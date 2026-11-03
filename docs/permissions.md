# RouterOS Least‑Privilege Permissions

Goal: allow certificate upload/import and service/profile updates via REST (and optional SFTP fallback) while avoiding broad administrative rights.

## Recommended Group

Create a dedicated group with only the needed policies.

With `UPDATE_WWW_SSL=false` and no SFTP fallback (REST only):

```routeros
/user group add name=certbot \
  policy="read,write,api,rest-api,!local,!telnet,!ftp,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon"
```

With `www-ssl` updates enabled, add SSH for the disable/assign/enable sequence and recovery. Add FTP too when using SFTP upload fallback (RouterOS < 7.17):

```routeros
/user group add name=certbot \
  policy="read,write,api,rest-api,ssh,ftp,!local,!telnet,!reboot,!policy,!test,!winbox,!password,!web,!sniff,!sensitive,!romon"
```

Notes:
- `read`/`write` are required to query and patch resources (files, certificates, services, hotspot profiles).
- `rest-api` is required for the HTTP endpoints; `api` is harmless and sometimes useful for inspection.
- SSH `www-ssl` updates and recovery require `ssh` and `write`; they do not use FTP.
- For SFTP upload fallback, both `ssh` and `ftp` policies are required on RouterOS to permit file operations over SFTP.
- Avoid enabling `ftp`, `web`, or other interactive policies unless absolutely necessary.

## Create User

```routeros
/user add name=certbot group=certbot password=STRONG_PASSWORD
```

Rotate credentials periodically and store them outside shell history where possible.

## Verification

Quick checks to confirm permissions without over‑provisioning:

```routeros
# Verify REST is reachable (from your automation host):
#   curl -k -u certbot:STRONG_PASSWORD https://ROUTER:8443/rest/system/resource

# From RouterOS, verify user exists and group policies look correct:
/user/print where name=certbot
/user/group/print where name=certbot
```

If REST calls fail with 401/403, audit logs and add only the specific missing policy.
