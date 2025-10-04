import re
from datetime import UTC, datetime

from mikrotik_certbot.certificates import (
    format_import_timestamp,
    get_local_cert_serial,
)
from mikrotik_certbot.config import load_settings
from mikrotik_certbot.workflow import determine_certificate_name


def test_determine_certificate_name_domain_based(tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "MIKROTIK_DOMAIN": "example.com",
    }
    settings = load_settings(env)
    name = determine_certificate_name(settings)
    assert re.match(r"^example_com_\d{8}T\d{4}$", name)


def test_determine_certificate_name_cert_name_preserves_versioned(tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "MIKROTIK_DOMAIN": "example.com",
        "CERT_NAME": "custom_20251007T1200",
    }
    settings = load_settings(env)
    assert determine_certificate_name(settings) == "custom_20251007T1200"


def test_determine_certificate_name_cert_name_normalises_legacy_yyyymm(tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "MIKROTIK_DOMAIN": "example.com",
        "CERT_NAME": "custom_202510",
    }
    settings = load_settings(env)
    name = determine_certificate_name(settings)
    assert name.startswith("custom_")
    assert "T" in name and re.search(r"_\d{8}T\d{4}$", name)


def test_format_import_timestamp_is_utc_and_no_seconds():
    dt = datetime(2025, 10, 7, 12, 0, 30, tzinfo=UTC)
    ts = format_import_timestamp(dt)
    assert ts == "20251007T1200"


def test_get_local_cert_serial_parsing(monkeypatch, tmp_path):
    # Monkeypatch the internal loader to avoid needing a real cert file
    class DummyCert:
        serial_number = 0xA1B2C3

    def fake_load(path):
        return DummyCert()

    import mikrotik_certbot.certificates as certmod

    monkeypatch.setattr(certmod, "_load_first_certificate", fake_load)
    (tmp_path / "fullchain.pem").write_text("ignore", encoding="utf-8")
    serial = get_local_cert_serial(tmp_path / "fullchain.pem")
    assert re.match(r"^[0-9A-F]+$", serial)
    assert serial == format(0xA1B2C3, "X")
