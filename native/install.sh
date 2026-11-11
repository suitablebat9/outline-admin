#!/usr/bin/env bash
# Install an IKEv2 endpoint inside a supported Debian or Ubuntu guest.
set -euo pipefail
umask 077
die() { echo "$*" >&2; exit 1; }
[[ $EUID == 0 ]] || die "Run as root inside the VPN guest."
[[ ! -d /etc/pve ]] || die "Open the VPN guest console instead of the Proxmox host shell."
source /etc/os-release
case "$ID:$VERSION_ID" in
    debian:12|ubuntu:24.04) ;;
    *) die "Supported guests are Debian 12 and Ubuntu 24.04." ;;
esac
state=/etc/apple-ikev2
if [[ ! -d $state ]]; then
    [[ ! -d /etc/swanctl && ! -f /etc/ipsec.conf ]] || die "Existing IPsec configuration found. Check the current installation first."
    listeners=$(ss -H -lun '( sport = :500 or sport = :4500 )')
    [[ -z $listeners ]] || die "UDP port 500 or 4500 is already in use."
fi
if systemd-detect-virt --container --quiet; then
    ip xfrm policy list >/dev/null || die "The container needs access to kernel IPsec policies."
    ip xfrm state count >/dev/null || die "The container needs access to kernel IPsec states."
    [[ $(sysctl -n net.ipv4.ip_forward) == 1 || -w /proc/sys/net/ipv4/ip_forward ]] || die "Enable net.ipv4.ip_forward=1 for this container in Proxmox."
fi
install -d -m 700 "$state"
exec 9>"$state/install.lock"
flock -n 9 || die "Another installation is running."
if [[ -s $state/hostname ]]; then
    host=$(cat "$state/hostname")
