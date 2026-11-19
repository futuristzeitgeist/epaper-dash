"""
one-time helper: trade a google oauth_token cookie for a keep master token.

1. in a browser, go to https://accounts.google.com/EmbeddedSetup and sign in.
   (it may hang on a loading screen after sign-in. that's fine.)
2. open dev tools > application (chrome) or storage (firefox) > cookies
   > accounts.google.com, and copy the value of the cookie named "oauth_token".
   it starts with "oauth2_4/".
3. run:  pip install gpsoauth  then  python get_master_token.py
4. paste the printed token into a github secret called KEEP_MASTER_TOKEN.

the master token is basically a password for your google account.
don't commit it, don't paste it anywhere public.
"""

import getpass
import secrets

import gpsoauth

email = input("google email: ").strip()
oauth_token = getpass.getpass("oauth_token cookie (hidden): ").strip()
android_id = secrets.token_hex(8)

res = gpsoauth.exchange_token(email, oauth_token, android_id)
if "Token" not in res:
    raise SystemExit(f"didn't work: {res}")
print("\nmaster token:\n" + res["Token"])
