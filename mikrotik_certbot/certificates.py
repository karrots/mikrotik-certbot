from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.backends import default_backend

__all__ = [
    "build_certificate_name",
    "format_import_timestamp",
    "CombinedCertificate",
    "combine_certificate_material",
    "get_cert_year_month",
    "get_local_cert_serial",
]

@dataclass(frozen=True, slots=True)
class CombinedCertificate:
    pem: str
    key_length: int
    chain_length: int


def combine_certificate_material(key_path: Path, fullchain_path: Path) -> CombinedCertificate:
    """Return the concatenated private key and fullchain PEM contents with length metadata."""

    key_text = key_path.read_text(encoding="utf-8").rstrip()
    chain_text = fullchain_path.read_text(encoding="utf-8").rstrip()
    pem = f"{key_text}\n{chain_text}\n"
    return CombinedCertificate(pem=pem, key_length=len(key_text), chain_length=len(chain_text))


def _load_first_certificate_pem(fullchain_path: Path) -> bytes:
    begin = b"-----BEGIN CERTIFICATE-----"
    end = b"-----END CERTIFICATE-----"
    block: list[bytes] = []
    collecting = False
    for line in fullchain_path.read_bytes().splitlines(keepends=True):
        if begin in line:
            collecting = True
        if collecting:
            block.append(line)
        if end in line and collecting:
            break
    if not block:
        raise ValueError("No certificate block found in fullchain PEM")
    return b"".join(block)


def _load_first_certificate(fullchain_path: Path) -> x509.Certificate:
    pem_bytes = _load_first_certificate_pem(fullchain_path)
    return x509.load_pem_x509_certificate(pem_bytes, default_backend())


def get_local_cert_serial(fullchain_path: Path) -> str:
    """Return the uppercase hexadecimal serial number for the first certificate."""

    cert = _load_first_certificate(fullchain_path)
    return format(cert.serial_number, "X")


def get_cert_year_month(fullchain_path: Path) -> str:
    """Return the YYYYMM string using the certificate's not-before field."""

    try:
        cert = _load_first_certificate(fullchain_path)
        not_before = getattr(cert, "not_valid_before_utc", None)
        if not_before is None:  # pragma: no cover - compatibility with older cryptography
            not_before = cert.not_valid_before.replace(tzinfo=UTC)
    except Exception:  # noqa: BLE001
        now = datetime.now(UTC)
        return f"{now.year}{now.month:02d}"
    return f"{not_before.year}{not_before.month:02d}"



def format_import_timestamp(dt: datetime | None = None) -> str:
    """Return an import-time timestamp string in the canonical YYYYMMDDThhmm form (UTC).

    If dt is None the current UTC now() is used.
    """

    if dt is None:
        dt = datetime.now(UTC)
    dt = dt.astimezone(UTC)
    return f"{dt.year:04d}{dt.month:02d}{dt.day:02d}T{dt.hour:02d}{dt.minute:02d}"


def build_certificate_name(domain: str, fullchain_path: Path) -> str:
    """Generate the router certificate name using the domain and current import timestamp.

    The base is the domain with dots replaced by underscores. The timestamp is the import-time
    UTC value in YYYYMMDDThhmm format.
    """

    base = domain.replace(".", "_")
    return f"{base}_{format_import_timestamp()}"
