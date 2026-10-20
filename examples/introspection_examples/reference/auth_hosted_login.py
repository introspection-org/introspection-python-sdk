"""Authentication reference: exchange a hosted-login authorization code.

Backs the "Hosted browser login" block of the docs' Authentication page
(region ``reference/authentication/hosted-login``). An ``spa`` Application
signs the user in with authorization code + PKCE; after the redirect, your
backend exchanges the code, redirect URI and PKCE verifier for a token.

The code is single-use and comes from a live browser redirect, so take the
three values from that redirect and export them before running.

Run with:
    INTROSPECTION_SPA_CLIENT_ID=intro_app_xxx
    INTROSPECTION_SPA_CODE=...            # `code` query param of the redirect
    INTROSPECTION_SPA_REDIRECT_URI=...    # exactly as sent to /authorize
    INTROSPECTION_SPA_CODE_VERIFIER=...   # the PKCE verifier you generated

        uv run -m introspection_examples.reference.auth_hosted_login

Optional env:
    INTROSPECTION_BASE_API_URL  - CP REST API host (default https://api.introspection.dev)
"""

import os

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
    raise SystemExit(
        f"missing required env var(s): {', '.join(_missing)} -- sign in "
        "through hosted login with an spa Application and export the "
        "redirect's code, the redirect URI and your PKCE verifier"
    )
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
