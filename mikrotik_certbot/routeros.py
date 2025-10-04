from __future__ import annotations

# ruff: noqa: E501, S110, S112
import re
from dataclasses import dataclass
from typing import Any

import paramiko
import requests
import urllib3
from urllib3.exceptions import InsecureRequestWarning

from .certificates import CombinedCertificate, combine_certificate_material
from .config import ConfigurationError, Settings

urllib3.disable_warnings(InsecureRequestWarning)

__all__ = [
    "RouterOSClient",
    "detect_routeros_version",
    "find_certificate_by_serial",
    "find_existing_certificate",
    "extract_remote_serial",
    "import_new_certificate",
    "remove_old_certificate",
    "update_hotspot_profile",
    "update_ip_service",
    "prune_old_certificates",
    "upload_certificate",
    "delete_uploaded_file",
    "confirm_certificate_present",
    "confirm_file_exists",
]


@dataclass(slots=True)
class RouterOSClient:
    """Thin wrapper around the RouterOS REST endpoints with consistent defaults."""

    settings: Settings

    @property
    def base_url(self) -> str:
        return self.settings.base_url.rstrip("/")

    @property
    def hostname(self) -> str:
        return self.settings.router_host.split(":")[0]

    @property
    def auth(self) -> tuple[str, str]:
        return self.settings.auth

    def url(self, path: str) -> str:
        path = path.lstrip("/")
        return f"{self.base_url}/{path}" if path else self.base_url

    def get(self, path: str, *, params: dict[str, Any] | None = None, timeout: int = 10, label: str | None = None) -> requests.Response:
        resp = requests.get(self.url(path), auth=self.auth, verify=self.settings.verify_ssl, params=params, timeout=timeout)
        if label:
            self.debug_http(resp, label)
        return resp

    def post(self, path: str, *, json: Any | None = None, timeout: int = 15, label: str | None = None) -> requests.Response:
        resp = requests.post(self.url(path), auth=self.auth, verify=self.settings.verify_ssl, json=json, timeout=timeout)
        if label:
            self.debug_http(resp, label)
        return resp

    def patch(self, path: str, *, json: Any | None = None, timeout: int = 15, label: str | None = None) -> requests.Response:
        resp = requests.patch(self.url(path), auth=self.auth, verify=self.settings.verify_ssl, json=json, timeout=timeout)
        if label:
            self.debug_http(resp, label)
        return resp

    def delete(self, path: str, *, timeout: int = 15, label: str | None = None) -> requests.Response:
        resp = requests.delete(self.url(path), auth=self.auth, verify=self.settings.verify_ssl, timeout=timeout)
        if label:
            self.debug_http(resp, label)
        return resp

    def debug_http(self, resp: requests.Response, label: str) -> None:
        if not self.settings.debug:
            return

        try:
            content_type = resp.headers.get("Content-Type", "") or ""
        except Exception:  # pragma: no cover - defensive
            content_type = ""

        summary = [f"HTTP {resp.status_code}"]
        if content_type:
            summary.append(f"ct={content_type}")
        try:
            length = resp.headers.get("Content-Length")
            if length:
                summary.append(f"len={length}")
        except Exception:  # pragma: no cover - defensive
            pass

        body_detail = ""
        if self.settings.full_http_debug:
            try:
                if "application/json" in content_type:
                    data = resp.json()
                    if isinstance(data, dict):
                        keys = list(data.keys())
                        body_detail = f"json_keys={keys[:12]}"
                        if "detail" in data:
                            detail_val = str(data["detail"])
                            if len(detail_val) > self.settings.http_debug_body_limit:
                                detail_val = detail_val[: self.settings.http_debug_body_limit] + "\u2026"
                            body_detail += f" detail={detail_val!r}"
                    elif isinstance(data, list):
                        body_detail = f"json_list_len={len(data)}"
                else:
                    text = resp.text
                    if len(text) > self.settings.http_debug_body_limit:
                        text = text[: self.settings.http_debug_body_limit] + "\u2026"
                    if "-----BEGIN PRIVATE KEY-----" in text:
                        text = re.sub(
                            r"-{5}BEGIN PRIVATE KEY-{5}[\s\S]*?-{5}END PRIVATE KEY-{5}",
                            "[REDACTED-PRIVATE-KEY]",
                            text,
                        )
                    body_detail = f"body={text!r}"
            except Exception:  # pragma: no cover - defensive
                body_detail = "<unparseable>"
        else:
            try:
                if "application/json" in content_type:
                    data = resp.json()
                    if isinstance(data, dict):
                        keys = list(data.keys())[:6]
                        body_detail = "json_keys=" + ",".join(keys)
                    elif isinstance(data, list):
                        body_detail = f"json_list_len={len(data)}"
                else:
                    snippet = resp.text[:80].replace("\n", " ")
                    body_detail = f"text_snip={snippet!r}"
            except Exception:  # pragma: no cover - defensive
                body_detail = "<unparseable>"

        if body_detail:
            summary.append(body_detail)
        print(f"DEBUG: {label} -> {' '.join(summary)}")


