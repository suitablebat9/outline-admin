# Deployment-specific DNS profiles

There is intentionally no ready-made personal configuration profile in this repository.

`profiles.py` generates an Apple encrypted-DNS profile from the VPN and admin hostnames supplied during installation. The installer writes it to `/var/lib/outline-ws/profiles/outline-dns.mobileconfig` on your server, served at `https://YOUR_VPN_HOSTNAME/profiles/outline-dns.mobileconfig`. Email invitations generate the same profile from your settings and attach the file directly.

The profile uses Google Public DNS over HTTPS, with supplied resolver IPs so it does not depend on the network resolving the DNS service hostname. Only the configured hostnames and their subdomains match. Google receives those DNS queries. It contains no VPN credential, certificate, traffic tunnel, or device-management enrollment.

Download on a working network, review the profile, and approve installation in the Mac/iPhone Profiles or Device Management settings. The profile is unsigned and removable. Apple's schema supports manual installation on iOS 14+ and macOS 11+; it is marked deprecated from OS 27 in the current schema. Organization-managed devices may restrict profiles.

Encrypted DNS can address resolver failures but not every type of network filtering. Another VPN, application-specific DNS resolver, or managed policy may override it. Test the actual Outline connection; `nslookup` does not necessarily use macOS's scoped resolver settings.

Remove the profile through the same device settings to restore prior DNS behavior. Do not upload generated deployment profiles or access credentials to this repository.
