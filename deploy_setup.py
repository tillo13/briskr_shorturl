#!/usr/bin/env python3
"""
bris.kr - Complete GCP Setup Script

This script creates the entire GCP project and configures all permissions
using Python SDK calls instead of gcloud CLI.

Usage:
    python deploy_setup.py --billing-account=XXXXXX-XXXXXX-XXXXXX
    
Requirements:
    pip install google-cloud-resource-manager google-cloud-billing google-cloud-service-usage google-api-python-client google-auth
"""

import argparse
import time
import subprocess
import sys

# Google Cloud Python SDK imports
from google.cloud import resourcemanager_v3
from google.cloud import billing_v1
from google.cloud import service_usage_v1
from google.api_core import exceptions as gcp_exceptions
from google.iam.v1 import iam_policy_pb2
from google.protobuf import field_mask_pb2
from googleapiclient import discovery
from google.auth import default as get_default_credentials

# =============================================================================
# CONFIGURATION
# =============================================================================

PROJECT_ID = "briskr"
PROJECT_NAME = "Bris KR URL Shortener"
REGION = "us-central1"
KUMORI_PROJECT = "kumori-404602"

# APIs to enable
REQUIRED_APIS = [
    "appengine.googleapis.com",
    "secretmanager.googleapis.com",
    "sqladmin.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudresourcemanager.googleapis.com",
    "iam.googleapis.com",
]

# IAM roles to grant on kumori-404602
KUMORI_ROLES = [
    "roles/secretmanager.secretAccessor",
    "roles/cloudsql.client",
]

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def print_step(step_num: int, message: str):
    """Print a formatted step message."""
    print(f"\n{'='*60}")
    print(f"STEP {step_num}: {message}")
    print('='*60)


def print_success(message: str):
    print(f"✅ {message}")


def print_warning(message: str):
    print(f"⚠️  {message}")


def print_error(message: str):
    print(f"❌ {message}")


def wait_for_operation(message: str, seconds: int = 5):
    """Wait with a message."""
    print(f"⏳ {message} (waiting {seconds}s)...")
    time.sleep(seconds)


# =============================================================================
# STEP 1: CREATE PROJECT
# =============================================================================

def create_project() -> bool:
    """Create the GCP project."""
    print_step(1, "Creating GCP Project")
    
    client = resourcemanager_v3.ProjectsClient()
    
    # Check if project already exists
    try:
        existing = client.get_project(name=f"projects/{PROJECT_ID}")
        print_warning(f"Project '{PROJECT_ID}' already exists (state: {existing.state.name})")
        return True
    except gcp_exceptions.NotFound:
        pass
    except gcp_exceptions.PermissionDenied:
        print_warning(f"Project '{PROJECT_ID}' may exist but you don't have access")
        return True
    
    # Create new project
    try:
        project = resourcemanager_v3.Project(
            project_id=PROJECT_ID,
            display_name=PROJECT_NAME,
        )
        
        operation = client.create_project(project=project)
        print(f"Creating project '{PROJECT_ID}'...")
        
        # Wait for operation to complete
        result = operation.result(timeout=120)
        print_success(f"Project '{PROJECT_ID}' created successfully!")
        return True
        
    except gcp_exceptions.AlreadyExists:
        print_warning(f"Project '{PROJECT_ID}' already exists")
        return True
    except Exception as e:
        print_error(f"Failed to create project: {e}")
        return False


# =============================================================================
# STEP 2: LINK BILLING
# =============================================================================

def link_billing(billing_account_id: str) -> bool:
    """Link billing account to project."""
    print_step(2, "Linking Billing Account")
    
    client = billing_v1.CloudBillingClient()
    
    # Format billing account name
    if not billing_account_id.startswith("billingAccounts/"):
        billing_account_name = f"billingAccounts/{billing_account_id}"
    else:
        billing_account_name = billing_account_id
    
    try:
        # Check current billing info
        project_name = f"projects/{PROJECT_ID}"
        current = client.get_project_billing_info(name=project_name)
        
        if current.billing_account_name:
            print_warning(f"Project already has billing: {current.billing_account_name}")
            return True
        
        # Update billing info
        billing_info = billing_v1.ProjectBillingInfo(
            name=project_name,
            billing_account_name=billing_account_name,
        )
        
        client.update_project_billing_info(
            name=project_name,
            project_billing_info=billing_info,
        )
        
        print_success(f"Billing account linked: {billing_account_name}")
        return True
        
    except Exception as e:
        print_error(f"Failed to link billing: {e}")
        print("You may need to link billing manually in the console.")
        return False


