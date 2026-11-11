#!/bin/bash
# Only retire the project-managed Outline and Apple gateway files in this guest.
set -euo pipefail
umask 077
backup=$(mktemp -d /var/backups/vpn-legacy.XXXXXXXX)
archive() {
    local path
    for path in "$@"; do
        if [[ -e $path || -L $path ]]; then
            mkdir -p "$backup$(dirname "$path")"
            mv -- "$path" "$backup$path"
        fi
    done
}
if [[ -f /etc/outline-ws/config.yaml && -f /etc/systemd/system/outline-ws.service ]]; then
    systemctl disable --now outline-ws.service
    archive /etc/systemd/system/outline-ws.service /etc/systemd/system/outline-ws.service.d/admin-metrics.conf \
        /etc/nginx/conf.d/outline-ws.conf /etc/outline-ws /var/lib/outline-ws /usr/local/bin/outline-ws
    nginx -t
    systemctl reload nginx
fi
if [[ -f /etc/apple-ikev2/hostname ]]; then
    host=$(cat /etc/apple-ikev2/hostname)
    # Remove only rules matching the ones installed by the native gateway.
    dev=$(ip -4 route get 1.1.1.1 | awk '{for(i=1;i<NF;i++) if ($i=="dev") {print $(i+1);exit}}')
    pool=10.249.187.0/24
    drop_rule() {
        local tool=$1 table=$2 chain=$3
        shift 3
        if "$tool" -w -t "$table" -C "$chain" "$@" 2>/dev/null; then
            "$tool" -w -t "$table" -D "$chain" "$@"
        fi
    }
    if [[ -f /etc/systemd/system/apple-ikev2-network.service ]]; then
        systemctl disable --now apple-ikev2-network.service
        drop_rule iptables filter INPUT -p udp -m multiport --dports 500,4500 -j ACCEPT
        drop_rule iptables filter FORWARD -s "$pool" -o "$dev" -m policy --dir in --pol ipsec -j ACCEPT
        drop_rule iptables filter FORWARD -d "$pool" -m policy --dir out --pol ipsec -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
        for sub in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
            drop_rule iptables filter FORWARD -s "$pool" -d "$sub" -j DROP
        done
        drop_rule iptables filter INPUT -s "$pool" -j DROP
        drop_rule iptables nat POSTROUTING -s "$pool" -o "$dev" -m policy --dir out --pol none -j MASQUERADE
        for chain in INPUT FORWARD; do drop_rule ip6tables filter "$chain" -s fd79:aead:5300::/120 -j DROP; done
    fi
    archive /etc/systemd/system/apple-ikev2-network.service /usr/local/sbin/apple-ikev2-network \
        /etc/sysctl.d/90-apple-ikev2.conf /etc/letsencrypt/renewal-hooks/deploy/apple-ikev2 \
        /etc/swanctl/conf.d/apple-ikev2.conf /etc/swanctl/conf.d/apple-users.conf \
        /etc/swanctl/private/apple-key.pem /etc/swanctl/x509/apple-cert.pem /etc/swanctl/x509ca/apple-issuer-*.pem
    if systemctl is-active --quiet strongswan.service; then
        swanctl --load-all --noprompt >/dev/null
        connections=$(swanctl --list-conns)
        if [[ -z $connections ]]; then
            systemctl disable --now strongswan.service
        elif swanctl --list-sas --ike apple | grep '^apple:' >/dev/null; then
            swanctl --terminate --ike apple --force
        fi
    elif systemctl is-enabled --quiet strongswan.service && ! compgen -G '/etc/swanctl/conf.d/*.conf' >/dev/null; then
        systemctl disable strongswan.service
    fi
    if [[ $host =~ ^[a-z0-9.-]+$ ]] && grep -qF '/etc/apple-ikev2/cloudflare.ini' "/etc/letsencrypt/renewal/$host.conf" 2>/dev/null; then
        archive "/etc/letsencrypt/renewal/$host.conf"
    fi
    # Another cert may be using this credential. Leave it in place in that case.
    if grep -RsF '/etc/apple-ikev2/cloudflare.ini' /etc/letsencrypt/renewal 2>/dev/null | grep . >/dev/null; then
        archive /etc/apple-ikev2/hostname
    else
        archive /etc/apple-ikev2
    fi
fi
archive /usr/local/bin/outline-admin-email-setup /etc/outline-admin/smtp.json \
    /opt/outline-admin/{configure_endpoint,mailer,manager,native_accounts,profiles,setup_email}.py \
    /opt/outline-admin/client-profiles /opt/outline-admin/static/{sharing,native,wireguard}.js
systemctl daemon-reload
if ! rmdir "$backup" 2>/dev/null; then echo "Retired VPN files are stored in $backup (root only)."; fi
