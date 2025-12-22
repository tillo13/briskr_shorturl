#!/bin/bash
# setup_local.sh - Set up local development environment and git repo

set -e

echo "🚀 Setting up briskr_shorturl..."

# Create virtual environment
if [ ! -d "venv_briskr" ]; then
    echo "📦 Creating virtual environment..."
    python3 -m venv venv_briskr
else
    echo "✅ venv_briskr already exists"
fi

# Activate and install dependencies
echo "📥 Installing dependencies..."
source venv_briskr/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
pip install -r requirements-deploy.txt

# Initialize git if needed
if [ ! -d ".git" ]; then
    echo "🔧 Initializing git repository..."
    git init
    git branch -M main
fi

# Add remote if not exists
if ! git remote | grep -q origin; then
    echo "🔗 Adding GitHub remote..."
    git remote add origin https://github.com/tillo13/briskr_shorturl.git
fi

echo ""
echo "✅ Local setup complete!"
echo ""
echo "Next steps:"
echo "  1. Activate venv:  source venv_briskr/bin/activate"
echo "  2. Deploy to GCP:  python deploy_setup.py --billing-account=YOUR_BILLING_ID"
echo "  3. Push to GitHub: git add . && git commit -m 'Initial commit' && git push -u origin main"
echo ""