# =============================================================================
# STEP 3: ENABLE APIS
# =============================================================================

def enable_apis() -> bool:
    """Enable required APIs."""
    print_step(3, "Enabling Required APIs")
    
    client = service_usage_v1.ServiceUsageClient()
    parent = f"projects/{PROJECT_ID}"
    
    for api in REQUIRED_APIS:
        try:
            service_name = f"{parent}/services/{api}"
            
            # Check if already enabled
            try:
                service = client.get_service(name=service_name)
                if service.state == service_usage_v1.State.ENABLED:
                    print_success(f"{api} (already enabled)")
                    continue
            except gcp_exceptions.NotFound:
                pass
            
            # Enable the API
            print(f"Enabling {api}...")
            operation = client.enable_service(name=service_name)
            operation.result(timeout=180)
            print_success(f"{api}")
            
        except Exception as e:
            print_error(f"Failed to enable {api}: {e}")
            return False
    
    # Wait for APIs to propagate
    wait_for_operation("Waiting for APIs to propagate", 10)
    return True


# =============================================================================
# STEP 4: CREATE APP ENGINE
# =============================================================================

def create_app_engine() -> bool:
    """Create App Engine application."""
    print_step(4, "Creating App Engine Application")
    
    credentials, _ = get_default_credentials()
    service = discovery.build('appengine', 'v1', credentials=credentials)
    
    try:
        # Check if App Engine already exists
        app = service.apps().get(appsId=PROJECT_ID).execute()
        print_warning(f"App Engine already exists in {app.get('locationId', 'unknown')}")
        return True
        
    except Exception as e:
        if "404" not in str(e) and "NOT_FOUND" not in str(e):
            print_error(f"Error checking App Engine: {e}")
    
    try:
        # Create App Engine application
        print(f"Creating App Engine in {REGION}...")
        
        body = {
            "id": PROJECT_ID,
            "locationId": REGION,
        }
        
        operation = service.apps().create(body=body).execute()
        
        # Wait for operation to complete
        op_name = operation.get('name')
        while True:
            result = service.apps().operations().get(
                appsId=PROJECT_ID,
                operationsId=op_name.split('/')[-1]
            ).execute()
            
            if result.get('done'):
                if result.get('error'):
                    print_error(f"App Engine creation failed: {result['error']}")
                    return False
                break
            
            time.sleep(5)
        
        print_success(f"App Engine created in {REGION}")
        return True
        
    except Exception as e:
        if "already exists" in str(e).lower():
            print_warning("App Engine already exists")
            return True
        print_error(f"Failed to create App Engine: {e}")
        return False


# =============================================================================
# STEP 5: GRANT KUMORI PERMISSIONS
# =============================================================================

def grant_kumori_permissions() -> bool:
    """Grant briskr service account access to kumori-404602."""
    print_step(5, "Granting Cross-Project Permissions")
    
    service_account = f"serviceAccount:{PROJECT_ID}@appspot.gserviceaccount.com"
    
    credentials, _ = get_default_credentials()
    service = discovery.build('cloudresourcemanager', 'v1', credentials=credentials)
    
    try:
        # Get current IAM policy for kumori project
        policy = service.projects().getIamPolicy(
            resource=KUMORI_PROJECT,
            body={}
        ).execute()
        
        # Add roles
        for role in KUMORI_ROLES:
            # Check if binding already exists
            binding_exists = False
            for binding in policy.get('bindings', []):
                if binding['role'] == role:
                    if service_account not in binding.get('members', []):
                        binding['members'].append(service_account)
                        print(f"Adding {PROJECT_ID} to existing {role} binding")
                    else:
                        print_warning(f"{role} already granted")
                    binding_exists = True
                    break
            
            # Create new binding if doesn't exist
            if not binding_exists:
                if 'bindings' not in policy:
                    policy['bindings'] = []
                policy['bindings'].append({
                    'role': role,
                    'members': [service_account]
                })
                print(f"Creating new binding for {role}")
        
        # Update policy
        service.projects().setIamPolicy(
            resource=KUMORI_PROJECT,
            body={'policy': policy}
        ).execute()
        
        print_success(f"Granted {PROJECT_ID} access to {KUMORI_PROJECT}")
        print_success(f"  - {', '.join(KUMORI_ROLES)}")
        return True
        
    except Exception as e:
        print_error(f"Failed to grant permissions: {e}")
        print("\nYou may need to run these commands manually:")
        for role in KUMORI_ROLES:
            print(f"  gcloud projects add-iam-policy-binding {KUMORI_PROJECT} \\")
            print(f"    --member='{service_account}' \\")
            print(f"    --role='{role}'")
        return False


