"""bris.kr smoke test. Runs the real app against the real table: `venv_briskr/bin/python smoke_test.py`.

It creates one link (code smoke-<random>, to example.com) as a signed-in creator, follows it,
disables it, and removes that one row at the end. Nothing else in the table is written, except
that following the test link counts its own click.
"""
import secrets
import sys

import app as briskr
from utilities.kumori_db import db_cursor

client = briskr.app.test_client()
failures = []
TEST_EMAIL = 'andy.tillo@gmail.com'
CODE = 'smoke-' + secrets.token_hex(4)


def check(name, ok):
    print(('  ok    ' if ok else '  FAIL  ') + name)
    if not ok:
        failures.append(name)


queries = []
_real_cursor = briskr.db_cursor


def counting_cursor(*a, **kw):
    queries.append(1)
    return _real_cursor(*a, **kw)


def db_queries(path):
    """Database cursors opened while serving one GET."""
    queries.clear()
    briskr.db_cursor = counting_cursor
    try:
        return client.get(path), len(queries)
    finally:
        briskr.db_cursor = _real_cursor


def row(code):
    with db_cursor() as cur:
        cur.execute("SELECT long_url, click_count, disabled_at, created_by FROM briskr.urls WHERE short_code = %s", (code,))
        return cur.fetchone()


def sign_in(email):
    with client.session_transaction() as s:
        s['user'] = {'email': email}


print('signed out')
home = client.get('/')
check('home renders', home.status_code == 200 and b'bris.kr' in home.data)
check('home offers sign-in and no create form', b'/login' in home.data and b'action="/shorten"' not in home.data)
r = client.post('/shorten', data={'url': 'https://example.com/anon', 'code': CODE})
check('anonymous form post creates nothing', r.status_code == 302 and 'Sign+in' in r.headers['Location'] and row(CODE) is None)
r = client.post('/api/shorten', json={'url': 'https://example.com/anon', 'code': CODE})
check('anonymous API post is 401 and creates nothing', r.status_code == 401 and row(CODE) is None)

print('scanner paths never reach the database')
for path in ('/.env', '/xmlrpc.php', '/wp-login.php', "/test'", '/' + 'a' * 21):
    r, n = db_queries(path)
    check(f'{path[:24]} is 404 with 0 queries', r.status_code == 404 and n == 0)
r, n = db_queries('/no-such-code-zz')
check('a well-formed unknown code is 404 with 1 query', r.status_code == 404 and n == 1)

print('disabled links')
with db_cursor() as cur:
    cur.execute("SELECT short_code, click_count FROM briskr.urls WHERE disabled_at IS NOT NULL ORDER BY click_count DESC LIMIT 1")
    disabled = cur.fetchone()
check('there is a disabled link to test against', disabled is not None)
if disabled:
    r = client.get('/' + disabled['short_code'])
    check('a disabled link is 404 and its click count does not move',
          r.status_code == 404 and row(disabled['short_code'])['click_count'] == disabled['click_count'])

print('signed in, not on the creator list')
sign_in('someone-else@example.com')
r = client.post('/shorten', data={'url': 'https://example.com/other', 'code': CODE})
check('a signed-in stranger creates nothing', r.status_code == 302 and row(CODE) is None)

print('signed in as a creator')
briskr.CREATOR_EMAILS = frozenset({TEST_EMAIL})       # the secret may not be readable where this runs
sign_in(TEST_EMAIL)
home = client.get('/')
check('home shows the create form', b'action="/shorten"' in home.data)
for bad, why in (('https://tinu.be/abc', 'another shortener'), ('https://www.bit.ly/x', 'a shortener subdomain'),
                 ('https://bris.kr/aa', 'bris.kr itself'), ('javascript:alert(1)', 'not http'), ('https://nodots', 'no real host')):
    r = client.post('/api/shorten', json={'url': bad, 'code': CODE})
    check(f'refuses {why}', r.status_code == 400 and row(CODE) is None)
r = client.post('/api/shorten', json={'url': 'https://example.com/x', 'code': 'has.dot'})
check('refuses a code with a character the form does not allow', r.status_code == 400 and row('has.dot') is None)

try:
    r = client.post('/shorten', data={'url': 'https://example.com/briskr-smoke', 'code': CODE})
    made = row(CODE)
    check('creates a link and records who made it',
          r.status_code == 302 and made is not None and made['long_url'] == 'https://example.com/briskr-smoke'
          and made['created_by'] == TEST_EMAIL)
    r, n = db_queries('/' + CODE)
    check('the link redirects with 1 query and counts the click',
          r.status_code == 302 and r.headers['Location'] == 'https://example.com/briskr-smoke' and n == 1
          and row(CODE)['click_count'] == 1)
    r = client.post('/api/shorten', json={'url': 'https://example.com/again', 'code': CODE})
    check('a taken code is refused', r.status_code == 400)
    with db_cursor(commit=True) as cur:
        cur.execute("UPDATE briskr.urls SET disabled_at = now(), disabled_reason = 'smoke test' WHERE short_code = %s", (CODE,))
    check('once disabled it stops redirecting', client.get('/' + CODE).status_code == 404)
finally:
    with db_cursor(commit=True) as cur:
        cur.execute("DELETE FROM briskr.urls WHERE short_code = %s AND created_by = %s AND long_url LIKE 'https://example.com/%%'",
                    (CODE, TEST_EMAIL))
check('the test link is gone', row(CODE) is None)

client.get('/logout')
check('sign out removes the form', b'action="/shorten"' not in client.get('/').data)
check('health answers', client.get('/health').status_code == 200)

print(f"\n{'FAILED: ' + str(len(failures)) if failures else 'all passed'}")
sys.exit(1 if failures else 0)
