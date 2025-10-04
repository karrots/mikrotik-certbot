from __future__ import annotations

import os
import re
import shlex
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "ConfigurationError",
    "Settings",
    "env_bool",
    "load_settings",
    "parse_hotspot_profiles",
]


_TRUE_VALUES = {"1", "true", "yes", "on"}


class ConfigurationError(RuntimeError):
    """Raised when required configuration cannot be derived from the environment."""


@dataclass(frozen=True, slots=True)
class Settings:
    """Resolved configuration used throughout the certificate workflow."""

    mikrotik_domain: str
    router_host: str
    router_user: str
    router_pass: str
    verify_ssl: bool
    renewed_lineage: Path
    key_path: Path
    fullchain_path: Path
    update_www_ssl: bool
    update_api_ssl: bool
    debug: bool
    dry_run: bool
    force_reimport: bool
    hotspot_profiles: tuple[str, ...]
    full_http_debug: bool
    http_debug_body_limit: int
    cert_name_override: str | None
    keep_uploaded_file: bool
    overwrite_files: bool
    # If True, automatically accept unknown SSH host keys for SFTP uploads.
    # Default True for typical single-device automation; can be turned off for stricter security.
    sftp_auto_accept_host_key: bool
    renewed_domains: tuple[str, ...]

    @property
    def base_url(self) -> str:
        return f"https://{self.router_host}/rest"

    @property
    def auth(self) -> tuple[str, str]:
        return self.router_user, self.router_pass


def env_bool(name: str, default: bool, env: Mapping[str, str]) -> bool:
    """Interpret an environment value as a boolean flag."""

    raw = env.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in _TRUE_VALUES


def parse_hotspot_profiles(raw: str | None) -> list[str]:
    """Normalise the HOTSPOT_PROFILE_NAMES environment variable."""

    if not raw:
        return []

    value = raw.strip()
    if not value:
        return []

    if "," in value or ";" in value:
        parts = re.split(r"[;,]+", value)
    else:
        try:
            parts = shlex.split(value)
        except ValueError:
            parts = value.split()

    seen: set[str] = set()
    cleaned: list[str] = []
    for part in parts:
        token = part.strip()
        if not token:
            continue
        if (token.startswith("\"") and token.endswith("\"")) or (
            token.startswith("'") and token.endswith("'")
        ):
            token = token[1:-1]
        if token and token not in seen:
            seen.add(token)
            cleaned.append(token)
    return cleaned


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    """Resolve configuration from the given environment mapping."""

    env: MutableMapping[str, str] = dict(os.environ if environ is None else environ)

    lineage_raw = env.get("RENEWED_LINEAGE", "").rstrip("/")
    if not lineage_raw:
        raise ConfigurationError(
            "RENEWED_LINEAGE environment variable is required for the deploy hook workflow.")

    lineage_path = Path(lineage_raw)
    if not lineage_path.is_dir():
        raise ConfigurationError(
            f"RENEWED_LINEAGE '{lineage_path}' does not exist or is not a directory.")

    key_path = lineage_path / "privkey.pem"
    fullchain_path = lineage_path / "fullchain.pem"
    missing: list[str] = [str(p) for p in (key_path, fullchain_path) if not p.is_file()]
    if missing:
        raise ConfigurationError(
            "Missing expected certificate material: " + ", ".join(missing)
        )

    hotspot_raw = env.get("HOTSPOT_PROFILE_NAMES")
    hotspot_profiles = tuple(parse_hotspot_profiles(hotspot_raw))

    renewed_domains = tuple((env.get("RENEWED_DOMAINS") or "").split())

    def _int_setting(name: str, default: int) -> int:
        raw_val = env.get(name)
        if raw_val is None:
            return default
        try:
            return int(raw_val)
        except (TypeError, ValueError) as exc:  # pragma: no cover - defensive
            raise ConfigurationError(f"Environment variable {name} must be an integer.") from exc

    return Settings(
        mikrotik_domain=env.get("MIKROTIK_DOMAIN", "your.domain.com"),
        router_host=env.get("ROUTER_HOST", "192.168.88.1:443"),
        router_user=env.get("ROUTER_USER", "api-user"),
        router_pass=env.get("ROUTER_PASS", "your-password"),
        verify_ssl=env_bool("VERIFY_SSL", False, env),
        renewed_lineage=lineage_path,
        key_path=key_path,
        fullchain_path=fullchain_path,
        update_www_ssl=env_bool("UPDATE_WWW_SSL", True, env),
        update_api_ssl=env_bool("UPDATE_API_SSL", True, env),
        debug=env_bool("DEBUG", False, env),
        dry_run=env_bool("DRY_RUN", False, env),
        force_reimport=env_bool("FORCE_REIMPORT", False, env),
        hotspot_profiles=hotspot_profiles,
        full_http_debug=env_bool("FULL_HTTP_DEBUG", False, env),
        http_debug_body_limit=_int_setting("HTTP_DEBUG_BODY_LIMIT", 2000),
        cert_name_override=(env.get("CERT_NAME", "").strip() or None),
        keep_uploaded_file=env_bool("KEEP_UPLOADED_FILE", False, env),
        overwrite_files=env_bool("OVERWRITE", True, env),
        sftp_auto_accept_host_key=env_bool("SFTP_AUTO_ACCEPT_HOST_KEY", True, env),
        renewed_domains=renewed_domains,
    )