else
    read -rp 'Public VPN hostname: ' host </dev/tty
    [[ $host =~ ^([a-z0-9]([a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$ ]] || die "Enter a lowercase DNS hostname."
    echo "$host" > "$state/hostname"
fi

users=/etc/swanctl/conf.d/apple-users.conf
if [[ ! -s $users ]]; then
    read -rp 'Choose your VPN username: ' username </dev/tty
    [[ $username =~ ^[a-zA-Z0-9_-]{1,64}$ ]] || die "Use letters, numbers, dashes or underscores."
fi

apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y charon-systemd strongswan-swanctl libcharon-extra-plugins libstrongswan-extra-plugins certbot python3-certbot-dns-cloudflare iptables openssl
if [[ ! -s $state/cloudflare.ini ]]; then
    read -rsp 'Cloudflare API token (Edit zone DNS for your zone): ' token </dev/tty
    echo
    [[ $token =~ ^[a-zA-Z0-9_-]+$ ]] || die "Token is empty or invalid."
    printf 'dns_cloudflare_api_token = %s\n' "$token" > "$state/cloudflare.ini"
    unset token
fi
certbot certonly --dns-cloudflare --dns-cloudflare-credentials "$state/cloudflare.ini" \
    --dns-cloudflare-propagation-seconds 60 --cert-name "$host" --key-type rsa \
    --keep-until-expiring --agree-tos -d "$host" </dev/tty

hook=/etc/letsencrypt/renewal-hooks/deploy/apple-ikev2
install -d "$(dirname "$hook")"
cat > "$hook" <<'HOOK'
#!/bin/bash
set -euo pipefail
host=$(cat /etc/apple-ikev2/hostname)
[[ $RENEWED_LINEAGE == "/etc/letsencrypt/live/$host" ]] || exit 0
cd /etc/swanctl
install -m 600 "$RENEWED_LINEAGE/privkey.pem" private/apple-key.pem
install -m 644 "$RENEWED_LINEAGE/cert.pem" x509/apple-cert.pem
# swanctl reads one certificate per file.
awk '/BEGIN CERTIFICATE/{i++} i {print > ("x509ca/apple-issuer-" i ".pem")}' "$RENEWED_LINEAGE/chain.pem"
swanctl --load-creds --noprompt
swanctl --load-conns
HOOK
chmod 700 "$hook"
install -d /etc/swanctl/{conf.d,private,x509,x509ca}
grep -Eq '^\s*include\s+conf.d/\*\.conf' /etc/swanctl/swanctl.conf || die "Expected the default swanctl.conf with conf.d enabled."
cat > /etc/swanctl/conf.d/apple-ikev2.conf <<CONF
connections {
  apple {
    version = 2
    encap = yes
    send_cert = always
    proposals = aes256-sha256-modp2048,aes256-sha256-ecp256
    pools = apple4, apple6
    local {
      auth = pubkey
      id = $host
      certs = apple-cert.pem
    }
    remote {
      auth = eap-mschapv2
      eap_id = %any
    }
    children {
      internet {
        local_ts = 0.0.0.0/0,::/0
        esp_proposals = aes256-sha256-modp2048-modpnone
      }
    }
  }
}
pools {
  apple4 {
    addrs = 10.249.187.0/24
    dns = 1.1.1.1,1.0.0.1
  }
  apple6 {
    addrs = fd79:aead:5300::/120
  }
}
CONF
if [[ ! -s $users ]]; then
    password=$(openssl rand -hex 18)
    printf 'secrets {\n  eap-apple {\n    id = %s\n    secret = "%s"\n  }\n}\n' "$username" "$password" > "$users.tmp"
    mv "$users.tmp" "$users"
fi

cat > /usr/local/sbin/apple-ikev2-network <<'NET'
#!/bin/bash
set -euo pipefail
dev=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<NF;i++) if ($i=="dev") {print $(i+1); exit}}')
pool=10.249.187.0/24
rule() {
    local table=$1 chain=$2
    shift 2
    iptables -w -t "$table" -C "$chain" "$@" 2>/dev/null || iptables -w -t "$table" -I "$chain" 1 "$@"
}
rule filter INPUT -p udp -m multiport --dports 500,4500 -j ACCEPT
rule filter FORWARD -s "$pool" -o "$dev" -m policy --dir in --pol ipsec -j ACCEPT
rule filter FORWARD -d "$pool" -m policy --dir out --pol ipsec -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
# Only provide Internet access to remote users.
for subnet in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
    rule filter FORWARD -s "$pool" -d "$subnet" -j DROP
done
rule filter INPUT -s "$pool" -j DROP
rule nat POSTROUTING -s "$pool" -o "$dev" -m policy --dir out --pol none -j MASQUERADE
# Keep client IPv6 traffic local to the tunnel without changing guest-wide IPv6 settings.
for chain in INPUT FORWARD; do
    ip6tables -w -C "$chain" -s fd79:aead:5300::/120 -j DROP 2>/dev/null ||
        ip6tables -w -I "$chain" 1 -s fd79:aead:5300::/120 -j DROP
done
NET
chmod 700 /usr/local/sbin/apple-ikev2-network
cat > /etc/systemd/system/apple-ikev2-network.service <<'UNIT'
[Unit]
Description=Configure packet forwarding rules for Apple VPN clients
After=network-online.target
Wants=network-online.target
Before=strongswan.service

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/apple-ikev2-network
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
# Forwarding may already be set by Proxmox on a read-only sysctl mount.
if [[ $(sysctl -n net.ipv4.ip_forward) != 1 ]]; then
    sysctl -w net.ipv4.ip_forward=1
fi
if [[ -w /proc/sys/net/ipv4/ip_forward ]]; then
    echo 'net.ipv4.ip_forward=1' > /etc/sysctl.d/90-apple-ikev2.conf
fi
systemctl daemon-reload
systemctl enable apple-ikev2-network.service
systemctl restart apple-ikev2-network.service
# Stage the leaf before starting charon, whose service loads connections at startup.
install -m 644 "/etc/letsencrypt/live/$host/cert.pem" /etc/swanctl/x509/apple-cert.pem
systemctl enable --now strongswan.service certbot.timer
RENEWED_LINEAGE="/etc/letsencrypt/live/$host" "$hook"
swanctl --load-pools
swanctl --list-conns | grep -F 'apple:'
printf '\nType: IKEv2\nServer and Remote ID: %s\nLocal ID: leave blank\nAuthentication: Username\n' "$host"
awk '/^[[:space:]]*id =/{print "Username: " $3} /secret =/{gsub(/"/,"",$3); print "Password: " $3}' "$users"
