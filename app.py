"""
bris.kr - Minimal URL Shortener
Uses kumori-404602 PostgreSQL database for storage
Schema: briskr.urls
"""
import os
import string
import random

from flask import Flask, request, redirect, jsonify, render_template_string, url_for, g
from werkzeug.middleware.proxy_fix import ProxyFix
from google.cloud import secretmanager
import psycopg
from psycopg.rows import dict_row

app = Flask(__name__)

# Trust proxy headers (App Engine has 2 proxies in front)
# This makes request.remote_addr return the real client IP
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)

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
# IP ADDRESS HELPER
# ============================================================================

def get_client_ip() -> str:
    """Get the real client IP address.
    
    With ProxyFix middleware, request.remote_addr should be correct.
    Falls back to X-Forwarded-For header parsing if needed.
    """
    # ProxyFix should handle this, but let's be safe
    if request.remote_addr and request.remote_addr != '127.0.0.1':
        return request.remote_addr
    
    # Fallback: manually parse X-Forwarded-For
    x_forwarded_for = request.headers.get('X-Forwarded-For')
    if x_forwarded_for:
        # First IP in the comma-separated list is the original client
        ip = x_forwarded_for.split(',')[0].strip()
        return ip
    
    return request.remote_addr or 'unknown'


# Log IP on every request
@app.before_request
def log_request_info():
    """Log client IP for every request."""
    client_ip = get_client_ip()
    g.client_ip = client_ip  # Store in flask g object for use in templates
    print(f"📍 Request from IP: {client_ip} | Path: {request.path}")


# ============================================================================
# URL SHORTENING LOGIC
# ============================================================================

def generate_short_code(length: int = 2) -> str:
    """Generate a random short code."""
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=length))


def find_available_code() -> str:
    """Find an available short code, starting with shortest possible."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            for length in range(MIN_CODE_LENGTH, MAX_CODE_LENGTH + 1):
                for _ in range(10):
                    code = generate_short_code(length)
                    cur.execute(
                        "SELECT 1 FROM briskr.urls WHERE short_code = %s",
                        (code,)
                    )
                    if not cur.fetchone():
                        return code
            return generate_short_code(MAX_CODE_LENGTH)
    finally:
        conn.close()


def create_short_url(long_url: str, custom_code: str = None, client_ip: str = None) -> dict:
    """Create a new short URL."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if custom_code:
                cur.execute(
                    "SELECT short_code FROM briskr.urls WHERE short_code = %s",
                    (custom_code.lower(),)
                )
                if cur.fetchone():
                    return {"error": f"Code '{custom_code}' already exists"}
                short_code = custom_code.lower()
            else:
                short_code = find_available_code()
            
            cur.execute("""
                INSERT INTO briskr.urls (short_code, long_url, created_by_ip)
                VALUES (%s, %s, %s)
                RETURNING id, short_code, long_url, created_at
            """, (short_code, long_url, client_ip))
            
            result = cur.fetchone()
            conn.commit()
            
            print(f"✅ Created short URL: {short_code} -> {long_url[:50]}... (IP: {client_ip})")
            
            return {
                "short_url": f"{BASE_URL}/{result['short_code']}",
                "short_code": result['short_code'],
                "long_url": result['long_url'],
                "created_at": str(result['created_at'])
            }
    finally:
        conn.close()


def get_url_by_code(short_code: str) -> dict | None:
    """Get URL info by short code."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT short_code, long_url, click_count, created_at
                FROM briskr.urls WHERE short_code = %s
            """, (short_code.lower(),))
            return cur.fetchone()
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


def get_stats_by_ip(client_ip: str) -> list:
    """Get URLs created by a specific IP address."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT short_code, long_url, click_count, created_at, last_clicked
                FROM briskr.urls
                WHERE created_by_ip = %s
                ORDER BY created_at DESC
                LIMIT 100
            """, (client_ip,))
            return cur.fetchall()
    finally:
        conn.close()


