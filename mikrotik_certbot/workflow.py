from __future__ import annotations

import re

from .certificates import (
    build_certificate_name,
    format_import_timestamp,
    get_local_cert_serial,
)
from .config import Settings
from .routeros import (
    RouterOSClient,
    confirm_certificate_present,
    confirm_file_exists,
    delete_uploaded_file,
    detect_routeros_version,
    extract_remote_serial,
    find_certificate_by_serial,
    find_existing_certificate,
    import_new_certificate,
    prune_old_certificates,
    remove_old_certificate,
    update_hotspot_profile,
    update_ip_service,
    upload_certificate,
)

__all__ = ["run", "determine_certificate_name"]


def _cert_name_has_version_suffix(name: str) -> bool:
    # Matches _YYYYMMDDThhmm optionally followed by _SEQ or other suffix
    return bool(re.search(r"_\d{8}T\d{4}(?:_.*)?$", name))


def _replace_legacy_yyyymm(name: str, timestamp: str) -> str:
    # Replace a trailing _YYYYMM with canonical timestamp
    return re.sub(r"_(\d{6})$", f"_{timestamp}", name)


def determine_certificate_name(settings: Settings) -> str:
    """Resolve the target RouterOS certificate name following PRD: versioned timestamps and overrides."""

    timestamp = format_import_timestamp()

    if settings.cert_name_override:
        override = settings.cert_name_override
        if _cert_name_has_version_suffix(override):
            print(
                "INFO: Using certificate name override (already versioned) "
                f"'{override}' (dry-run={settings.dry_run})"
            )
            return override
        # If override ends with legacy _YYYYMM, replace it
        if re.search(r"_\d{6}$", override):
            new_name = _replace_legacy_yyyymm(override, timestamp)
            print(f"INFO: Normalized legacy override '{override}' -> '{new_name}' (dry-run={settings.dry_run})")
            return new_name
        cert_name = f"{override}_{timestamp}"
        print(f"INFO: Using certificate name override base '{override}' -> '{cert_name}' (dry-run={settings.dry_run})")
        return cert_name

    cert_name = build_certificate_name(settings.mikrotik_domain, settings.fullchain_path)
    print(f"INFO: Using dynamic certificate name '{cert_name}' (dry-run={settings.dry_run})")
    return cert_name


