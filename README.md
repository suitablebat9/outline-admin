# Outline Admin

A self-hosted dashboard for managing an Outline Shadowsocks-over-WebSockets server. Create individual access keys, revoke access, view recorded traffic, and email setup instructions with an Apple DNS profile attached.

**Bring your own domain, server, and email account.** Hostnames, passwords, access keys, and generated profiles are created on your server and are not part of this repository. This is an independent project, not an official Outline product.

For an iPhone or Mac that connects through built-in VPN settings, see the [native IKEv2 gateway setup](native/README.md).

## Features

- Dark, responsive dashboard with two-second updates and manual refresh.
- Separate access credentials for each person; copy, share, or revoke a key.
- Per-key upload/download totals, daily traffic charts, recent activity, and an admin audit log.
- SQLite history retained across restarts and upgrades.
- Direct Gmail/Google Workspace invitations with a generated `.mobileconfig` attachment.
- Optional scoped encrypted DNS profiles for Mac and iPhone.
- Optional explicit WebSocket dial IP while preserving the HTTPS hostname.
- Login, CSRF protection, HTTPS-only session cookies, email rate limiting, and duplicate-request protection.

## Requirements

Use a dedicated Debian 12+ or Ubuntu 22.04+ server or Proxmox LXC with:

- Root access, systemd, an x86-64 or ARM64 CPU, and `curl`.
- Two hostnames you control, such as `vpn.example.com` and `admin.example.com`.
- A Cloudflare account and running Cloudflare Tunnel, or another HTTPS reverse proxy supporting WebSockets.
- Outbound internet access. If using email, the server also needs access to Gmail's SMTP service.

The installer can create a new Outline WebSocket server or reuse the existing installation at `/etc/outline-ws/config.yaml`. It installs Outline server version 1.9.2 when the binary is absent and verifies the official archive checksum. It manages nginx listeners and systemd services; use a dedicated instance rather than an unrelated production web server.

## 1. Install

Run **as root inside the server/LXC**, not on the Proxmox host:

```bash
curl -fsSL https://raw.githubusercontent.com/suitablebat9/outline-admin/v0.2.0/bootstrap.sh | bash
```

The installer asks for your VPN hostname, admin hostname, and admin password. On upgrades it preserves saved settings, access keys, email credentials, and traffic history. Outline restarts briefly during installation.

You can inspect `bootstrap.sh` and `install.sh` before running them. Alternatively, download the tagged source and run `bash install.sh` from the extracted directory. Forks can set `OUTLINE_ADMIN_REPOSITORY=OWNER/REPOSITORY` for the bootstrap download; publish the matching release tag in that repository first.

## 2. Connect your domain

For Cloudflare Tunnel, add two published application/public hostname routes:

| Public hostname | Service type | Service URL |
| --- | --- | --- |
| Your VPN hostname, e.g. `vpn.example.com` | HTTP | `YOUR_SERVER_PRIVATE_IP:18081` |
| Your admin hostname, e.g. `admin.example.com` | HTTP | `YOUR_SERVER_PRIVATE_IP:18082` |

If `cloudflared` runs on the Proxmox host, use the **LXC's IP**, not `localhost`. If it runs inside the same LXC, loopback is appropriate. Keep WebSockets enabled. The dashboard creates no DNS records and does not request a Cloudflare token.

No router port forwarding is required with Cloudflare Tunnel. If firewalls are enabled, allow the two origin ports only from your tunnel host. Do not expose the loopback application or metrics listeners publicly.

You may add Cloudflare Access to the **admin hostname**. Do not require a browser login for the VPN hostname: Outline cannot complete one. Avoid caching admin pages and access-key configuration files.

For a locally managed tunnel, add your routes before its catch-all rule, create DNS records for both hostnames using your tunnel name, and restart `cloudflared`. A different reverse proxy must provide HTTPS and preserve WebSocket upgrades for the VPN hostname.

## 3. Create access

Open your chosen **HTTPS admin URL** and sign in as `admin` using the password you chose.

1. Choose **Create access** and enter a username.
2. Copy the generated `ssconf://...` link into an official Outline Client that supports WebSockets (1.15.0+ on supported platforms).
3. Click a user's name or **Share** to view their code or copy setup instructions.
4. Choose **Revoke** to remove their server credential and disconnect sessions.

Adding or revoking access restarts Outline; other authorized users can reconnect. Existing keys imported from a supported configuration appear in the list. A hidden, never-distributed credential keeps an otherwise empty Outline configuration valid.

The dashboard manages this WebSocket server independently of Outline Manager. It does not integrate with Outline Manager's management API.

## 4. Optional: send invitations through Gmail

