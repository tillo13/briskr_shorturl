"""
bris.kr - Minimal URL Shortener
Uses kumori-404602 PostgreSQL database for storage
Schema: briskr.urls
"""
import os
import string
import random

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

# Short code settings - start small, grow as needed
MIN_CODE_LENGTH = 2  # Start with 2 chars (a9, bX, etc.)
MAX_CODE_LENGTH = 6  # Max length if all shorter codes used

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

def generate_short_code(length: int = 2) -> str:
    """Generate a random short code."""
    # Use lowercase + digits for cleaner URLs
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


def find_available_code() -> str:
    """Find an available short code, starting with shortest possible."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for length in range(MIN_CODE_LENGTH, MAX_CODE_LENGTH + 1):
                # Try a few random codes at this length
                for _ in range(10):
                    code = generate_short_code(length)
                    cur.execute(
                        "SELECT 1 FROM briskr.urls WHERE short_code = %s",
                        (code,)
                    )
                    if not cur.fetchone():
                        return code
            
            # Fallback: generate longer code
            return generate_short_code(MAX_CODE_LENGTH)
    finally:
        conn.close()


def create_short_url(long_url: str, custom_code: str = None) -> dict:
    """Create a new short URL."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if custom_code:
                # Check if custom code exists
                cur.execute(
                    "SELECT short_code FROM briskr.urls WHERE short_code = %s",
                    (custom_code.lower(),)
                )
                if cur.fetchone():
                    return {"error": f"Code '{custom_code}' already exists"}
                short_code = custom_code.lower()
            else:
                short_code = find_available_code()
            
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
            """, (short_code.lower(),))
            
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


def get_total_urls() -> int:
    """Get total number of URLs."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) as count FROM briskr.urls")
            result = cur.fetchone()
            return result['count'] if result else 0
    finally:
        conn.close()


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
        .result a { color: #4ade80; word-break: break-all; font-size: 1.25rem; }
        .stats { margin-top: 3rem; }
        .stats h2 { margin-bottom: 1rem; font-size: 1.25rem; color: #888; }
        .stats table { width: 100%; border-collapse: collapse; }
        .stats th, .stats td { 
            padding: 0.75rem; text-align: left; 
            border-bottom: 1px solid #333;
        }
        .stats td { font-family: monospace; font-size: 0.875rem; }
        .stats a { color: #4ade80; }
        .clicks { color: #4ade80; }
        .error { color: #f87171; }
        .info { color: #666; font-size: 0.875rem; margin-top: 2rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>bris<span>.kr</span></h1>
        
        <form method="POST" action="/shorten">
            <input type="url" name="url" placeholder="Paste long URL here..." required>
            <input type="text" name="code" placeholder="Custom code (optional)" maxlength="20">
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
            <h2>Recent URLs ({{ total_urls }} total)</h2>
            <table>
                <tr><th>Code</th><th>Destination</th><th>Clicks</th></tr>
                {% for url in stats %}
                <tr>
                    <td><a href="/{{ url.short_code }}">{{ url.short_code }}</a></td>
                    <td>{{ url.long_url[:40] }}{% if url.long_url|length > 40 %}...{% endif %}</td>
                    <td class="clicks">{{ url.click_count }}</td>
                </tr>
                {% endfor %}
            </table>
        </div>
        {% endif %}
        
        <p class="info">Free URL shortener. No tracking, no ads.</p>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    """Home page - show form and recent URLs."""
    try:
        stats = get_stats()
        total_urls = get_total_urls()
    except Exception as e:
        print(f"Error getting stats: {e}")
        stats = []
        total_urls = 0
    return render_template_string(HTML_TEMPLATE, result=None, stats=stats, total_urls=total_urls)


@app.route("/shorten", methods=["POST"])
def shorten():
    """Create new short URL."""
    long_url = request.form.get('url', '').strip()
    custom_code = request.form.get('code', '').strip() or None
    
    if not long_url:
        return render_template_string(HTML_TEMPLATE, 
                                      result={"error": "URL is required"}, 
                                      stats=[], total_urls=0)
    
    # Ensure URL has protocol
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code)
    
    try:
        stats = get_stats()
        total_urls = get_total_urls()
    except:
        stats = []
        total_urls = 0
    
    return render_template_string(HTML_TEMPLATE, result=result, stats=stats, total_urls=total_urls)


@app.route("/<short_code>")
def redirect_url(short_code: str):
    """Redirect short URL to long URL."""
    if short_code in ('favicon.ico', 'robots.txt', 'health', 'api'):
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
def api_shorten():
    """API endpoint for creating short URLs."""
    data = request.get_json() or {}
    long_url = data.get('url', '').strip()
    custom_code = data.get('code', '').strip() or None
    
    if not long_url:
        return jsonify({"error": "URL is required"}), 400
    
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code)
    return jsonify(result)


@app.route("/api/stats")
def api_stats():
    """API endpoint for getting stats."""
    return jsonify({
        "total_urls": get_total_urls(),
        "recent": get_stats()
    })


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(debug=True, port=8080)