# =============================================================================
# STEP 6: GENERATE ADMIN KEY
# =============================================================================

def generate_admin_key() -> str:
    """Generate a secure admin key."""
    print_step(6, "Generating Admin Key")
    
    import secrets
    key = secrets.token_urlsafe(32)
    
    print_success(f"Admin key generated")
    print(f"\n🔑 YOUR ADMIN KEY (save this!):\n")
    print(f"   {key}")
    print()
    
    return key


# =============================================================================
# STEP 7: DEPLOY APPLICATION
# =============================================================================

def deploy_application(admin_key: str) -> bool:
    """Deploy the application to App Engine."""
    print_step(7, "Deploying Application")
    
    print("Deploying to App Engine...")
    print("(This may take 2-3 minutes)\n")
    
    try:
        result = subprocess.run(
            [
                "gcloud", "app", "deploy", "app.yaml",
                f"--project={PROJECT_ID}",
                f"--set-env-vars=ADMIN_KEY={admin_key}",
                "--quiet"
            ],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        if result.returncode == 0:
            print_success("Application deployed!")
            print(f"\n🚀 Your app is live at:")
            print(f"   https://{PROJECT_ID}.appspot.com")
            print(f"\n🔐 Admin panel:")
            print(f"   https://{PROJECT_ID}.appspot.com?key={admin_key}")
            return True
        else:
            print_error(f"Deployment failed:\n{result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print_error("Deployment timed out")
        return False
    except FileNotFoundError:
        print_error("gcloud CLI not found. Please install Google Cloud SDK.")
        return False
    except Exception as e:
        print_error(f"Deployment error: {e}")
        return False


# =============================================================================
# MAIN
# =============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Set up briskr GCP project and deploy URL shortener"
    )
    parser.add_argument(
        "--billing-account",
        required=True,
        help="Billing account ID (format: XXXXXX-XXXXXX-XXXXXX)"
    )
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="Skip the deployment step (just set up project)"
    )
    parser.add_argument(
        "--admin-key",
        help="Use a specific admin key instead of generating one"
    )
    
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("  bris.kr - GCP Project Setup")
    print("="*60)
    print(f"\nProject ID: {PROJECT_ID}")
    print(f"Region: {REGION}")
    print(f"Database: {KUMORI_PROJECT}")
    
    # Step 1: Create project
    if not create_project():
        sys.exit(1)
    
    # Step 2: Link billing
    if not link_billing(args.billing_account):
        print_warning("Continuing without billing (may fail later)...")
    
    # Step 3: Enable APIs
    if not enable_apis():
        sys.exit(1)
    
    # Step 4: Create App Engine
    if not create_app_engine():
        sys.exit(1)
    
    # Step 5: Grant kumori permissions
    if not grant_kumori_permissions():
        print_warning("You'll need to grant permissions manually before deploying")
    
    # Step 6: Generate admin key
    admin_key = args.admin_key or generate_admin_key()
    
    # Step 7: Deploy (optional)
    if not args.skip_deploy:
        wait_for_operation("Waiting for permissions to propagate", 10)
        if not deploy_application(admin_key):
            print("\n⚠️  Deployment failed. Try manually:")
            print(f"   gcloud app deploy app.yaml --project={PROJECT_ID} --set-env-vars=ADMIN_KEY={admin_key}")
            sys.exit(1)
    else:
        print("\n📋 Skipped deployment. To deploy manually:")
        print(f"   gcloud app deploy app.yaml --project={PROJECT_ID} --set-env-vars=ADMIN_KEY={admin_key}")
    
    # Final summary
    print("\n" + "="*60)
    print("  SETUP COMPLETE!")
    print("="*60)
    print(f"""
Next steps:
1. Visit https://{PROJECT_ID}.appspot.com?key={admin_key}
2. Configure custom domain (bris.kr) in App Engine settings
3. Add DNS records at your domain registrar:
   - A record: @ → (IP from GCP console)
   - AAAA record: @ → (IPv6 from GCP console)
   
Save your admin key:
   {admin_key}
""")


if __name__ == "__main__":
    main()
