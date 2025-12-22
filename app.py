"""
bris.kr - Minimal URL Shortener
Uses kumori-404602 PostgreSQL database for storage
Schema: briskr.urls
"""
import os
import string
import random
from functools import wraps

from flask import Flask, request, redirect, jsonify, render_template_string
from google.cloud import secretmanager
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

GCP_SECRET_PROJECT = "kumori-404602"
BASE_URL = os.environ.get("BASE_URL", "https://bris.kr")

# Admin key from environment
ADMIN_KEY = os.environ.get("ADMIN_KEY", "change_this_key_123")

# ============================================================================
# DATABASE HELPERS
# ============================================================================

def get_secret(secret_id: str) -> str:
    """Fetch secret from Google Secret Manager."""
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{GCP_SECRET_PROJECT}/secrets/{secret_id}/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("UTF-8")


def get_db_connection():
    """Get database connection - works on GAE and locally."""
    is_gcp = os.environ.get('GAE_ENV', '').startswith('standard')
    
    dbname = get_secret('KUMORI_POSTGRES_DB_NAME')
    user = get_secret('KUMORI_POSTGRES_USERNAME')
    password = get_secret('KUMORI_POSTGRES_PASSWORD')
    
    if is_gcp:
        connection_name = get_secret('KUMORI_POSTGRES_CONNECTION_NAME')
        host = f"/cloudsql/{connection_name}"
    else:
        host = get_secret('KUMORI_POSTGRES_IP')
    
    conninfo = f"host={host} dbname={dbname} user={user} password={password}"
    return psycopg.connect(conninfo, row_factory=dict_row)


# ============================================================================
# URL SHORTENING LOGIC
# ============================================================================

def generate_short_code(length: int = 6) -> str:
    """Generate a random short code."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choices(chars, k=length))


def create_short_url(long_url: str, custom_code: str = None) -> dict:
    """Create a new short URL."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            short_code = custom_code or generate_short_code()
            
            # Check if code exists
            cur.execute(
                "SELECT short_code FROM briskr.urls WHERE short_code = %s",
                (short_code,)
            )
            if cur.fetchone():
                if custom_code:
                    return {"error": f"Code '{custom_code}' already exists"}
                short_code = generate_short_code(8)
            
            # Insert new URL
            cur.execute("""
                INSERT INTO briskr.urls (short_code, long_url)
                VALUES (%s, %s)
                RETURNING id, short_code, long_url, created_at
            """, (short_code, long_url))
            
            result = cur.fetchone()
            conn.commit()
            
            return {
                "short_url": f"{BASE_URL}/{result['short_code']}",
                "short_code": result['short_code'],
                "long_url": result['long_url'],
                "created_at": str(result['created_at'])
            }
    finally:
        conn.close()


def get_long_url(short_code: str) -> str | None:
    """Get long URL and increment click count."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE briskr.urls 
                SET click_count = click_count + 1,
                    last_clicked = CURRENT_TIMESTAMP
                WHERE short_code = %s
                RETURNING long_url
            """, (short_code,))
            
            result = cur.fetchone()
            conn.commit()
            
            return result['long_url'] if result else None
    finally:
        conn.close()


def get_stats() -> list:
    """Get all URLs with stats."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT short_code, long_url, click_count, created_at, last_clicked
                FROM briskr.urls
                ORDER BY created_at DESC
                LIMIT 100
            """)
            return cur.fetchall()
    finally:
        conn.close()


# ============================================================================
# AUTH HELPER
# ============================================================================

def check_admin_key() -> bool:
    """Check if admin key is valid from query param, form data, or header."""
    key = (
        request.args.get('key') or 
        request.form.get('key') or 
        request.headers.get('X-Admin-Key')
    )
    return key == ADMIN_KEY


