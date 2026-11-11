#!/bin/bash
# Install the standalone Mac client with the WireGuard and Shadowsocks components.
set -euo pipefail
umask 077

launch=true
case "${1:-}" in
    --no-open) launch=false ;;
    '') ;;
    *) echo 'Usage: bash install-sfm.sh [--no-open]' >&2; exit 2 ;;
esac

if [[ $(uname -s) != Darwin ]]; then
    echo 'Run this installer on the Mac that will connect to the VPN.' >&2
    exit 1
fi
macos_version=$(/usr/bin/sw_vers -productVersion)
if (( ${macos_version%%.*} < 13 )); then
    echo 'SFM requires macOS 13 or later.' >&2
    exit 1
fi

app=/Applications/SFM.app
version=1.14.4
digest=51b9ab52e5bc7ef6058ff35fba1309fbc2c4a3241762eca1ad7e490cd7678294
installed_version() {
    /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' "$app/Contents/Info.plist"
}
compatible() {
    /usr/bin/awk -v installed="$1" -v wanted="$version" 'BEGIN {
        split(installed, a, "."); split(wanted, b, ".");
        for (i=1; i<=3; i++) {
            if (a[i]+0 > b[i]+0) exit 0;
            if (a[i]+0 < b[i]+0) exit 1;
        }
    }'
}

if [[ -d $app ]] && compatible "$(installed_version)"; then
    echo "SFM $(installed_version) is already installed."
else
    work=$(/usr/bin/mktemp -d)
    trap 'rm -rf "$work"' EXIT
    package="$work/SFM.pkg"
    /usr/bin/curl --fail --show-error --location --retry 3 \
        "https://github.com/SagerNet/sing-box/releases/download/v$version/SFM-$version-Universal.pkg" -o "$package"
    (cd "$work" && printf '%s  SFM.pkg\n' "$digest" | /usr/bin/shasum -a 256 -c -)
    /usr/sbin/pkgutil --check-signature "$package"
    /usr/bin/sudo /usr/sbin/installer -pkg "$package" -target /
fi

/usr/bin/codesign --verify --strict -R='anchor apple generic and identifier "io.nekohasekai.sfamt.standalone" and certificate leaf[subject.OU] = "P8XK3KHB48"' "$app"
echo "SFM $(installed_version) is ready."
if [[ $launch == true ]]; then /usr/bin/open "$app"; fi
cat <<'NEXT'

If this Mac already has its working profile, select it in SFM and connect.
On a new Mac:
  1. In your dashboard, add this Mac as a device and download its sing-box JSON.
  2. In SFM, choose Profiles → New Profile → Import from File. Select the JSON and save.
  3. Start the profile. Approve the system extension and VPN configuration when macOS asks.
NEXT
