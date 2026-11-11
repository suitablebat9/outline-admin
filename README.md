# WireGuard dashboard

Self-host a WireGuard gateway and manage one private profile per device. Devices can connect directly with the WireGuard app or use sing-box to carry WireGuard through Shadowsocks over TCP. The dashboard supports local QR import, both profile downloads, individual revocation and per-device traffic statistics.

## Install or upgrade

Run in a Debian 12 or Ubuntu 24.04 guest as root. The installer supports amd64 and arm64 and uses systemd, nginx and a checksum-verified sing-box release.

```bash
curl -fsSLo /tmp/update-vpn.sh https://raw.githubusercontent.com/suitablebat9/outline-admin/v0.5.0/bootstrap.sh && bash /tmp/update-vpn.sh
```

On first install, enter your reachable public IPv4 address, forwarded TCP port, dashboard hostname and admin password. Publish the dashboard through your HTTPS tunnel or reverse proxy to the guest’s HTTP port 18082. Forward the selected TCP port (default 443) for sing-box and UDP 51820 for direct WireGuard. Allow these ports through applicable firewalls. A public IPv4 address reachable through your router or hosting provider is required for the VPN.

On upgrade, existing device keys, admin login and port settings are reused. The gateway briefly reconnects. The installer retires the previous project-managed Outline WebSocket and Apple IKEv2 services and moves their configuration into a root-only directory under /var/backups. Remove obsolete router forwards for UDP 500 and 4500 and the old Outline public hostname route if they were dedicated to those services. Keep the dashboard hostname route.

## Devices and usage

Use **Add device** for each phone or computer. Open **Profile** to scan the QR in sing-box MT, download JSON for sing-box, download a config for the WireGuard app, or revoke both credentials. Device changes briefly restart the gateway. Anyone with the QR or either file can use that device’s access.

Upload, download, last activity, and today’s transfer are tracked by device key. Shared profiles combine usage. The seven-day chart uses UTC. Totals include recorded usage from revoked devices. The gateway counts decrypted traffic once across both transports, excluding relay overhead. The collector samples open flows and up to 1,000 recently closed flows every two seconds, even while the dashboard is closed. Counter history starts with this release. Extended downtime, heavy churn or an abrupt gateway restart can leave gaps. Recent traffic is an activity indicator.

The monitoring API binds to loopback port 18971 and requires a server-derived secret. Statistics and login state use SQLite in /var/lib/outline-admin. Device secrets remain in /etc/outline-wireguard/devices.json. Use the existing outline-admin-password command to reset the dashboard login.
