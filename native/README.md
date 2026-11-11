# Native VPN for iPhone and Mac

Use a Debian 12 LXC or Ubuntu Server 24.04 guest with systemd and a reserved LAN IPv4 address. An existing Outline container can run this service alongside Outline when it has kernel IPsec and firewall access. Run the installer inside the guest. The native gateway uses strongSwan IKEv2 with individual credentials stored on the guest. Outline keys, dashboard statistics, and email invitations apply to the Outline service only.

1. In Cloudflare DNS, create a DNS-only A record for a new hostname pointing to your router's public IPv4 address. Keep it updated if your ISP changes your address. A router behind carrier-grade NAT needs an ISP-provided public address or another publicly reachable gateway.
2. Forward UDP 500 and UDP 4500 from the router to the **same ports on the VPN guest**. Allow both in any Proxmox firewall protecting the guest. The installer uses DNS validation for its Let's Encrypt certificate.
3. Create a Cloudflare API token using the **Edit zone DNS** template, limited to the single domain. The installer saves it root-only on the guest for certificate renewal.
4. Download and run the native installer in the guest. Enter your new hostname and choose your username. Copy the generated password from the guest console.

```bash
curl -fsSLo /tmp/install-apple-vpn.sh https://raw.githubusercontent.com/suitablebat9/outline-admin/main/native/install.sh && sudo bash /tmp/install-apple-vpn.sh
```

On iPhone open **Settings → General → VPN & Device Management → VPN → Add VPN Configuration**. On Mac open **System Settings → VPN → Add VPN Configuration → IKEv2**. Choose IKEv2, enter any description, enter the hostname as Server and Remote ID, leave Local ID empty, and select Username authentication. Enter the credentials printed by the installer. If the local network filters DNS for your hostname, try the current public IPv4 address in Server and keep the hostname in Remote ID.

Test first from cellular with Wi-Fi off. On the guest, `sudo swanctl --list-sas` shows active sessions. The gateway provides IPv4 internet access. It assigns an IPv6 tunnel address and requests the default IPv6 route, with the VPN clients’ IPv6 traffic dropped by guest firewall rules. Client operating systems control routing exceptions. Networks that block IKEv2 can prevent connections even when DNS works.

For additional users, edit `/etc/swanctl/conf.d/apple-users.conf` as root and add another uniquely named `eap-...` block inside `secrets` with its own `id` and a strong random `secret`. Run `sudo swanctl --load-creds --clear` after editing. To revoke a user, remove their block, reload credentials and terminate each of their active sessions with `sudo swanctl --terminate --ike-id NUMBER` using the session numbers from `sudo swanctl --list-sas`.

[strongSwan Apple client documentation](https://docs.strongswan.org/docs/latest/interop/ios.html)