def detect_routeros_version(client: RouterOSClient) -> tuple[str | None, bool]:
    version: str | None = None
    for endpoint in ("system/resource", "system/package"):
        try:
            resp = client.get(endpoint, timeout=10)
        except requests.RequestException:
            continue
        if not resp.ok:
            continue
        try:
            data = resp.json()
        except Exception:
            continue
        if isinstance(data, dict) and "version" in data:
            version = str(data.get("version"))
            break
        if isinstance(data, list) and data and isinstance(data[0], dict) and "version" in data[0]:
            version = str(data[0].get("version"))
            break

    if not version:
        return None, False

    match = re.match(r"^(\d+)\.(\d+)", version.strip())
    if not match:
        return version, False
    major, minor = int(match.group(1)), int(match.group(2))
    supports_type = (major > 7) or (major == 7 and minor >= 17)
    return version, supports_type


def confirm_file_exists(client: RouterOSClient, remote_filename: str) -> None:
    try:
        resp = client.get("file", params={"name": remote_filename}, timeout=15, label=f"post-upload file confirm '{remote_filename}'")
        if resp.ok:
            items = resp.json()
            if items:
                print(f"INFO: Remote file '{remote_filename}' present (will be imported).")
            else:
                print(f"WARN: Remote file '{remote_filename}' not found right after upload.")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Could not confirm uploaded file presence: {exc}")


def confirm_certificate_present(client: RouterOSClient, cert_name: str) -> None:
    try:
        resp = client.get("certificate", params={"name": cert_name}, timeout=20, label=f"post-import cert confirm '{cert_name}'")
        if resp.ok:
            entries = resp.json()
            if entries:
                print(f"INFO: Confirmed certificate '{cert_name}' exists (id={entries[0].get('.id', '?')}).")
            else:
                print(f"WARN: Certificate '{cert_name}' not found immediately after import.")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Could not confirm certificate presence: {exc}")


def find_existing_certificate(client: RouterOSClient, cert_name: str):
    try:
        resp = client.get("certificate", params={"name": cert_name}, timeout=20, label=f"serial preflight lookup '{cert_name}'")
        if not resp.ok:
            return None
        items = resp.json()
        if items:
            return items[0]
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Could not fetch existing certificate for serial comparison: {exc}")
    return None


def extract_remote_serial(item) -> str | None:
    if not item:
        return None
    serial = item.get("serial-number") or item.get("serial")
    if not serial:
        return None
    serial_clean = serial.replace(":", "").strip()
    return serial_clean.upper() or None


def find_certificate_by_serial(client: RouterOSClient, serial_hex: str | None):
    if not serial_hex:
        return None
    try:
        resp = client.get("certificate", timeout=30, label="certificate list for serial scan")
        if not resp.ok:
            return None
        items = resp.json()
        target = serial_hex.lower()
        for item in items:
            remote_serial = extract_remote_serial(item)
            if remote_serial and remote_serial.lower() == target:
                return item
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Serial scan failed: {exc}")
    return None