def run(settings: Settings) -> bool:
    """Execute the certificate deployment workflow.

    Returns True when work was performed, False if skipped.
    """

    if settings.mikrotik_domain not in settings.renewed_domains:
        print(
            "INFO: Certificate for "
            f"{settings.mikrotik_domain} was not renewed. Skipping MikroTik update."
        )
        return False

    print(
        "SUCCESS: Certificate for "
        f"{settings.mikrotik_domain} was renewed. Running MikroTik update..."
    )
    if settings.debug:
        print(f"DEBUG: Using lineage directory: {settings.renewed_lineage}")

    client = RouterOSClient(settings)

    version_str, supports_type_file = detect_routeros_version(client)
    if settings.debug:
        if version_str:
            print(f"DEBUG: Detected RouterOS version {version_str} (supports type=file: {supports_type_file})")
        else:
            print(f"DEBUG: Could not detect RouterOS version (defaulting supports type=file: {supports_type_file})")

    cert_name = determine_certificate_name(settings)

    try:
        local_serial_hex = get_local_cert_serial(settings.fullchain_path)
        if settings.debug:
            print(f"DEBUG: Local certificate serial (hex)={local_serial_hex}")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Could not read local certificate serial: {exc}")
        local_serial_hex = None

    existing_cert_by_name = find_existing_certificate(client, cert_name)
    remote_serial_hex: str | None = None
    if existing_cert_by_name:
        remote_serial_hex = extract_remote_serial(existing_cert_by_name)
        if settings.debug and remote_serial_hex:
            print(f"DEBUG: Remote existing cert (by name) serial (hex)={remote_serial_hex}")

    existing_cert_by_serial = find_certificate_by_serial(client, local_serial_hex)
    if existing_cert_by_serial and settings.debug:
        print(
            "DEBUG: Found existing cert by serial with name="
            f"'{existing_cert_by_serial.get('name')}'"
        )

    skip_import = False

    # Collision handling: if a cert with the desired name exists but with a different
    # serial, do NOT delete it; instead derive a unique name using the last 6 hex
    # digits of the local serial (SEQ). If that name exists, append numeric suffixes.
    if existing_cert_by_name and local_serial_hex:
        if remote_serial_hex and remote_serial_hex.lower() != local_serial_hex.lower():
            seq = local_serial_hex[-6:].rjust(6, "0").upper()
            candidate = f"{cert_name}_{seq}"
            counter = 0
            while find_existing_certificate(client, candidate):
                counter += 1
                candidate = f"{cert_name}_{seq}_{counter}"
            print(
                "INFO: Name collision detected for '"
                f"{cert_name}'. Using '{candidate}' instead (SEQ={seq})."
            )
            cert_name = candidate

    # If a certificate with identical serial already exists (by serial), reuse it and skip import
    if (
        not settings.dry_run
        and not settings.force_reimport
        and local_serial_hex
        and (
            (remote_serial_hex and local_serial_hex.lower() == remote_serial_hex.lower())
            or (existing_cert_by_serial is not None)
        )
    ):
        name_used: str | None = None
        if existing_cert_by_serial:
            existing_serial_clean = extract_remote_serial(existing_cert_by_serial)
            if existing_serial_clean and existing_serial_clean.lower() == local_serial_hex.lower():
                name_used = existing_cert_by_serial.get("name")
        if name_used and name_used != cert_name:
            print(
                "INFO: Certificate with identical serial already present under "
                f"different name '{name_used}'."
            )
            print("INFO: Skipping upload/import to prevent duplicate (set FORCE_REIMPORT=1 to override).")
            cert_name = name_used
            skip_import = True
        else:
            print(
                "INFO: Existing router certificate (same name) has identical serial; skipping import."
            )
            skip_import = True

    remote_filename = f"{cert_name}.pem"

    if skip_import:
            print(
                "INFO: Skipping upload/import steps because an identical certificate "
                f"is already present on the router (using name '{cert_name}')."
            )
    else:
        if settings.dry_run:
            print(f"DRY-RUN: Would upload combined cert to file '{remote_filename}'")
        else:
            upload_certificate(client, remote_filename, cert_name, supports_type_file=supports_type_file)
            confirm_file_exists(client, remote_filename)

    if skip_import:
        print(
            f"INFO: Skipping removal of existing certificate named '{cert_name}' because import was skipped."
        )
    else:
        if settings.dry_run:
            print(f"DRY-RUN: Would remove existing certificate named '{cert_name}' (if present)")
        else:
            remove_old_certificate(client, cert_name)

    if skip_import:
        print(
            f"INFO: Skipping import because an identical certificate is already present under the name '{cert_name}'."
        )
    else:
        if settings.dry_run:
            print(
                f"DRY-RUN: Would import uploaded file '{remote_filename}' as certificate '{cert_name}'"
            )
        else:
            import_new_certificate(client, remote_filename, cert_name)
            confirm_certificate_present(client, cert_name)

    if not settings.dry_run and not settings.keep_uploaded_file:
        print("\n🧹 Cleaning up uploaded certificate file...")
        if delete_uploaded_file(client, remote_filename):
            print("✅ Uploaded file removed after import.")
        else:
            print("INFO: Uploaded file could not be deleted (may not exist or insufficient permissions).")
    elif settings.dry_run:
        print("DRY-RUN: Would delete uploaded file after import (skipped)")

    if settings.update_www_ssl:
        if settings.dry_run:
            print("DRY-RUN: Would apply certificate to service 'www-ssl'")
        else:
            update_ip_service(client, "www-ssl", cert_name)

    if settings.update_api_ssl:
        if settings.dry_run:
            print("DRY-RUN: Would apply certificate to service 'api-ssl'")
        else:
            update_ip_service(client, "api-ssl", cert_name)

    if settings.hotspot_profiles:
        for profile in settings.hotspot_profiles:
            if settings.dry_run:
                print(f"DRY-RUN: Would apply certificate to Hotspot profile '{profile}'")
            else:
                update_hotspot_profile(client, cert_name, profile)
    elif settings.debug:
        print("DEBUG: Skipping Hotspot step because profile list is empty after parsing")

    # Show pruning as an explicit step. Only perform pruning if we actually
    # imported a new certificate (to avoid removing certificates when we merely
    # detected an existing identical cert and skipped import).
    print("\n🔄 Step 6: Pruning old certificates...")
    # We consider an import to have occurred when we did not skip import and
    # we executed the import path (i.e., skip_import is False and we were not
    # in dry-run). The actual import call sets the state by virtue of running
    # without raising; we track it using a simple local variable.
    # Determine whether we imported: if skip_import is False and not dry_run
    imported = (not skip_import) and (not settings.dry_run)
    if imported:
        prune_old_certificates(
            client,
            settings.mikrotik_domain,
            cert_name,
            keep=2,
            dry_run=False,
        )
    else:
        if settings.dry_run:
            print("DRY-RUN: Would evaluate pruning after a successful import (skipped in dry-run).")
        else:
            print("INFO: Skipping prune because no import was performed.")

    print("\n✨ Certificate update process complete!")
    return True
