"""The https URLs AAuth names: server identifiers, endpoints and origins."""

from urllib.parse import urlsplit


def https_origin(value: str) -> bool:
    """A server identifier: `https://host`, with no path, query or fragment."""
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not parts.path.strip("/")
        and not parts.query
        and not parts.fragment
    )


def https_endpoint(value: str) -> bool:
    """An endpoint URL: https, with a host and no query or fragment."""
    parts = urlsplit(value)
    return (
        parts.scheme == "https"
        and bool(parts.hostname)
        and not parts.query
        and not parts.fragment
    )


def _origin(url: str) -> str | None:
    """The https origin `url` is on, or None for any other URL or one
    carrying credentials."""
    parts = urlsplit(url)
    if (
        parts.scheme != "https"
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        return None
    return f"https://{parts.netloc.lower()}"


def same_origin(url: str, origin: str) -> bool:
    """Whether `url` is an https URL on `origin`, with no credentials in it."""
    found = _origin(url)
    return found is not None and found == _origin(origin)