Create a Google app password with 2-Step Verification enabled. See [Google's app-password instructions](https://support.google.com/accounts/answer/185833). Some Workspace policies and Advanced Protection accounts do not support app passwords; this implementation requires an account that allows them.

Then run inside the LXC:

```bash
outline-admin-email-setup
```

Enter the sending address and app password at the hidden terminal prompt. Do not use your normal Google password or commit credentials. Setup verifies Gmail authentication over TLS without sending a test message.

Reload the dashboard, click **Share**, enter one recipient, and choose **Send email with attachment**. The email contains the person's access code and instructions, with an actual DNS profile generated for **your deployment's hostnames** attached. A download link on your VPN hostname is included as a fallback.

Credentials remain in `/etc/outline-admin/smtp.json`, readable only by root. Gmail receives the intended recipient address, access code, instructions, and attachment. The dashboard does not save recipient addresses in plaintext or include access codes in audit messages. Sending is limited to 20 requests per hour. The interface reports provider acceptance, not guaranteed inbox delivery. After an unconfirmed timeout, check the recipient inbox before sending again.

## Optional: encrypted DNS profiles

The installer generates a profile at:

```text
https://YOUR_VPN_HOSTNAME/profiles/outline-dns.mobileconfig
```

Download it on a working connection. It sends DNS queries only for your configured VPN/admin hostnames and their subdomains to Google Public DNS over HTTPS. It contains no access credential, root certificate, or device-management enrollment. Other domains keep their existing DNS configuration.

- **Mac:** open the profile and install it through System Settings → General → Device Management, or search Settings for Profiles.
- **iPhone:** download in Safari and install through Settings → General → VPN & Device Management.

The profile is unsigned and removable from the same screen. It addresses DNS lookup problems; it does not guarantee access through IP, TLS-hostname, or WebSocket filtering. See [profile details](client-profiles/README.md).

## Optional: pin the WebSocket dial address

If configuration fetching works but the tunnel fails with a hostname lookup error, you can configure a verified IPv4 address for **your own server/CDN endpoint**:

```bash
/opt/outline-admin/venv/bin/python /opt/outline-admin/configure_endpoint.py --endpoint YOUR_ENDPOINT_IPV4:443
systemctl restart outline-admin
```

The command validates HTTPS to the supplied IP with your original hostname, updates hosted client configurations, and saves the choice for future dashboard keys. It does not replace the URL hostname or disable certificate verification. No shared IP is hardcoded into this project. Revisit this setting if your endpoint's IP assignment changes.

The initial dynamic configuration download still needs DNS. Pinning the later WebSocket connection alone does not fix a failed configuration download.

## What the statistics mean

Metrics are collected every two seconds. The first successful scrape establishes a baseline; no earlier traffic is claimed as dashboard history.

- **Active recently** means tunnel-time or traffic counters increased within ten seconds. It is not an exact app connected/disconnected indicator or a device count. Idle apps and open UDP associations can affect this estimate.
- **Unknown** means telemetry is unavailable or older than ten seconds.
- **Upload/download** count the client-facing side of TCP and UDP traffic once, avoiding double counting the server-facing counters. Protocol overhead may be included.
- **TCP totals can be delayed** until connections close. Faster dashboard refresh cannot remove this server reporting behavior.
- Daily totals use the UTC day the increase was sampled. Aggregate history includes revoked users.
- Saved history survives restarts, but unsampled traffic around restarts or monitoring downtime may be lost. These are observed usage statistics, not billing-grade accounting.

## Operations

```bash
# Reset the admin password and invalidate sessions
outline-admin-password

# Inspect services and recent logs
systemctl status outline-admin outline-ws nginx --no-pager
journalctl -u outline-admin -u outline-ws -n 80 --no-pager
```

| Path / port | Purpose |
| --- | --- |
| `/etc/outline-admin/settings.json` | Local hostnames, password hash, session secret, optional dial endpoint |
| `/etc/outline-admin/smtp.json` | Optional local email credential |
| `/etc/outline-ws/config.yaml` | Outline server keys and WebSocket paths |
| `/etc/outline-ws/users.json` | Username-to-key mapping |
| `/var/lib/outline-ws/keys` | Secret, randomly named client configuration files |
| `/var/lib/outline-ws/profiles` | Generated deployment-specific DNS profile |
| `/var/lib/outline-admin` | Persistent usage and audit database |
| TCP 18081 / 18082 | VPN origin / admin origin, for your HTTPS proxy |
| Loopback 18080 / 18083 / 19090 | WebSocket server / dashboard / metrics |

Back up configuration and state privately. Stop the admin service while copying its SQLite database, or use a consistent SQLite backup. Treat backups and access links as credentials. Do not commit runtime files to GitHub.

This is a small single-admin application. The dashboard runs as root to manage root-owned configuration and restart Outline, with systemd filesystem restrictions. Use a strong password, HTTPS, and trusted administrators. Browser-visible code cannot submit arbitrary email content, attachments, or SMTP credentials. Updates rewrite the project's nginx listeners; custom proxy changes should be tracked separately.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
node --test tests/sharing.test.cjs
node --check static/app.js
bash -n install.sh bootstrap.sh
```

Tests use temporary files, example domains, and mocked SMTP; they never send real email. GitHub Actions checks Python 3.11 and 3.13. Actual systemd installation, email delivery, and reverse-proxy connectivity must be verified on your deployment.

## References and license

- [Outline WebSocket setup](https://developer.getoutline.org/vpn/advanced/websockets/)
- [Outline access-key configuration](https://developer.getoutline.org/vpn/reference/access-key-config/)
- [Apple DNS profile schema](https://github.com/apple/device-management/blob/release/mdm/profiles/com.apple.dnsSettings.managed.yaml)
- [MIT license](LICENSE)
