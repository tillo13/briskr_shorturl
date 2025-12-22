#!/usr/bin/env python3
"""
Deployment script for bris.kr URL Shortener
"""

import subprocess
import json
import time
import sys
import random
import string
import select

# Configuration
EXPECTED_PROJECT_ID = "briskr"
SERVICE_NAME = "default"
VERSION_MAX = 10

def print_separator():
    print("\n" + "="*70 + "\n")

def check_gcloud_project():
    """Verify we're using the correct GCP project."""
    print_separator()
    print("🔒 VERIFYING GOOGLE CLOUD PROJECT...")
    print(f"Expected: {EXPECTED_PROJECT_ID}")
    
    try:
        current_project = subprocess.run(
            ["gcloud", "config", "get-value", "project"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True
        ).stdout.decode().strip()
        
        print(f"Current:  {current_project}")
        
        if current_project != EXPECTED_PROJECT_ID:
            print(f"🔄 Switching to {EXPECTED_PROJECT_ID}...")
            subprocess.run(
                ["gcloud", "config", "set", "project", EXPECTED_PROJECT_ID],
                check=True
            )
        
        print(f"✅ Project verified: {EXPECTED_PROJECT_ID}")
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


def get_versions(service_name):
    """Fetch current versions."""
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
        if "not found" in e.stderr.decode().lower():
            return []
        raise e


def delete_old_versions(service_name, versions_to_delete):
    """Delete older versions."""
    if not versions_to_delete:
        return
    
    print(f"🧹 Deleting {len(versions_to_delete)} old versions...")
    
    for v in versions_to_delete:
        version_id = v["id"]
        subprocess.run(
            ["gcloud", "app", "versions", "delete", version_id, 
             "--service", service_name, 
             "--quiet", 
             "--project", EXPECTED_PROJECT_ID],
            check=True)
    
    print("✅ Cleanup complete")


def generate_version_name():
    random_string = ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"v-{random_string}"


def deploy_service():
    """Deploy to App Engine."""
    start_time = time.time()
    
    print_separator()
    print(f"🚀 DEPLOYING BRIS.KR TO APP ENGINE")
    print(f"📦 Project: {EXPECTED_PROJECT_ID}")
    print_separator()
    
    # Check versions
    try:
        versions = get_versions(SERVICE_NAME)
        print(f"📊 Current versions: {len(versions)}")
    except:
        versions = []
    
    # Deploy
    version_name = generate_version_name()
    print(f"🚀 Deploying version: {version_name}")
    
    try:
        subprocess.run([
            "gcloud", "app", "deploy", "app.yaml", 
            "--quiet", 
            "--project", EXPECTED_PROJECT_ID,
            "--version", version_name
        ], check=True)
        print("✅ Deployment successful!")
    except subprocess.CalledProcessError as e:
        print(f"❌ Deployment failed")
        return False
    
    # Cleanup old versions
    if len(versions) >= VERSION_MAX:
        print_separator()
        try:
            updated_versions = get_versions(SERVICE_NAME)
            delete_old_versions(SERVICE_NAME, updated_versions[VERSION_MAX:])
        except:
            pass

    # Done
    elapsed = time.time() - start_time
    print_separator()
    print(f"⏱️  Completed in {elapsed:.1f}s")
    print(f"🌐 Live at: https://{EXPECTED_PROJECT_ID}.appspot.com")
    print(f"🔗 Custom domain: https://bris.kr")
    print_separator()
    
    return True


def prompt_with_timeout(prompt, timeout=5, default='y'):
    """Prompt user with a timeout. Returns default if no response."""
    print(f"{prompt} (auto-yes in {timeout}s): ", end='', flush=True)
    
    try:
        # Unix/Mac: use select for timeout
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            response = sys.stdin.readline().strip().lower()
            return response if response else default
        else:
            print(f"\n⏱️  No response, defaulting to '{default}'")
            return default
    except:
        # Fallback for systems where select doesn't work on stdin
        try:
            response = input().strip().lower()
            return response if response else default
        except:
            return default


def main():
    check_gcloud_project()
    
    if not deploy_service():
        sys.exit(1)
    
    # Prompt for logs with 5 second timeout, defaults to yes
    print("📋 Tail logs? [Y/n]", end=' ')
    response = prompt_with_timeout("", timeout=5, default='y')
    
    if response not in ('n', 'no'):
        print("📋 Tailing logs... (Ctrl+C to stop)\n")
        try:
            subprocess.run([
                "gcloud", "app", "logs", "tail",
                "--service", SERVICE_NAME,
                "--project", EXPECTED_PROJECT_ID
            ])
        except KeyboardInterrupt:
            print("\n\n⏹️  Stopped tailing logs.")
    else:
        print(f"📋 Skipped. View logs anytime: gcloud app logs tail -s {SERVICE_NAME} --project {EXPECTED_PROJECT_ID}")


if __name__ == "__main__":
    main()