"""Authentication reference: exchange a hosted-login authorization code.

Backs the "Hosted browser login" block of the docs' Authentication page
(region ``reference/authentication/hosted-login``). An ``spa`` Application
signs the user in with authorization code + PKCE; after the redirect, your
backend exchanges the code, redirect URI and PKCE verifier for a token.

The code is single-use and comes from a live browser redirect, so take the
three values from that redirect and export them before running. Without
them the module does the headless half: it generates a PKCE verifier and
its S256 challenge (RFC 7636) for the authorize call, prints them, and
exits 0, which is what the examples workflow runs.

Run with:
    INTROSPECTION_SPA_CLIENT_ID=intro_app_xxx
    INTROSPECTION_SPA_CODE=...            # `code` query param of the redirect
    INTROSPECTION_SPA_REDIRECT_URI=...    # exactly as sent to /authorize
    INTROSPECTION_SPA_CODE_VERIFIER=...   # the PKCE verifier you generated

        uv run -m introspection_examples.reference.auth_hosted_login

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import base64
import hashlib
import os
import secrets

from dotenv import load_dotenv

load_dotenv()
_missing = [
    name
    for name in (
        "INTROSPECTION_SPA_CLIENT_ID",
        "INTROSPECTION_SPA_CODE",
        "INTROSPECTION_SPA_REDIRECT_URI",
        "INTROSPECTION_SPA_CODE_VERIFIER",
    )
    if not os.getenv(name)
]
if _missing:
    # No redirect to exchange: generate the PKCE pair the authorize call
    # needs instead. Send the challenge with code_challenge_method=S256 and
    # keep the verifier for the exchange below.
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    print(f"code_verifier={verifier}")
    print(f"code_challenge={challenge}")
    print(
        f"skipping the exchange: set {', '.join(_missing)} from a hosted-login "
        "redirect (export the verifier above as INTROSPECTION_SPA_CODE_VERIFIER)"
    )
    raise SystemExit(0)
code = os.environ["INTROSPECTION_SPA_CODE"]
redirect_uri = os.environ["INTROSPECTION_SPA_REDIRECT_URI"]
code_verifier = os.environ["INTROSPECTION_SPA_CODE_VERIFIER"]

# #region docs:reference/authentication/hosted-login
import os

from introspection_sdk import authorization_code_token

# In your backend, after the hosted-login redirect.
token = authorization_code_token(
    code=code,  # from the redirect URI
    client_id=os.environ["INTROSPECTION_SPA_CLIENT_ID"],  # public, no secret
    redirect_uri=redirect_uri,  # must match the authorize call
    code_verifier=code_verifier,  # pairs with the PKCE challenge
)
# #endregion docs:reference/authentication/hosted-login


def main() -> None:
    print(f"token_type={token.token_type}, expires_in={token.expires_in}")


if __name__ == "__main__":
    main()
