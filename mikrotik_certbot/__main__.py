from __future__ import annotations

import sys

import requests

from mikrotik_certbot import ConfigurationError, load_settings
from mikrotik_certbot.workflow import run


def main() -> None:
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        performed = run(settings)
    except ConfigurationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    except requests.exceptions.RequestException as exc:
        print(f"\nERROR: A network error occurred: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"\nERROR: An unexpected error occurred: {exc}", file=sys.stderr)
        sys.exit(1)

    if not performed:
        sys.exit(0)


if __name__ == "__main__":
    main()