def upload_certificate(client: RouterOSClient, remote_filename: str, cert_name: str, *, supports_type_file: bool) -> None:
    print("\n🔄 Step 1: Combining and Uploading Certificate...")
    try:
        combined: CombinedCertificate = combine_certificate_material(
            client.settings.key_path,
            client.settings.fullchain_path,
        )
        if client.settings.debug:
            print(
                "DEBUG: Combined cert size="
                f"{len(combined.pem)} bytes (key={combined.key_length}, chain={combined.chain_length})"
            )
    except OSError as exc:  # pragma: no cover - filesystem access
        raise ConfigurationError("Could not read certificate files for upload.") from exc

    if client.settings.dry_run:
        print("DRY-RUN: Skipping actual upload (simulating success)")
        return

    if supports_type_file:
        print("Attempting upload via REST /file/add (type=file)")
        if _upload_rest_add(client, remote_filename, combined.pem):
            print(f"✅ Uploaded via REST as '{remote_filename}' (cert name: {cert_name})")
            return
        raise RuntimeError("REST upload failed; aborting.")

    print("INFO: RouterOS version <7.17 – falling back to SFTP upload")
    if _sftp_upload(client, remote_filename, combined.pem):
        print(f"✅ Uploaded via SFTP as '{remote_filename}' (cert name: {cert_name})")
        return
    raise RuntimeError("SFTP upload failed.")


def _upload_rest_add(client: RouterOSClient, remote_filename: str, combined_cert: str) -> bool:
    overwrite = client.settings.overwrite_files

    def attempt() -> requests.Response:
        payload = {"name": remote_filename, "contents": combined_cert, "type": "file"}
        return client.post("file/add", json=payload, timeout=30, label=f"file/add upload '{remote_filename}'")

    resp = attempt()
    if resp.ok:
        return True
    if resp.status_code == 400:
        try:
            data = resp.json()
        except Exception:
            data = {}
        detail = (data or {}).get("detail", "")
        if overwrite and isinstance(detail, str) and "already exists" in detail.lower():
            print("INFO: File exists – attempting delete then re-upload...")
            if delete_uploaded_file(client, remote_filename):
                resp = attempt()
                if resp.ok:
                    return True
                print(f"ERROR: Re-upload after delete failed HTTP {resp.status_code}")
            else:
                print("WARN: Could not delete existing file; aborting overwrite.")
    content_type = resp.headers.get("Content-Type", "")
    print(f"rest-add failed HTTP {resp.status_code}")
    if "application/json" in content_type:
        try:
            print(f"Response JSON: {resp.json()}")
        except Exception:
            print(f"Body: {resp.text[:400]}")
    else:
        print(f"Body: {resp.text[:400]}")
    return False


def _sftp_upload(client: RouterOSClient, remote_filename: str, combined_cert: str) -> bool:
    host = client.hostname
    username, password = client.auth
    try:
        ssh = paramiko.SSHClient()
        # Respect configured policy: auto-accept unknown host keys only when enabled.
        if client.settings.sftp_auto_accept_host_key:
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())  # noqa: S507 - intentional: accept host key for SFTP uploads
        else:
            # Be explicit: reject unknown host keys to avoid accidental trust.
            ssh.set_missing_host_key_policy(paramiko.RejectPolicy())
        ssh.connect(host, port=22, username=username, password=password, timeout=20)
        sftp = ssh.open_sftp()
        with sftp.file(remote_filename, "w") as handle:
            handle.write(combined_cert)
        sftp.close()
        ssh.close()
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: SFTP upload exception: {exc}")
        return False


def delete_uploaded_file(client: RouterOSClient, remote_filename: str) -> bool:
    try:
        resp = client.get("file", params={"name": remote_filename}, timeout=15, label=f"file lookup for delete '{remote_filename}'")
        if not resp.ok:
            print(f"INFO: File lookup failed HTTP {resp.status_code}; cannot delete.")
            return False
        items = resp.json()
        if not items:
            print("INFO: File not present; nothing to delete.")
            return False
        file_id = items[0].get(".id")
        if not file_id:
            print("INFO: File entry lacks .id; cannot delete.")
            return False
        del_resp = client.delete(f"file/{file_id}", timeout=15, label=f"file delete '{remote_filename}' id={file_id}")
        if del_resp.ok:
            print("INFO: Existing file deleted.")
            return True
        print(f"INFO: Delete failed HTTP {del_resp.status_code}")
        return False
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Exception during delete attempt: {exc}")
        return False


