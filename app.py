"""
bris.kr - Minimal URL Shortener
PostgreSQL-backed URL shortener with no tracking
"""
import os
import re
import secrets
import string
import random

from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit
from flask import Flask, request, redirect, jsonify, render_template_string, session, url_for, g, Response
from werkzeug.middleware.proxy_fix import ProxyFix

# The connection is kumori's canonical pool, vendored on every deploy (deploy.json shared_files ->
# utilities/kumori_db.py); never edit that copy. Until 2026-10-11 every request opened its own
# connection, so a scanner's 235 probes in one minute became 67 logins on the shared database.
os.environ.setdefault('DB_ROLE', 'briskr_app')
os.environ.setdefault('DB_SECRET_PREFIX', 'BRISKR')
os.environ.setdefault('DB_POOL_MAX', '2')          # x max_instances 3 = 6 of briskr_app's 10
os.environ.setdefault('DB_DICT_ROWS', '1')
from utilities.kumori_db import db_cursor  # noqa: E402
from utilities.google_secrets_utils import get_secret  # noqa: E402

app = Flask(__name__)

# GA4 tag injection — registers `ga_snippet(slug)` for use in HTML_TEMPLATE
try:
    from utilities.gtag import snippet as _ga_snippet
    app.jinja_env.globals['ga_snippet'] = _ga_snippet
except Exception:
    pass

# Cross-app visitor logging → kumori_ops.visitor_log
try:
    from utilities.visitor_logging import install_middleware as _install_visitor_logging
    _install_visitor_logging(app, 'briskr')
except Exception as _vl_e:
    pass

# Trust proxy headers (App Engine has 2 proxies in front)
# This makes request.remote_addr return the real client IP
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=2, x_proto=1, x_host=1)

# ============================================================================
# CONFIGURATION
# ============================================================================

BASE_URL = os.environ.get("BASE_URL", "https://bris.kr")

# Creating a link needs a Google sign-in from this list; following one never does. The form was
# open to anyone until 2026-10-11: on 2026-10-05..08 four strangers made five links to
# previous.oriwada.xyz and tinu.be that drew 1,942 of the 3,538 clicks bris.kr had ever served.
# The list is a secret because this repository is public.
CREATOR_EMAILS = frozenset(e.strip().lower() for e in (get_secret('BRISKR_CREATOR_EMAILS') or '').split(',') if e.strip())
app.secret_key = get_secret('BRISKR_SECRET_KEY') or secrets.token_hex(32)   # no secret = sessions end at restart
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=os.environ.get('GAE_ENV', '').startswith('standard'),
                  SESSION_COOKIE_NAME='briskr_session', PERMANENT_SESSION_LIFETIME=timedelta(days=30))
from utilities.google_auth import GoogleAuth  # noqa: E402
gauth = GoogleAuth(app)

# A code is what the form lets you type: letters, digits, _ and -, at most 20. Anything else
# (/.env, /xmlrpc.php, /wp-login.php) is answered 404 without a database query.
CODE_SHAPE = re.compile(r'^[a-z0-9_-]{1,20}$')

# Other shorteners, as of 2026-10-11. A short link to a short link only hides where it goes.
SHORTENER_HOSTS = frozenset((
    'bris.kr', 'bit.ly', 'bitly.com', 'tinyurl.com', 't.co', 'goo.gl', 'is.gd', 'v.gd', 'ow.ly',
    'buff.ly', 'rebrand.ly', 'cutt.ly', 'shorturl.at', 'rb.gy', 't.ly', 'tiny.cc', 'tinu.be',
    's.id', 'lnkd.in', 'qr.ae', 'shorter.me', 'short.io', 'tiny.one', 'urlz.fr', 'x.gd', 'da.gd',
))

# Short code settings - start small, grow as needed
MIN_CODE_LENGTH = 2  # Start with 2 chars (a9, bX, etc.)
MAX_CODE_LENGTH = 6  # Max length if all shorter codes used

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


@app.before_request
def force_canonical_host():
    host = request.headers.get('Host', '')
    if host.startswith('www.'):
        return redirect(f'https://bris.kr{request.full_path}', code=301)

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


def find_available_code(cur) -> str:
    """Find an available short code, starting with shortest possible."""
    for length in range(MIN_CODE_LENGTH, MAX_CODE_LENGTH + 1):
        for _ in range(10):
            code = generate_short_code(length)
            cur.execute("SELECT 1 FROM briskr.urls WHERE short_code = %s", (code,))
            if not cur.fetchone():
                return code
    return generate_short_code(MAX_CODE_LENGTH)


