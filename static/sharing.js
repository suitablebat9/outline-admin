'use strict';

function buildShareMessage(name, key, email = '') {
  if (!key.startsWith('ssconf://') || /\s/.test(key)) throw new Error('Invalid access link. Reopen this user and try again.');
  if (email && !/^[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+$/.test(email)) throw new Error('Enter one valid email address.');
  const domain = new URL(key.replace(/^ssconf:\/\//, 'https://')).hostname;
  const profile = `https://${domain}/profiles/outline-dns.mobileconfig`;
  const subject = 'Your Outline Admin VPN access';
  const body = `Hi ${name},

Here is your personal Outline Admin VPN access.

1. Install the official Outline Client (version 1.15.0 or newer):
https://getoutline.org/get-started/

2. In Outline, choose Add server and paste this entire access code:
${key}

3. For Mac or iPhone, if the network cannot resolve our VPN hostname, download this DNS profile on a working connection:
${profile}

Mac: open the file, then install Outline Admin — Encrypted DNS in System Settings → General → Device Management (or search for Profiles).
iPhone: download in Safari, then install Outline Admin — Encrypted DNS in Settings → General → VPN & Device Management.

The profile uses Google encrypted DNS only for the VPN and admin hostnames listed in the profile and their subdomains. It is unsigned and contains no VPN access key or device-management enrollment. You can remove it from the same settings screen.

4. Disconnect other VPNs and connect in Outline.

Keep your access code private: anyone with it can use your access. Contact me if you need help or want the key revoked.

Outline Admin`;
  return { subject, body, mailto: email ? `mailto:${encodeURIComponent(email)}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}` : null };
}

if (typeof module !== 'undefined' && module.exports) module.exports = { buildShareMessage };
else window.OutlineShare = { buildShareMessage };