def require_admin(f):
    """Simple admin key check."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not check_admin_key():
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated


# ============================================================================
# ROUTES
# ============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>bris.kr</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, system-ui, sans-serif;
            background: #0a0a0a; color: #fff;
            min-height: 100vh; padding: 2rem;
        }
        .container { max-width: 600px; margin: 0 auto; }
        h1 { font-size: 3rem; margin-bottom: 2rem; }
        h1 span { color: #666; }
        form { display: flex; flex-direction: column; gap: 1rem; }
        input, button { 
            padding: 1rem; font-size: 1rem; border: none; border-radius: 8px;
        }
        input { background: #1a1a1a; color: #fff; }
        input::placeholder { color: #666; }
        button { 
            background: #fff; color: #000; cursor: pointer;
            font-weight: bold; transition: opacity 0.2s;
        }
        button:hover { opacity: 0.9; }
        .result { 
            margin-top: 2rem; padding: 1.5rem; 
            background: #1a1a1a; border-radius: 8px;
        }
        .result a { color: #4ade80; word-break: break-all; }
        .stats { margin-top: 3rem; }
        .stats table { width: 100%; border-collapse: collapse; }
        .stats th, .stats td { 
            padding: 0.75rem; text-align: left; 
            border-bottom: 1px solid #333;
        }
        .stats td { font-family: monospace; font-size: 0.875rem; }
        .clicks { color: #4ade80; }
        .error { color: #f87171; }
    </style>
</head>
<body>
    <div class="container">
        <h1>bris<span>.kr</span></h1>
        
        <form method="POST" action="/shorten?key={{ key }}">
            <input type="url" name="url" placeholder="Paste long URL here..." required>
            <input type="text" name="code" placeholder="Custom code (optional)">
            <input type="hidden" name="key" value="{{ key }}">
            <button type="submit">Shorten</button>
        </form>
        
        {% if result %}
        <div class="result">
            {% if result.error %}
            <p class="error">{{ result.error }}</p>
            {% else %}
            <p>Short URL:</p>
            <p><a href="{{ result.short_url }}">{{ result.short_url }}</a></p>
            {% endif %}
        </div>
        {% endif %}
        
        {% if stats %}
        <div class="stats">
            <h2>Your URLs</h2>
            <table>
                <tr><th>Code</th><th>Destination</th><th>Clicks</th></tr>
                {% for url in stats %}
                <tr>
                    <td><a href="/{{ url.short_code }}">{{ url.short_code }}</a></td>
                    <td>{{ url.long_url[:50] }}{% if url.long_url|length > 50 %}...{% endif %}</td>
                    <td class="clicks">{{ url.click_count }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        {% endif %}
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    """Home page - show form and stats if admin."""
    key = request.args.get('key', '')
    stats = None
    if key == ADMIN_KEY:
        try:
            stats = get_stats()
        except Exception as e:
            print(f"Error getting stats: {e}")
    return render_template_string(HTML_TEMPLATE, key=key, result=None, stats=stats)


@app.route("/shorten", methods=["POST"])
@require_admin
def shorten():
    """Create new short URL."""
    long_url = request.form.get('url')
    custom_code = request.form.get('code', '').strip() or None
    key = request.args.get('key') or request.form.get('key', '')
    
    if not long_url:
        return render_template_string(HTML_TEMPLATE, key=key, 
                                      result={"error": "URL is required"}, stats=None)
    
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code)
    stats = get_stats()
    
    return render_template_string(HTML_TEMPLATE, key=key, result=result, stats=stats)


@app.route("/<short_code>")
def redirect_url(short_code: str):
    """Redirect short URL to long URL."""
    if short_code in ('favicon.ico', 'robots.txt'):
        return '', 404
    
    long_url = get_long_url(short_code)
    
    if long_url:
        return redirect(long_url, code=302)
    else:
        return render_template_string("""
            <!DOCTYPE html>
            <html>
            <head><title>Not Found</title>
            <style>
                body { font-family: sans-serif; background: #0a0a0a; color: #fff;
                       display: flex; align-items: center; justify-content: center;
                       min-height: 100vh; margin: 0; }
                h1 { font-size: 2rem; }
                a { color: #4ade80; }
            </style>
            </head>
            <body><div><h1>404 - Not Found</h1><p><a href="/">← bris.kr</a></p></div></body>
            </html>
        """), 404


# ============================================================================
# API ENDPOINTS
# ============================================================================

@app.route("/api/shorten", methods=["POST"])
@require_admin
def api_shorten():
    """API endpoint for creating short URLs."""
    data = request.get_json() or {}
    long_url = data.get('url')
    custom_code = data.get('code')
    
    if not long_url:
        return jsonify({"error": "URL is required"}), 400
    
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code)
    return jsonify(result)


@app.route("/api/stats")
@require_admin
def api_stats():
    """API endpoint for getting stats."""
    return jsonify(get_stats())


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


@app.route("/debug")
def debug():
    """Debug endpoint to check config."""
    key = request.args.get('key', '')
    return jsonify({
        "admin_key_set": bool(ADMIN_KEY),
        "admin_key_length": len(ADMIN_KEY) if ADMIN_KEY else 0,
        "admin_key_first5": ADMIN_KEY[:5] if ADMIN_KEY else None,
        "received_key_first5": key[:5] if key else None,
        "keys_match": key == ADMIN_KEY,
        "env_admin_key_first5": os.environ.get("ADMIN_KEY", "")[:5]
    })


if __name__ == "__main__":
    app.run(debug=True, port=8080)