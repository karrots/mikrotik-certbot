#!/usr/bin/env bash
# Certbot --deploy-hook wrapper for updating MikroTik certificate via this project.
# Place (or symlink) this script into /etc/letsencrypt/renewal-hooks/deploy/
# or call it via: certbot renew --deploy-hook /path/to/deploy-hook.sh
# Duplicate this script for each distinct router needing certificate updates.

set -euo pipefail

# --- Configuration (override via environment or by editing) ---
: "${MIKROTIK_DOMAIN:=your.domain.com}"          # Must match the renewed domain
: "${ROUTER_HOST:=192.168.88.1:443}"             # host:port of RouterOS REST
: "${ROUTER_USER:=api-user}"
: "${ROUTER_PASS:=your-password}"                # Consider sourcing from a secure file
#: "${CERT_NAME:=letsencrypt-cert}"               # Name will be generated based on certificate CN automatically. Optional override.
: "${HOTSPOT_PROFILE_NAMES:=}"                   # New: comma/space/semicolon separated list
: "${VERIFY_SSL:=false}"                         # Set true if router has trusted cert
: "${UPDATE_WWW_SSL:=true}"                      # Apply cert to www-ssl service
: "${UPDATE_API_SSL:=true}"                      # Apply cert to api-ssl service
#: "${LE_BASE_PATH:=/etc/letsencrypt/live}"       # Base path to LE dirs. Change if non-standard

# Determine script directory (follow symlinks) for optional local-dev mode.
SCRIPT_PATH="$(readlink -f -- "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(dirname -- "$SCRIPT_PATH")"

# Optional override for running a local clone instead of PyPI/git fetch.
: "${PROJECT_ROOT:=}"

# PyPI or git spec usable by uvx. Examples:
#   mikrotik-certbot                 (latest from PyPI)
#   mikrotik-certbot==0.1.0          (pinned PyPI)
#   git+https://github.com/karrots/mikrotik-certbot@tag
: "${MIKROTIK_CERTBOT_SPEC:=mikrotik-certbot}"

# Force a fresh resolution each run (set UVX_REFRESH=1) -> adds --refresh
UVX_REFRESH_FLAG=""
if [ "${UVX_REFRESH:-0}" = "1" ] || [ "${UVX_REFRESH:-}" = "true" ]; then
  UVX_REFRESH_FLAG="--refresh"
fi

# Console script entry defined in pyproject.toml
TOOL_ENTRY="mikrotik-certbot"

# Check that uv (and uvx path) is installed early
if ! command -v uv >/dev/null 2>&1; then
  echo "ERROR: 'uv' not found in PATH. Install from https://github.com/astral-sh/uv" >&2
  exit 1
fi

# Certbot provides RENEWED_DOMAINS, which the Python script uses for gating logic.
# Export variables so they are visible to whichever execution path we take.
export MIKROTIK_DOMAIN ROUTER_HOST ROUTER_USER ROUTER_PASS CERT_NAME HOTSPOT_PROFILE_NAMES \
  VERIFY_SSL UPDATE_WWW_SSL UPDATE_API_SSL LE_BASE_PATH

EXECUTION_METHOD=""

if [ -n "$PROJECT_ROOT" ] && [ -f "$PROJECT_ROOT/pyproject.toml" ]; then
  echo "INFO: Using local project root: $PROJECT_ROOT"
  ( cd "$PROJECT_ROOT" && uv run "$TOOL_ENTRY" )
  EXECUTION_METHOD="local-project"
elif [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
  echo "INFO: Using script directory project: $SCRIPT_DIR"
  ( cd "$SCRIPT_DIR" && uv run "$TOOL_ENTRY" )
  EXECUTION_METHOD="script-dir"
else
  # Remote/spec execution via uvx (PyPI / git). We supply a --from spec to allow pinning.
  # If MIKROTIK_CERTBOT_SPEC is just the name, uvx duplicates default behavior but remains explicit.
  if command -v uvx >/dev/null 2>&1; then
    echo "INFO: Executing via uvx spec '$MIKROTIK_CERTBOT_SPEC' ($UVX_REFRESH_FLAG)"
    uvx $UVX_REFRESH_FLAG --from "$MIKROTIK_CERTBOT_SPEC" "$TOOL_ENTRY"
  else
    echo "INFO: 'uvx' shim not found; falling back to 'uv tool run' (cannot use --from)."
    echo "INFO: Consider installing 'uvx' (usually part of uv install)."
    uv tool run "$TOOL_ENTRY"
  fi
  EXECUTION_METHOD="uvx-spec"
fi

echo "INFO: Execution pathway used: $EXECUTION_METHOD (spec=$MIKROTIK_CERTBOT_SPEC)"
