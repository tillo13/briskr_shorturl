#!/bin/bash
# gcp_setup.sh - One-time GCP project setup for briskr

set -e

# Configuration
PROJECT_ID="briskr"
REGION="us-central1"
KUMORI_PROJECT="kumori-404602"
BILLING_ACCOUNT="${1:-}"

echo ""
echo "============================================================"
echo "  bris.kr - GCP Project Setup"
echo "============================================================"
echo "Project ID: $PROJECT_ID"
echo "Region: $REGION"
echo "Database: $KUMORI_PROJECT"
echo ""

# Check for billing account argument
if [ -z "$BILLING_ACCOUNT" ]; then
    echo "Usage: ./gcp_setup.sh BILLING_ACCOUNT_ID"
    echo ""
    echo "Get your billing account ID with:"
    echo "  gcloud billing accounts list"
    echo ""
    echo "Then run:"
    echo "  ./gcp_setup.sh 011C1C-EB09FF-06FE43"
    exit 1
fi

# Step 1: Create project
echo "============================================================"
echo "STEP 1: Creating GCP Project"
echo "============================================================"
if gcloud projects describe $PROJECT_ID &>/dev/null; then
    echo "✅ Project '$PROJECT_ID' already exists"
else
    echo "Creating project '$PROJECT_ID'..."
    gcloud projects create $PROJECT_ID --name="Bris KR URL Shortener"
    echo "✅ Project created"
fi

# Set as current project
gcloud config set project $PROJECT_ID

# Step 2: Link billing
echo ""
echo "============================================================"
echo "STEP 2: Linking Billing Account"
echo "============================================================"
echo "Linking billing account $BILLING_ACCOUNT..."
gcloud billing projects link $PROJECT_ID --billing-account=$BILLING_ACCOUNT
echo "✅ Billing linked"

# Step 3: Enable APIs
echo ""
echo "============================================================"
echo "STEP 3: Enabling Required APIs"
echo "============================================================"
APIS="appengine.googleapis.com secretmanager.googleapis.com sqladmin.googleapis.com cloudbuild.googleapis.com"
for api in $APIS; do
    echo "Enabling $api..."
    gcloud services enable $api --project=$PROJECT_ID
    echo "✅ $api enabled"
done

# Step 4: Create App Engine
echo ""
echo "============================================================"
echo "STEP 4: Creating App Engine Application"
echo "============================================================"
if gcloud app describe --project=$PROJECT_ID &>/dev/null; then
    echo "✅ App Engine already exists"
else
    echo "Creating App Engine in $REGION..."
    gcloud app create --region=$REGION --project=$PROJECT_ID
    echo "✅ App Engine created"
fi

# Step 5: Grant kumori permissions
echo ""
echo "============================================================"
echo "STEP 5: Granting Cross-Project Permissions"
echo "============================================================"
SERVICE_ACCOUNT="${PROJECT_ID}@appspot.gserviceaccount.com"
echo "Service account: $SERVICE_ACCOUNT"

echo "Granting Secret Manager access..."
gcloud projects add-iam-policy-binding $KUMORI_PROJECT \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/secretmanager.secretAccessor" \
    --quiet
echo "✅ Secret Manager access granted"

echo "Granting Cloud SQL access..."
gcloud projects add-iam-policy-binding $KUMORI_PROJECT \
    --member="serviceAccount:$SERVICE_ACCOUNT" \
    --role="roles/cloudsql.client" \
    --quiet
echo "✅ Cloud SQL access granted"

# Step 6: Generate admin key
echo ""
echo "============================================================"
echo "STEP 6: Generating Admin Key"
echo "============================================================"
ADMIN_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
echo ""
echo "🔑 YOUR ADMIN KEY (save this!):"
echo ""
echo "   $ADMIN_KEY"
echo ""

# Save admin key to file for reference
echo "$ADMIN_KEY" > .admin_key
echo "(Also saved to .admin_key file)"

# Step 7: Deploy
echo ""
echo "============================================================"
echo "STEP 7: Deploying Application"
echo "============================================================"
echo "Deploying to App Engine..."
gcloud app deploy app.yaml --project=$PROJECT_ID --set-env-vars="ADMIN_KEY=$ADMIN_KEY" --quiet

# Done!
echo ""
echo "============================================================"
echo "✅ SETUP COMPLETE!"
echo "============================================================"
echo ""
echo "🌐 Your URL shortener is live at:"
echo "   https://${PROJECT_ID}.appspot.com"
echo ""
echo "🔐 Admin panel:"
echo "   https://${PROJECT_ID}.appspot.com?key=$ADMIN_KEY"
echo ""
echo "📝 Next: Configure custom domain (bris.kr) in App Engine settings"
echo ""
echo "📋 View logs:"
echo "   gcloud app logs tail -s default --project=$PROJECT_ID"
echo ""