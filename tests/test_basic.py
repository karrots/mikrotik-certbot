import pytest

from mikrotik_certbot.config import ConfigurationError, load_settings, parse_hotspot_profiles
from mikrotik_certbot.workflow import determine_certificate_name


def test_parse_profiles_whitespace():
    assert parse_hotspot_profiles("alpha beta") == ["alpha", "beta"]


def test_parse_profiles_with_quoted_names():
    assert parse_hotspot_profiles('"Guest Portal" "Staff Portal"') == ["Guest Portal", "Staff Portal"]


def test_load_settings_requires_lineage():
    with pytest.raises(ConfigurationError):
        load_settings({})


def test_determine_certificate_name_uses_override_suffix(tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "CERT_NAME": "custom_202501",
    }
    settings = load_settings(env)
    name = determine_certificate_name(settings)
    # legacy _YYYYMM should be normalized to include full timestamp (ends with 'T' and 4 digits)
    assert name.startswith("custom_")
    assert "T" in name and len(name.split("T")[-1]) >= 4


def test_determine_certificate_name_preserves_versioned_override(tmp_path):
    lineage = tmp_path
    (lineage / "privkey.pem").write_text("dummy", encoding="utf-8")
    (lineage / "fullchain.pem").write_text("dummy", encoding="utf-8")

    env = {
        "RENEWED_LINEAGE": str(lineage),
        "RENEWED_DOMAINS": "example.com",
        "CERT_NAME": "custom_20251007T1200",
    }
    settings = load_settings(env)
    assert determine_certificate_name(settings) == "custom_20251007T1200"