def refuse_destination(long_url: str) -> str | None:
    """Why this URL may not be shortened, or None."""
    parts = urlsplit(long_url)
    host = (parts.hostname or '').lower()
    if parts.scheme not in ('http', 'https') or '.' not in host:
        return 'That is not a web address'
    if any(host == h or host.endswith('.' + h) for h in SHORTENER_HOSTS):
        return f'{host} is already a link shortener'
    return None


def create_short_url(long_url: str, custom_code: str = None, client_ip: str = None, created_by: str = None) -> dict:
    """Create a new short URL."""
    refused = refuse_destination(long_url)
    if refused:
        return {"error": refused}
    if custom_code and not CODE_SHAPE.match(custom_code.lower()):
        return {"error": "A code is letters, digits, _ and -, at most 20"}
    with db_cursor(commit=True) as cur:
        if custom_code:
            cur.execute("SELECT short_code FROM briskr.urls WHERE short_code = %s", (custom_code.lower(),))
            if cur.fetchone():
                return {"error": f"Code '{custom_code}' already exists"}
            short_code = custom_code.lower()
        else:
            short_code = find_available_code(cur)

        cur.execute("""
            INSERT INTO briskr.urls (short_code, long_url, created_by_ip, created_by)
            VALUES (%s, %s, %s, %s)
            RETURNING id, short_code, long_url, created_at
        """, (short_code, long_url, client_ip, created_by))
        result = cur.fetchone()

    print(f"✅ Created short URL: {short_code} -> {long_url[:50]}... (IP: {client_ip})")
    return {
        "short_url": f"{BASE_URL}/{result['short_code']}",
        "short_code": result['short_code'],
        "long_url": result['long_url'],
        "created_at": str(result['created_at'])
    }


def get_url_by_code(short_code: str) -> dict | None:
    """Get URL info by short code."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT short_code, long_url, click_count, created_at
            FROM briskr.urls WHERE short_code = %s
        """, (short_code.lower(),))
        return cur.fetchone()


def get_long_url(short_code: str) -> str | None:
    """Get long URL and increment click count. A disabled link (disabled_at set) is not served."""
    with db_cursor(commit=True) as cur:
        cur.execute("""
            UPDATE briskr.urls
            SET click_count = click_count + 1,
                last_clicked = CURRENT_TIMESTAMP
            WHERE short_code = %s AND disabled_at IS NULL
            RETURNING long_url
        """, (short_code.lower(),))
        result = cur.fetchone()
    return result['long_url'] if result else None


def get_stats_by_ip(client_ip: str) -> list:
    """Get URLs created by a specific IP address."""
    with db_cursor() as cur:
        cur.execute("""
            SELECT short_code, long_url, click_count, created_at, last_clicked
            FROM briskr.urls
            WHERE created_by_ip = %s AND disabled_at IS NULL
            ORDER BY created_at DESC
            LIMIT 100
        """, (client_ip,))
        return cur.fetchall()


def get_url_count_by_ip(client_ip: str) -> int:
    """Get count of URLs created by a specific IP."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM briskr.urls WHERE created_by_ip = %s AND disabled_at IS NULL",
                    (client_ip,))
        return cur.fetchone()['count']


def get_total_urls() -> int:
    """Get total number of URLs in system."""
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) as count FROM briskr.urls")
        return cur.fetchone()['count']


# ============================================================================
# ROUTES
# ============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <title>Briskr - Free URL Shortener | bris.kr</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="description" content="Shorten URLs instantly with Briskr. Free, fast link shortener with no tracking and no ads. Create short memorable links at bris.kr.">
    <link rel="canonical" href="https://bris.kr/">
    <meta property="og:title" content="Briskr - Free URL Shortener">
    <meta property="og:description" content="Shorten URLs instantly. Free, fast, no tracking, no ads.">
    <meta property="og:url" content="https://bris.kr/">
    <meta property="og:type" content="website">
    <meta property="og:image" content="https://bris.kr/static/og-card.svg">
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "WebApplication",
      "name": "Briskr",
      "url": "https://bris.kr",
      "description": "Free URL shortener with no tracking and no ads. Create short memorable links instantly.",
      "applicationCategory": "UtilityApplication",
      "operatingSystem": "All",
      "offers": {
        "@type": "Offer",
        "price": "0",
        "priceCurrency": "USD"
      }
    }
    </script>
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
        .cross-links { margin-top: 3rem; padding-top: 1.5rem; border-top: 1px solid #222; }
        .cross-links p { color: #555; font-size: 0.75rem; margin-bottom: 0.5rem; }
        .cross-links a { color: #555; font-size: 0.75rem; margin-right: 1rem; text-decoration: none; }
        .cross-links a:hover { color: #4ade80; }
    </style>
    {{ ga_snippet('briskr') | safe }}
</head>
<body>
    <div class="container">
        <h1>Briskr<span> URL Shortener</span></h1>
        <p class="tagline">Making links brisker for: <span>{{ client_ip }}</span>!</p>
        
        {% if can_create %}
        <form method="POST" action="/shorten">
            <input type="url" name="url" placeholder="Paste long URL here..." required>
            <input type="text" name="code" placeholder="Custom code (optional)" maxlength="20" pattern="[A-Za-z0-9_-]+">
            <button type="submit">Shorten</button>
        </form>
        <p class="total">{{ signed_in }} · <a href="/logout">sign out</a></p>
        {% elif signed_in %}
        <p class="tagline">{{ signed_in }} can't create links here. <a href="/logout">Sign out</a></p>
        {% else %}
        <p class="tagline"><a href="/login">Sign in with Google</a> to create a link.</p>
        {% endif %}
        
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

        <footer class="cross-links">
            <p>More from our network:</p>
            <a href="https://noqout.com">NoQout</a>
            <a href="https://pilgri.ms">Pilgri.ms</a>
            <a href="https://kindness.social">Kindness.social</a>
            <a href="https://crab.travel">Crab.travel</a>
            <a href="https://scatterbrain.us">Scatterbrain</a>
            <a href="https://digitalempiretv.com">DigitalEmpireTV</a>
        </footer>
    </div>
</body>
</html>
"""