def remove_old_certificate(client: RouterOSClient, cert_name: str) -> None:
    # To follow the PRD, do not remove an existing certificate with the same name
    # prior to importing a new certificate. This function will log intent but avoid
    # deleting to prevent removing an in-use cert before the new one is bound.
    print("\n🔄 Step 2: Checking for existing certificate (will NOT remove to avoid downtime)...")
    try:
        response = client.get("certificate", params={"name": cert_name}, label=f"certificate lookup '{cert_name}'")
        response.raise_for_status()
        certs = response.json()
        if certs:
            cert_id = certs[0].get(".id")
            print(f"INFO: Existing certificate named '{cert_name}' present (id={cert_id}). Will not remove prior to import to avoid service interruption.")
        else:
            print("INFO: No existing certificate found with that name. Proceeding.")
    except Exception as exc:  # noqa: BLE001
        print(f"WARN: Could not check for existing certificate: {exc}")


def import_new_certificate(client: RouterOSClient, remote_filename: str, cert_name: str) -> None:
    print("\n🔄 Step 3: Importing new certificate...")
    # Ensure the private key cannot be exported after import
    # RouterOS accepts the hyphenated form `no-key-export=yes`.
    payload = {"name": cert_name, "file-name": remote_filename, "passphrase": "", "no-key-export": "yes"}
    response = client.post("certificate/import", json=payload, label=f"certificate import '{cert_name}' from '{remote_filename}'")
    response.raise_for_status()
    print("✅ New certificate imported.")


def update_ip_service(client: RouterOSClient, service_name: str, cert_name: str) -> None:
    print(f"\n🔄 Step 4: Applying certificate to IP service '{service_name}'...")
    response = client.get("ip/service", params={"name": service_name}, label=f"service lookup '{service_name}'")
    response.raise_for_status()
    services = response.json()
    if services:
        service_id = services[0][".id"]
        payload = {"certificate": cert_name}
        patch_response = client.patch(f"ip/service/{service_id}", json=payload, label=f"service patch '{service_name}' apply cert '{cert_name}'")
        patch_response.raise_for_status()
        print(f"✅ Certificate applied to '{service_name}'.")
    else:
        print(f"⚠️ Service '{service_name}' not found.")


def update_hotspot_profile(client: RouterOSClient, cert_name: str, profile_name: str) -> None:
    print(f"\n🔄 Step 5: Applying certificate to Hotspot profile '{profile_name}'...")
    response = client.get("ip/hotspot/profile", params={"name": profile_name}, label=f"hotspot profile lookup '{profile_name}'")
    response.raise_for_status()
    profiles = response.json()
    if profiles:
        profile_id = profiles[0][".id"]
        payload = {"ssl-certificate": cert_name}
        patch_response = client.patch(
            f"ip/hotspot/profile/{profile_id}",
            json=payload,
            label=f"hotspot profile patch '{profile_name}' apply cert '{cert_name}'",
        )
        patch_response.raise_for_status()
        print(f"✅ Certificate applied to Hotspot profile '{profile_name}'.")
    else:
        print(f"⚠️ Hotspot profile '{profile_name}' not found.")


