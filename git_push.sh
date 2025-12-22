#!/bin/bash

# BRISKR PROJECT CONFIGURATION - CRITICAL SAFEGUARDS
EXPECTED_PROJECT="briskr"
SERVICE_NAME="default"
GITHUB_REPO="https://github.com/tillo13/briskr_shorturl.git"

# Check if a commit message was provided
if [ -z "$1" ]; then
  echo "❌ You must provide a commit message."
  echo "Usage: ./git_push.sh \"Your commit message\""
  exit 1
fi

echo ""
echo "🔗 bris.kr URL Shortener - Git Push & Deploy"
echo "=============================================="
echo ""

# Initialize the git repository if not already done
if [ ! -d ".git" ]; then
  echo "🔧 Setting up git repository for the first time..."

  git init
  if [ ! -f "README.md" ]; then
    echo "# bris.kr URL Shortener" >> README.md
    git add README.md
    git commit -m "Initial commit"
  fi

  git remote add origin $GITHUB_REPO
  git branch -M main
  git push -u origin main
  
  echo "✅ Git repository initialized"
fi

# Add all changes to git
echo "📝 Adding changes to git..."
git add .

# Commit the changes with the provided message
echo "💾 Committing: $1"
git commit -m "$1"

# Push to GitHub
echo "🚀 Pushing to GitHub..."
git push origin main

if [ $? -ne 0 ]; then
  echo ""
  echo "####################################"
  echo "# MERGE CONFLICT RESOLUTION STEPS: #"
  echo "####################################"
  echo ""
  echo "1. Fetch the latest changes:"
  echo "   git fetch origin"
  echo ""
  echo "2. Merge the changes:"
  echo "   git merge origin/main"
  echo ""
  echo "3. Resolve any conflicts in the files"
  echo ""
  echo "4. Stage resolved files:"
  echo "   git add <filename>"
  echo ""
  echo "5. Commit the merge:"
  echo "   git commit -m 'Resolve merge conflicts'"
  echo ""
  echo "6. Push again:"
  echo "   git push origin main"
  echo ""
  exit 1
fi

echo "✅ Pushed to GitHub successfully"
echo ""

# CRITICAL SAFEGUARD: Verify Google Cloud project
CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
echo "=== GOOGLE CLOUD PROJECT VERIFICATION ==="
echo "Expected project: $EXPECTED_PROJECT"
echo "Current project:  $CURRENT_PROJECT"

if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
  echo ""
  echo "❌ ERROR: Google Cloud project mismatch!"
  echo "Current project '$CURRENT_PROJECT' does not match expected project '$EXPECTED_PROJECT'"
  echo ""
  echo "🔄 Attempting to switch to correct project..."
  
  # Try existing configuration first
  if gcloud config configurations list --format="value(name)" 2>/dev/null | grep -q "briskr-config"; then
    echo "📋 Using existing briskr-config configuration"
    gcloud config configurations activate briskr-config
  else
    echo "⚙️  Setting project directly to $EXPECTED_PROJECT"
    gcloud config set project $EXPECTED_PROJECT
  fi
  
  # Verify the switch
  CURRENT_PROJECT=$(gcloud config get-value project 2>/dev/null)
  if [ "$CURRENT_PROJECT" != "$EXPECTED_PROJECT" ]; then
    echo ""
    echo "❌ CRITICAL ERROR: Failed to switch to $EXPECTED_PROJECT project!"
    echo "🛑 Deployment ABORTED to prevent deploying to wrong project."
    echo ""
    echo "Please manually set the project:"
    echo "  gcloud config set project $EXPECTED_PROJECT"
    echo ""
    echo "Then re-run this script."
    exit 1
  else
    echo "✅ Successfully switched to $EXPECTED_PROJECT project"
  fi
else
  echo "✅ Project verification passed"
fi

echo "==========================================="
echo ""

# Deploy to Google App Engine
echo "🚀 Starting deployment to Google App Engine..."
python3 gcloud_deploy.py
DEPLOY_EXIT_CODE=$?

if [ $DEPLOY_EXIT_CODE -eq 0 ]; then
  echo ""
  echo "=============================================="
  echo "✅ DEPLOYMENT COMPLETE!"
  echo "=============================================="
  echo ""
  echo "🌐 Live at: https://$EXPECTED_PROJECT.appspot.com"
  echo "🔗 Custom domain: https://bris.kr (after DNS setup)"
  echo ""
  echo "📋 View logs: gcloud app logs tail -s $SERVICE_NAME --project $EXPECTED_PROJECT"
  echo ""
else
  echo ""
  echo "❌ Deployment failed with exit code: $DEPLOY_EXIT_CODE"
  echo "Please check the error messages above."
  exit $DEPLOY_EXIT_CODE
fi
