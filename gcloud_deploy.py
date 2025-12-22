#!/usr/bin/env python3
"""
Deployment script for bris.kr URL Shortener
This script manages deployment to Google App Engine for briskr project.
"""

import subprocess
import json
import time
import os
import sys
import random
import string

# Configuration - BRISKR PROJECT SPECIFIC
EXPECTED_PROJECT_ID = "briskr"  # Critical: This must match your project
SERVICE_NAME = "default"
VERSION_MAX = 10  # Keep 10 versions (minimal app, less storage needed)
KUMORI_PROJECT = "kumori-404602"  # Database/secrets project

def print_separator():
    """Print a visual separator in console output."""
    print("\n" + "="*70 + "\n")

def check_gcloud_project():
    """Verify we're using the correct GCP project - CRITICAL SAFEGUARD."""
    print_separator()
    print("🔒 VERIFYING GOOGLE CLOUD PROJECT CONFIGURATION...")
    print(f"Expected project: {EXPECTED_PROJECT_ID}")
    
    try:
        current_project = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        ).stdout.decode().strip()
        
        print(f"Current project:  {current_project}")
        
        if current_project != EXPECTED_PROJECT_ID:
            print(f"❌ ERROR: Current gcloud project is '{current_project}' but expected '{EXPECTED_PROJECT_ID}'")
            print(f"🔄 Attempting to switch to the correct project...")
            
            # Try to use an existing configuration first
            try:
                configs_result = subprocess.run(
                    ["gcloud", "config", "configurations", "list", "--format=value(name)"],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
                )
                configs = configs_result.stdout.decode().strip().split('\n')
                
                if "briskr-config" in configs:
                    print("📋 Using existing briskr-config configuration")
                    subprocess.run(
                        ["gcloud", "config", "configurations", "activate", "briskr-config"],
                        check=True
                    )
                else:
                    print("⚙️  Setting project directly")
                    subprocess.run(
                        ["gcloud", "config", "set", "project", EXPECTED_PROJECT_ID],
                        check=True
                    )
            except subprocess.CalledProcessError:
                print("⚙️  Setting project directly")
                subprocess.run(
                    ["gcloud", "config", "set", "project", EXPECTED_PROJECT_ID],
                    check=True
                )
            
            # CRITICAL: Verify the switch was successful
            current_project = subprocess.run(
                ["gcloud", "config", "get-value", "project"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
            ).stdout.decode().strip()
            
            if current_project != EXPECTED_PROJECT_ID:
                print(f"❌ CRITICAL ERROR: Failed to switch to project {EXPECTED_PROJECT_ID}")
                print("🛑 DEPLOYMENT ABORTED to prevent deploying to wrong project!")
                print("")
                print("Please manually set the project with one of these commands:")
                print(f"  gcloud config configurations activate briskr-config")
                print(f"  gcloud config set project {EXPECTED_PROJECT_ID}")
                print("")
                print("Then re-run this script.")
                sys.exit(1)
            else:
                print(f"✅ Successfully switched to project {EXPECTED_PROJECT_ID}")
        else:
            print(f"✅ Project verification passed - correctly configured for {EXPECTED_PROJECT_ID}")
    
    except subprocess.CalledProcessError as e:
        print(f"❌ Error checking Google Cloud project: {e}")
        print("🛑 DEPLOYMENT ABORTED")
        sys.exit(1)


def check_kumori_permissions():
    """Verify briskr has access to kumori secrets."""
    print_separator()
    print(f"🔐 VERIFYING KUMORI PERMISSIONS...")
    print(f"Checking access to {KUMORI_PROJECT} secrets...")
    
    try:
        # Try to access a known secret
        result = subprocess.run(
            ["gcloud", "secrets", "versions", "access", "latest",
             "--secret=KUMORI_POSTGRES_DB_NAME",
             f"--project={KUMORI_PROJECT}"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        
        if result.returncode == 0:
            print(f"✅ Access to {KUMORI_PROJECT} secrets confirmed")
            return True
        else:
            print(f"⚠️  Cannot verify secret access (may still work with service account)")
            return True  # Don't block deployment, service account may have access
            
    except Exception as e:
        print(f"⚠️  Could not verify permissions: {e}")
        return True  # Don't block deployment


def get_versions(service_name):
    """Fetch the current versions of the App Engine service."""
    print(f"📋 Checking existing versions for service: {service_name}...")
    try:
        result = subprocess.run(
            ["gcloud", "app", "versions", "list", 
             "--service", service_name, 
             "--format", "json", 
             "--project", EXPECTED_PROJECT_ID],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        versions = json.loads(result.stdout)
        versions.sort(key=lambda x: x["version"]["createTime"], reverse=True)
        return versions
    except subprocess.CalledProcessError as e:
        if "Service not found" in e.stderr.decode() or f"Service [{service_name}] not found" in e.stderr.decode():
            print(f"📝 Service {service_name} not found. It will be created during deployment.")
            return []
        else:
            print(f"❌ Error getting versions: {e.stderr.decode()}")
            raise e


def delete_old_versions(service_name, versions_to_delete):
    """Delete older versions to maintain version limit."""
    if not versions_to_delete:
        return
    
    print(f"🧹 Cleaning up old versions. Deleting {len(versions_to_delete)} older versions...")
    
    for v in versions_to_delete:
        version_id = v["id"]
        print(f"  - Deleting version {service_name}-{version_id}")
        subprocess.run(
            ["gcloud", "app", "versions", "delete", version_id, 
             "--service", service_name, 
             "--quiet", 
             "--project", EXPECTED_PROJECT_ID],
            check=True)
    
    print("✅ Cleanup complete.")


def list_files_to_upload():
    """List files that will be uploaded to Google Cloud Storage."""
    print("📁 Files to be uploaded:")
    
    # Parse .gcloudignore
    ignored_patterns = set()
    if os.path.exists('.gcloudignore'):
        with open('.gcloudignore', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    ignored_patterns.add(line.rstrip('/'))
    
    # Default ignore patterns
    if not ignored_patterns:
        ignored_patterns = {
            '.git', '__pycache__', '*.pyc', '.env', 'venv*', 
            '.vscode', '.idea', '*.md'
        }
    
    # Walk directory and respect .gcloudignore patterns
    files_to_upload = []
    for root, dirs, files in os.walk('.'):
        # Remove ignored directories
        dirs[:] = [d for d in dirs if not any(
            d == pattern or d.startswith(pattern.rstrip('*'))
            for pattern in ignored_patterns
        )]
        
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), '.')
            # Skip if file matches any ignore pattern
            if not any(
                rel_path.startswith(pattern.rstrip('*')) or 
                file.endswith(pattern.lstrip('*'))
                for pattern in ignored_patterns
            ):
                files_to_upload.append(rel_path)
    
    for file in sorted(files_to_upload):
        print(f"  - {file}")
    
    print(f"\n📊 Total files to upload: {len(files_to_upload)}")


def generate_version_name():
    """Generate a valid version name."""
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"v-{random_string}"


def get_admin_key():
    """Get or prompt for admin key."""
    admin_key = os.environ.get('ADMIN_KEY')
    
    if not admin_key:
        print_separator()
        print("🔑 ADMIN KEY CONFIGURATION")
        print("No ADMIN_KEY environment variable found.")
        print("")
        response = input("Enter admin key (or press Enter to generate new one): ").strip()
        
        if response:
            admin_key = response
        else:
            import secrets
            admin_key = secrets.token_urlsafe(32)
            print(f"\n🔐 Generated new admin key: {admin_key}")
            print("⚠️  SAVE THIS KEY - you'll need it to access the admin panel!")
    
    return admin_key


def deploy_service(service_name, yaml_path, admin_key):
    """Deploy the application to Google App Engine."""
    start_time = time.time()
    current_directory = os.path.dirname(os.path.abspath(yaml_path)) or '.'
    
    print_separator()
    print(f"🚀 DEPLOYING BRIS.KR URL SHORTENER TO GOOGLE APP ENGINE")
    print(f"📦 Project: {EXPECTED_PROJECT_ID}")
    print(f"🗄️  Database: {KUMORI_PROJECT}")
    print(f"⚙️  Service: {service_name}")
    print(f"📂 Deploy from: {current_directory}")
    print(f"📄 Using config: {yaml_path}")
    print_separator()
    
    # Check current versions
    try:
        versions = get_versions(service_name)
        print(f"✅ {len(versions)} versions retrieved successfully.")
    except subprocess.CalledProcessError:
        versions = []
        print(f"📝 First deployment for service {service_name}.")
    
    print(f"📊 You currently have {len(versions)} versions for {service_name}.")
    if versions:
        print(f"📋 The latest version is {versions[0]['id']}")
    
    # Show files to upload
    print_separator()
    list_files_to_upload()
    
    # Deploy new version
    print_separator()
    version_name = generate_version_name()
    print(f"🚀 Deploying new version: {version_name}")
    print(f"🔑 Setting ADMIN_KEY environment variable")
    
    try:
        result = subprocess.run([
            "gcloud", "app", "deploy", yaml_path, 
            "--quiet", 
            "--project", EXPECTED_PROJECT_ID,
            "--version", version_name,
            f"--set-env-vars=ADMIN_KEY={admin_key}"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
        print("✅ Deployment successful!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to deploy. Error: {e.stderr.decode()}")
        return False
    
    # Delete old versions if needed
    if len(versions) >= VERSION_MAX:
        print_separator()
        try:
            updated_versions = get_versions(service_name)
            versions_to_delete = updated_versions[VERSION_MAX:]
            delete_old_versions(service_name, versions_to_delete)
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Failed to delete old versions: {e.stderr.decode()}")

    # Calculate execution time
    end_time = time.time()
    execution_time = end_time - start_time
    
    # Display success info
    print_separator()
    print(f"⏱️  Deployment completed in {execution_time:.2f} seconds.")
    print(f"")
    print(f"🌐 Your URL shortener is now live at:")
    print(f"   https://{EXPECTED_PROJECT_ID}.appspot.com")
    print(f"")
    print(f"🔐 Admin panel:")
    print(f"   https://{EXPECTED_PROJECT_ID}.appspot.com?key={admin_key}")
    print(f"")
    print(f"📝 After configuring custom domain:")
    print(f"   https://bris.kr?key={admin_key}")
    print_separator()
    
    return True


def main_deploy():
    """Main deployment function."""
    # CRITICAL: Verify project before doing ANYTHING
    check_gcloud_project()
    
    # Check kumori permissions
    check_kumori_permissions()
    
    # Get admin key
    admin_key = get_admin_key()
    
    # Deploy the service
    success = deploy_service(SERVICE_NAME, 'app.yaml', admin_key)
    
    if not success:
        sys.exit(1)
    
    # Prompt to tail logs
    print(f"\n📋 Would you like to tail logs? (Press Ctrl+C to stop)")
    response = input("Tail logs? [Y/n]: ").strip().lower()
    
    if response not in ('n', 'no'):
        try:
            subprocess.run([
                "gcloud", "app", "logs", "tail",
                "--service", SERVICE_NAME,
                "--project", EXPECTED_PROJECT_ID
            ])
        except KeyboardInterrupt:
            print("\n\n⏹️  Stopped tailing logs.")
            print(f"📋 View logs anytime: gcloud app logs tail -s {SERVICE_NAME} --project {EXPECTED_PROJECT_ID}")


if __name__ == "__main__":
    print("🔗 bris.kr URL Shortener Deployment")
    print(f"🔒 Keeping max {VERSION_MAX} versions")
    main_deploy()