def prune_old_certificates(client: RouterOSClient, domain: str, current_cert_name: str, *, keep: int = 2, dry_run: bool = False) -> None:
    print(
        f"INFO: prune_old_certificates called for domain='{domain}', current_cert_name='{current_cert_name}', keep={keep}, dry_run={dry_run}"
    )
    # Derive the base prefix from the current certificate name when possible.
    # Many deployments use a short base name (e.g. 'lp-218b-fw3_2025...') rather than
    # a full domain-based prefix (e.g. 'lp-218b-fw3_mgmt_weber_edu_'). Prefer the
    # actual current cert name so pruning matches what was imported.
    base_prefix = None
    # Match trailing version or legacy suffix on the current name
    m = re.search(r"(_\d{8}T\d{4}(?:_.*)?$)|(_\d{6}$)", current_cert_name)
    if m:
        base_name = current_cert_name[: m.start()]
        base_prefix = base_name + "_"
    if not base_prefix:
        base_prefix = domain.replace(".", "_") + "_"
    try:
        resp = client.get("certificate", timeout=30, label="certificate list for pruning")
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"WARN: Could not list certificates for pruning: {exc}")
        return
    try:
        items = resp.json()
    except Exception:
        print("WARN: Certificate list response not JSON; skipping prune")
        return

    # Recognise new names like base_YYYYMMDDThhmm and optional _SEQ/_1 suffixes,
    # as well as legacy base_YYYYMM names. Normalize to sortable timestamp key.
    versioned_re = re.compile(r"^" + re.escape(base_prefix) + r"(\d{8}T\d{4})(?:_[0-9A-Fa-f]{1,}|_\d+)?$")
    legacy_re = re.compile(r"^" + re.escape(base_prefix) + r"(\d{6})$")
    matched: list[tuple[str, str, int]] = []
    for cert in items:
        name = cert.get("name") or cert.get("name.0") or ""
        cert_id = cert.get(".id")
        if not name or not cert_id:
            continue
        m = versioned_re.match(name)
        if m:
            ts = m.group(1)  # YYYYMMDDThhmm
            # sortable integer key: YYYYMMDDhhmm
            key = int(ts.replace("T", ""))
            matched.append((name, cert_id, key))
            continue
        m2 = legacy_re.match(name)
        if m2:
            yyyymm = m2.group(1)
            # treat legacy as YYYYMM01T0000 -> key YYYYMM010000
            key = int(f"{yyyymm}010000")
            matched.append((name, cert_id, key))
            continue

    if not matched:
        if dry_run:
            print("DRY-RUN: No certificates found matching naming patterns; nothing to prune.")
        else:
            print("INFO: No certificates found matching naming patterns; nothing to prune.")
        return

    matched.sort(key=lambda entry: entry[2], reverse=True)
    to_keep = {entry[0] for entry in matched[:keep]}
    deletions = [entry for entry in matched if entry[0] not in to_keep]

    if dry_run:
        print(
            f"DRY-RUN: Evaluating {len(matched)} certificate(s) (keeping newest {keep})."
        )
        print("DRY-RUN: Decision list (newest first):")
        for name, _, _key in matched:
            if name == current_cert_name:
                status = "CURRENT-KEEP"
            elif name in to_keep:
                status = "KEEP"
            else:
                status = "DELETE"
            print(f"  - {name}  [{status}]")
        if deletions:
            deletion_names = [name for name, _, _ in deletions if name != current_cert_name]
            print(f"DRY-RUN: {len(deletion_names)} certificate(s) would be deleted, {len(to_keep)} kept.")
        else:
            print("DRY-RUN: No deletions required; all existing certs within retention window.")
        return

    if not deletions:
        print("INFO: No old certificates to prune.")
        return

    # Build reverse maps to detect references
    def _is_cert_referenced(name: str) -> list[str]:
        refs: list[str] = []
        try:
            svc_resp = client.get("ip/service", label=f"service list for ref check '{name}'")
            if svc_resp.ok:
                for svc in svc_resp.json():
                    cert_field = svc.get("certificate") or svc.get("certificate.0")
                    if cert_field == name:
                        refs.append(f"ip/service:{svc.get('name')}")
        except Exception:
            pass
        try:
            hs_resp = client.get("ip/hotspot/profile", label=f"hotspot list for ref check '{name}'")
            if hs_resp.ok:
                for prof in hs_resp.json():
                    cert_field = prof.get("ssl-certificate") or prof.get("ssl-certificate.0")
                    if cert_field == name:
                        refs.append(f"ip/hotspot/profile:{prof.get('name')}")
        except Exception:
            pass
        return refs

    print(
        f"INFO: Pruning {len(deletions)} old certificate(s), "
        f"keeping {len(to_keep)} latest."
    )
    for name, cert_id, _ in deletions:
        if name == current_cert_name:
            continue
        refs = _is_cert_referenced(name)
        if refs:
            print(f"WARN: Skipping deletion of '{name}' because it is still referenced by: {refs}")
            continue
        try:
            del_resp = client.delete(f"certificate/{cert_id}", timeout=20)
            if del_resp.ok:
                print(f"INFO: Pruned old certificate '{name}' (id {cert_id}).")
            else:
                print(f"WARN: Failed to delete cert '{name}' HTTP {del_resp.status_code}")
        except requests.RequestException as exc:
            print(f"WARN: Exception deleting cert '{name}': {exc}")

