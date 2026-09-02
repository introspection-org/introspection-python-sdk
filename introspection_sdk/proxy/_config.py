"""Dependency-neutral proxy routing policy."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

EGRESS_URL_ENV = "INTROSPECTION_EGRESS_URL"
ENDPOINT_HOSTS_ENV = "INTROSPECTION_ENDPOINT_HOSTS"
RELAY_TARGET_ENV = "INTROSPECTION_RELAY_TARGET"


def _first(environment: Mapping[str, str], *names: str) -> str | None:
    for name in names:
        value = environment.get(name)
        if value:
            return value
    return None


def _host_set(value: str | None) -> frozenset[str]:
    return frozenset(
        host.strip().lower()
        for host in (value or "").split(",")
        if host.strip()
    )


def _no_proxy_entries(value: str | None) -> tuple[str, ...]:
    return tuple(
        entry.strip().lower()
        for entry in (value or "").split(",")
        if entry.strip()
    )


@dataclass(frozen=True)
class ProxyConfig:
    """Immutable routing configuration shared by both HTTP adapters."""

    egress_url: str | None = None
    endpoint_hosts: frozenset[str] = frozenset()
    forward_proxy_url: str | None = None
    no_proxy: tuple[str, ...] = ()
    relay_target: str | None = None

    def __post_init__(self) -> None:
        if self.endpoint_hosts and not self.egress_url:
            raise ValueError(f"{ENDPOINT_HOSTS_ENV} requires {EGRESS_URL_ENV}")
        if self.egress_url:
            parsed = urlsplit(self.egress_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path not in {"", "/"}
            ):
                raise ValueError(
                    f"{EGRESS_URL_ENV} must be an HTTP(S) origin without credentials or a path"
                )

    @classmethod
    def from_env(
        cls, environment: Mapping[str, str] | None = None
    ) -> ProxyConfig:
        """Read the proxy contract shared by the Rust and JavaScript SDKs."""

        values = os.environ if environment is None else environment
        return cls(
            egress_url=values.get(EGRESS_URL_ENV) or None,
            endpoint_hosts=_host_set(values.get(ENDPOINT_HOSTS_ENV)),
            forward_proxy_url=_first(
                values,
                "HTTPS_PROXY",
                "https_proxy",
                "HTTP_PROXY",
                "http_proxy",
            ),
            no_proxy=_no_proxy_entries(_first(values, "NO_PROXY", "no_proxy")),
            relay_target=(values.get(RELAY_TARGET_ENV) or "").strip() or None,
        )

    def uses_egress(self, host: str) -> bool:
        return host.lower() in self.endpoint_hosts

    def bypasses_forward_proxy(
        self, host: str, port: int | None = None
    ) -> bool:
        host = host.lower().strip("[]")
        authority = f"{host}:{port}" if port is not None else host
        for raw_entry in self.no_proxy:
            entry = raw_entry.lstrip(".")
            if entry == "*" or raw_entry == authority:
                return True
            entry_host = (
                entry.rsplit(":", 1)[0] if entry.count(":") == 1 else entry
            )
            if host == entry_host or host.endswith(f".{entry_host}"):
                return True
        return False


__all__ = ["ProxyConfig"]
