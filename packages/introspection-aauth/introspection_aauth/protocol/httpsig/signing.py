"""Signing a request under the AAuth profile, and the `Signature-Key` values
that name its key."""

import base64
import hashlib
from urllib.parse import urlsplit

import http_sfv

from introspection_aauth.protocol.keys import SigningKey

LABEL = "sig"
REQUIRED = ("@method", "@authority", "@path", "signature-key")
MAX_CLOCK_SKEW_SECONDS = 60
#: Metadata documents a `jwks_uri` key may be named under (`#metadata-documents`).
KNOWN_DWKS = frozenset(
    {
        "aauth-agent.json",
        "aauth-person.json",
        "aauth-access.json",
        "aauth-resource.json",
    }
)


def _quoted(value: str) -> str:
    if '"' in value or "\\" in value or not value.isascii():
        raise ValueError("value cannot travel in Signature-Key")
    return f'"{value}"'


def jwt_key(token: str) -> str:
    """`Signature-Key` presenting a token whose `cnf.jwk` is the key."""
    return f"{LABEL}=jwt;jwt={_quoted(token)}"


def jwks_uri_key(server: str, dwk: str, kid: str) -> str:
    """`Signature-Key` naming a server's published key."""
    return (
        f"{LABEL}=jwks_uri;id={_quoted(server)};dwk={_quoted(dwk)};"
        f"kid={_quoted(kid)}"
    )


def _signature_key(signature_key: str) -> http_sfv.Item | None:
    parsed = http_sfv.Dictionary()
    try:
        parsed.parse(signature_key.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return None
    if len(parsed) != 1:
        return None
    item = next(iter(parsed.values()))
    return item if isinstance(item, http_sfv.Item) else None


def signature_scheme(signature_key: str) -> str | None:
    """The scheme a Signature-Key names, read before anything is fetched."""
    item = _signature_key(signature_key)
    return str(item.value) if item is not None else None


def named_server(signature_key: str) -> str | None:
    """The server a `jwks_uri` Signature-Key names, read before any key is
    fetched, so a verifier can refuse a server it does not take requests from."""
    item = _signature_key(signature_key)
    if item is None or str(item.value) != "jwks_uri":
        return None
    server = item.params.get("id")
    return server if isinstance(server, str) else None


def content_digest(body: bytes) -> str:
    """`sha-256=:…:`, the RFC 9530 `Content-Digest` of `body`."""
    return (
        f"sha-256=:{base64.b64encode(hashlib.sha256(body).digest()).decode()}:"
    )


def authority(url: str) -> str:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"{url} has no host")
    return f"{host}:{parts.port}" if parts.port else host


def sign(
    key: SigningKey,
    signature_key: str,
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    authorization: str | None = None,
    created: int,
) -> dict[str, str]:
    """The headers that sign a request to `url` with `key`, covering its
    `Authorization` when it carries one."""
    parts = urlsplit(url)
    covered = [
        ("@method", method.upper()),
        ("@authority", authority(url)),
        ("@path", parts.path or "/"),
    ]
    if parts.query:
        covered.append(("@query", f"?{parts.query}"))
    covered.append(("signature-key", signature_key))
    headers: dict[str, str] = {}
    if body:
        digest = content_digest(body)
        covered += [("content-digest", digest), ("content-type", content_type)]
        headers |= {"content-digest": digest, "content-type": content_type}
    if authorization is not None:
        covered.append(("authorization", authorization))
        headers["authorization"] = authorization
    params = (
        "("
        + " ".join(f'"{name}"' for name, _ in covered)
        + f");created={created}"
    )
    base = "\n".join(
        [f'"{name}": {value}' for name, value in covered]
        + [f'"@signature-params": {params}']
    )
    signature = base64.b64encode(key.sign(base.encode())).decode()
    return headers | {
        "signature-key": signature_key,
        "signature-input": f"{LABEL}={params}",
        "signature": f"{LABEL}=:{signature}:",
    }
