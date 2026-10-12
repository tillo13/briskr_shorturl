"""Google sign-in for bris.kr. Same shape as cardstock's utilities/auth.py: the shared kumori OAuth
client, identity is the verified Google email, no account table. Only creating a link needs it;
following a link never does.
"""

import logging
import os

from authlib.integrations.flask_client import OAuth
from flask import redirect, session

from utilities.google_secrets_utils import get_secret

logger = logging.getLogger(__name__)

# Explicit so it matches the registered redirect URI exactly, regardless of proxy/scheme guessing.
REDIRECT_URI = os.environ.get('OAUTH_REDIRECT_URI', 'https://bris.kr/auth/callback')


class GoogleAuth:
    def __init__(self, app):
        self.oauth = OAuth(app)
        cid = get_secret('KUMORI_GOOGLE_CLIENT_ID')
        csec = get_secret('KUMORI_GOOGLE_CLIENT_SECRET')
        if not cid or not csec:
            logger.error('KUMORI_GOOGLE_CLIENT_ID/SECRET unavailable: Google login disabled')
            self.google = None
            return
        self.google = self.oauth.register(
            name='google', client_id=cid, client_secret=csec,
            server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
            client_kwargs={'scope': 'openid email'},
        )

    def login(self):
        if not self.google:
            return redirect('/?error=Sign-in+is+not+set+up+yet')
        return self.google.authorize_redirect(REDIRECT_URI, prompt='select_account')

    def handle_callback(self):
        """Returns (email, error). Only verified emails are accepted."""
        if not self.google:
            return None, 'Google login is not configured'
        try:
            token = self.google.authorize_access_token()
            info = (token or {}).get('userinfo') or {}
            email = (info.get('email') or '').lower()
            if not email:
                return None, 'No email in the Google response'
            if info.get('email_verified') is not True:
                return None, 'Google did not verify this email address'
            session.clear()
            session.permanent = True
            session['user'] = {'email': email}
            logger.info('login: %s', email)
            return email, None
        except Exception as e:
            logger.warning('callback failed: %s', e)
            return None, str(e)
