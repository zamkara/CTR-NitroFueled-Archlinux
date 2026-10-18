#!/usr/bin/env bash
# Clean Arch container: no compiler, source checkout, game dump or bundled GPU drivers.
set -euo pipefail
pacman -Syu --noconfirm --needed xorg-server-xvfb xorg-xauth ttf-dejavu dbus
mapfile -t packages < <(printf '%s\n' /release/ctr-nitrofueled-*-x86_64.pkg.tar.zst)
[[ ${#packages[@]} == 1 && -f ${packages[0]} ]]
# Official minimal Arch images omit documentation via NoExtract. Whitelist only
# this package's documentation, including its parent directory, inside this container.
# Later inverted patterns override earlier exclusions; retain hosts/resolv.conf exclusions.
printf '\n[options]\nNoExtract = !usr/share/doc/ !usr/share/doc/ctr-nitrofueled/ !usr/share/doc/ctr-nitrofueled/*\n' >> /etc/pacman.conf
pacman -U --noconfirm "${packages[0]}"
[[ -s /usr/share/doc/ctr-nitrofueled/README.md ]]
for binary in /usr/lib/ctr-nitrofueled/bin/sacredfire /usr/lib/ctr-nitrofueled/bin/bb-gpu-capabilities /usr/lib/ctr-nitrofueled/bin/gpu/libbbgpu.so; do
    output=$(ldd "$binary")
    printf '%s\n' "$output"
    if grep -q 'not found' <<< "$output"; then exit 1; fi
done
python -c 'import gi; gi.require_version("Gtk", "4.0"); gi.require_version("Adw", "1"); from gi.repository import Gtk, Adw'
python - <<'PYINFO'
import json,pathlib,re
info=json.loads(pathlib.Path('/usr/lib/ctr-nitrofueled/build-info.json').read_text())
assert re.fullmatch(r'[0-9a-f]{40}',info['commit'])
assert info['package_version']
print('Native build identity:',info['commit'],info['package_version'])
PYINFO
mkdir -p /tmp/runtime-user
export BB_GPU_USER_DIR=/tmp/runtime-user
set +e
/usr/lib/ctr-nitrofueled/bin/sacredfire > /tmp/runtime-usage.log 2>&1
runtime_status=$?
set -e
cat /tmp/runtime-usage.log
[[ $runtime_status == 1 ]]
grep -q 'Usage:' /tmp/runtime-usage.log
unset BB_GPU_USER_DIR
useradd -m player
work=$(mktemp -d)
chown player:player "$work"
set +e
runuser -u player -- env HOME=/home/player XDG_DATA_HOME="$work/data" XDG_CONFIG_HOME="$work/config" \
    dbus-run-session -- xvfb-run -a timeout 15 /usr/bin/ctr-nitrofueled > "$work/launcher.log" 2>&1
status=$?
set -e
cat "$work/launcher.log"
[[ $status == 124 ]] || { echo "Launcher exited unexpectedly: $status" >&2; exit 1; }
if grep -Eq 'Traceback|ImportError|ModuleNotFoundError' "$work/launcher.log"; then exit 1; fi
[[ -d $work/data/ctr-nitrofueled ]]
pacman -Qkk ctr-nitrofueled
pacman -R --noconfirm ctr-nitrofueled
[[ ! -e /usr/bin/ctr-nitrofueled && ! -e /usr/lib/ctr-nitrofueled ]]
[[ -d $work/data/ctr-nitrofueled ]] # Uninstall preserves user data.
echo 'PASS: native package installed, launcher stayed open as an unprivileged user, uninstall preserved data.'