def get_url_count_by_ip(client_ip: str) -> int:
    """Get count of URLs created by a specific IP."""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) as count FROM briskr.urls WHERE created_by_ip = %s",
                (client_ip,)
            )
            result = cur.fetchone()
            return result['count'] if result else 0
    finally:
        conn.close()


def get_total_urls() -> int:
    """Get total number of URLs in system."""
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
        h1 { font-size: 3rem; margin-bottom: 0.5rem; }
        h1 span { color: #666; }
        .tagline { color: #4ade80; font-size: 0.9rem; margin-bottom: 2rem; font-family: monospace; }
        .tagline span { color: #888; }
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
        .total { color: #555; font-size: 0.75rem; }
    </style>
</head>
<body>
    <div class="container">
        <h1>bris<span>.kr</span></h1>
        <p class="tagline">Making links brisker for: <span>{{ client_ip }}</span>!</p>
        
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
            <h2>Your URLs ({{ your_url_count }})</h2>
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
            <p class="total">{{ total_urls }} URLs shortened globally</p>
        </div>
        {% endif %}
        
        <p class="info">Free URL shortener. No tracking, no ads.</p>
    </div>
</body>
</html>
"""


@app.route("/")
def home():
    """Home page - show form and user's URLs."""
    result = None
    error = request.args.get('error')
    created = request.args.get('created')
    client_ip = g.client_ip
    
    # Show result if we just created a URL (via redirect)
    if created:
        url_info = get_url_by_code(created)
        if url_info:
            result = {
                "short_url": f"{BASE_URL}/{url_info['short_code']}",
                "short_code": url_info['short_code'],
                "long_url": url_info['long_url']
            }
    
    # Show error if redirect included one
    if error:
        result = {"error": error}
    
    try:
        # Only show URLs created by this visitor's IP
        stats = get_stats_by_ip(client_ip)
        your_url_count = get_url_count_by_ip(client_ip)
        total_urls = get_total_urls()
    except Exception as e:
        print(f"Error getting stats: {e}")
        stats = []
        your_url_count = 0
        total_urls = 0
    
    return render_template_string(HTML_TEMPLATE, 
                                  result=result, 
                                  stats=stats, 
                                  your_url_count=your_url_count,
                                  total_urls=total_urls,
                                  client_ip=client_ip)


@app.route("/shorten", methods=["POST"])
def shorten():
    """Create new short URL and redirect (PRG pattern)."""
    long_url = request.form.get('url', '').strip()
    custom_code = request.form.get('code', '').strip() or None
    client_ip = g.client_ip
    
    if not long_url:
        return redirect(url_for('home', error='URL is required'))
    
    # Ensure URL has protocol
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code, client_ip)
    
    if 'error' in result:
        return redirect(url_for('home', error=result['error']))
    
    # Redirect to home with created code (PRG pattern - no form resubmission)
    return redirect(url_for('home', created=result['short_code']))


@app.route("/<short_code>")
def redirect_url(short_code: str):
    """Redirect short URL to long URL."""
    if short_code in ('favicon.ico', 'robots.txt', 'health', 'api'):
        return '', 404
    
    long_url = get_long_url(short_code)
    
    if long_url:
        print(f"🔗 Redirect: /{short_code} -> {long_url[:50]}...")
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
    client_ip = g.client_ip
    
    if not long_url:
        return jsonify({"error": "URL is required"}), 400
    
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code, client_ip)
    return jsonify(result)


@app.route("/api/stats")
def api_stats():
    """API endpoint for getting stats (your URLs only)."""
    client_ip = g.client_ip
    return jsonify({
        "your_urls": get_url_count_by_ip(client_ip),
        "total_urls": get_total_urls(),
        "urls": get_stats_by_ip(client_ip)
    })


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "your_ip": g.client_ip}), 200


if __name__ == "__main__":
    app.run(debug=True, port=8080)