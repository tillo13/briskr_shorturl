# bris.kr - Minimal URL Shortener

Super simple URL shortener using your kumori PostgreSQL database.

## Architecture

```
┌─────────────┐     ┌─────────────────────┐     ┌──────────────────┐
│   bris.kr   │────▶│  briskr (GAE)       │────▶│ kumori-404602    │
│   domain    │     │  App Engine         │     │ PostgreSQL + SM  │
└─────────────┘     └─────────────────────┘     └──────────────────┘
```

Uses `KUMORI_POSTGRES_*` secrets - the canonical database credentials.

---

## 🐍 Option A: One-Command Python Setup (Recommended)

```bash
# 1. Install deployment dependencies
pip install -r requirements-deploy.txt

# 2. Run the setup script (does EVERYTHING)
python deploy_setup.py --billing-account=XXXXXX-XXXXXX-XXXXXX
```

This single command:
- ✅ Creates the `briskr` GCP project
- ✅ Links your billing account
- ✅ Enables all required APIs
- ✅ Creates App Engine application
- ✅ Grants cross-project permissions to kumori-404602
- ✅ Generates secure admin key
- ✅ Deploys the application

### Script Options

```bash
# Just setup, don't deploy yet
python deploy_setup.py --billing-account=XXXXXX --skip-deploy

# Use a specific admin key
python deploy_setup.py --billing-account=XXXXXX --admin-key=my_custom_key
```

---

## 🔧 Option B: Manual gcloud CLI Setup

<details>
<summary>Click to expand manual steps</summary>

### 1. Create GCP Project

```bash
gcloud projects create briskr --name="Bris KR URL Shortener"
gcloud config set project briskr
gcloud billing projects link briskr --billing-account=YOUR_BILLING_ACCOUNT
```

### 2. Enable APIs

```bash
gcloud services enable appengine.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable sqladmin.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud app create --region=us-central1
```

### 3. Grant Cross-Project Access

```bash
gcloud projects add-iam-policy-binding kumori-404602 \
    --member="serviceAccount:briskr@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

gcloud projects add-iam-policy-binding kumori-404602 \
    --member="serviceAccount:briskr@appspot.gserviceaccount.com" \
    --role="roles/cloudsql.client"
```

### 4. Generate Admin Key & Deploy

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
gcloud app deploy --set-env-vars="ADMIN_KEY=YOUR_KEY"
```

</details>

---

## Configure Custom Domain (bris.kr)

After deployment, in GCP Console → App Engine → Settings → Custom domains:

1. Add `bris.kr`
2. Verify domain ownership (add TXT record at your registrar)
3. Add DNS records:
   - A record: `@` → (IP provided by GCP)
   - AAAA record: `@` → (IPv6 provided by GCP)
   - CNAME: `www` → `ghs.googlehosted.com`

---

## Usage

### Web Interface

Visit `https://bris.kr?key=YOUR_ADMIN_KEY` to:
- Create new short URLs
- See all URLs with click counts
- Use custom codes like `bris.kr/mylink`

### API

```bash
# Create short URL
curl -X POST https://bris.kr/api/shorten \
  -H "X-Admin-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/very/long/url", "code": "test"}'

# Get stats
curl "https://bris.kr/api/stats?key=YOUR_KEY"
```

---

## Database Table

Created automatically in your kumori database (public schema):

```sql
CREATE TABLE briskr_urls (
    id SERIAL PRIMARY KEY,
    short_code VARCHAR(20) UNIQUE NOT NULL,
    long_url TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    click_count INTEGER DEFAULT 0,
    last_clicked TIMESTAMP,
    created_by VARCHAR(100) DEFAULT 'anonymous'
);
```

---

## Files

```
briskr/
├── app.py              # Main Flask application (~200 lines)
├── app.yaml            # App Engine config
├── requirements.txt    # Runtime dependencies (4 packages)
├── deploy_setup.py     # Python GCP setup script
├── requirements-deploy.txt  # Setup script dependencies
├── .gitignore
├── .gcloudignore
└── static/
    └── favicon.ico     # (add your own)
```

---

## Costs

- **Idle**: $0/month (scales to zero with `min_instances: 0`)
- **Light use**: ~$0-5/month
- **Cloud SQL**: Already running for kumori (no additional cost)

---

## Troubleshooting

**502 Bad Gateway**
```bash
gcloud app logs tail -s default --project=briskr
```

**Secret Access Denied**
```bash
gcloud projects add-iam-policy-binding kumori-404602 \
    --member="serviceAccount:briskr@appspot.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"
```

**View Logs**
```bash
gcloud app logs tail -s default --project=briskr
```

---

## Future Enhancements (Post-MVP)

- [ ] Auth0/WorkOS login integration
- [ ] Per-user URL management  
- [ ] QR code generation
- [ ] Link expiration
- [ ] Analytics dashboard