@app.route("/sitemap.xml")
def sitemap():
    host = request.host_url.rstrip('/')
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    # Only list real public pages — just the homepage for a URL shortener
    xml = f'''<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{host}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>'''
    return Response(xml, mimetype='application/xml')

@app.route("/robots.txt")
def robots():
    from utilities.visitor_logging import append_bot_block
    host = request.host_url.rstrip('/')
    content = f'User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /shorten\nSitemap: {host}/sitemap.xml\n'
    return Response(append_bot_block(content), mimetype='text/plain')


@app.route("/b4c9ebbc8faa4d7b8b2b8104b6511fee.txt")
def indexnow_key():
    return Response('b4c9ebbc8faa4d7b8b2b8104b6511fee', mimetype='text/plain')


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
                                  can_create=bool(creator()), signed_in=signed_in_email(),
                                  result=result,
                                  stats=stats, 
                                  your_url_count=your_url_count,
                                  total_urls=total_urls,
                                  client_ip=client_ip)


def signed_in_email() -> str | None:
    return (session.get('user') or {}).get('email')


def creator() -> str | None:
    """The signed-in email when it may create links, else None."""
    email = signed_in_email()
    return email if email in CREATOR_EMAILS else None


@app.route("/login")
def login():
    return gauth.login()


@app.route("/auth/callback")
def auth_callback():
    email, error = gauth.handle_callback()
    return redirect(url_for('home', error=error) if error else url_for('home'))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for('home'))


@app.route("/shorten", methods=["POST"])
def shorten():
    """Create new short URL and redirect (PRG pattern)."""
    if not creator():
        return redirect(url_for('home', error='Sign in to create a link'))
    long_url = request.form.get('url', '').strip()
    custom_code = request.form.get('code', '').strip() or None
    client_ip = g.client_ip
    
    if not long_url:
        return redirect(url_for('home', error='URL is required'))
    
    # Ensure URL has protocol
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code, client_ip, creator())
    
    if 'error' in result:
        return redirect(url_for('home', error=result['error']))
    
    # Redirect to home with created code (PRG pattern - no form resubmission)
    return redirect(url_for('home', created=result['short_code']))


@app.route("/<short_code>")
def redirect_url(short_code: str):
    """Redirect short URL to long URL."""
    if short_code in ('favicon.ico', 'robots.txt', 'health', 'api'):
        return '', 404

    long_url = get_long_url(short_code) if CODE_SHAPE.match(short_code.lower()) else None
    
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
    if not creator():
        return jsonify({"error": "Sign in at https://bris.kr to create a link"}), 401
    data = request.get_json(silent=True) or {}
    long_url = data.get('url', '').strip()
    custom_code = data.get('code', '').strip() or None
    client_ip = g.client_ip
    
    if not long_url:
        return jsonify({"error": "URL is required"}), 400
    
    if not long_url.startswith(('http://', 'https://')):
        long_url = 'https://' + long_url
    
    result = create_short_url(long_url, custom_code, client_ip, creator())
    return jsonify(result), (400 if 'error' in result else 200)


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