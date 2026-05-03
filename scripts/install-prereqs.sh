#!/usr/bin/env bash
# Hub előfeltételek telepítése — Debian 12 (Proxmox LXC)
# Futtatás: bash /tmp/hub-bootstrap/scripts/install-prereqs.sh
set -euo pipefail

echo "=== Hub előfeltételek telepítése ==="

apt-get update
apt-get install -y \
  python3.12 python3.12-venv python3.12-dev \
  nginx \
  sqlite3 \
  avahi-daemon \
  clamav clamav-daemon \
  libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
  libffi-dev libharfbuzz0b libxml2 libxslt1.1 \
  restic \
  curl wget git

# ── Hub rendszeruser ──
if ! id hub &>/dev/null; then
  useradd --system --shell /usr/sbin/nologin --home /opt/hub hub
  echo "hub user létrehozva"
fi

mkdir -p /opt/hub/{app,data,uploads,venv}
chown -R hub:hub /opt/hub

# ── ClamAV konfiguráció ──
echo "ClamAV vírus-definíciók frissítése..."
# freshclam.conf: kommenteld ki az "Example" sort ha még benne van
sed -i 's/^Example/#Example/' /etc/clamav/freshclam.conf 2>/dev/null || true
freshclam || echo "freshclam figyelmeztetés (első futásnál normális)"

# clamd.conf: kommenteld ki az "Example" sort
sed -i 's/^Example/#Example/' /etc/clamav/clamd.conf 2>/dev/null || true

systemctl enable clamav-freshclam
systemctl start clamav-freshclam
systemctl enable clamav-daemon
systemctl start clamav-daemon

echo "ClamAV daemon elindult, socket: /var/run/clamav/clamd.ctl"

# ── Avahi (mDNS) ──
systemctl enable avahi-daemon
systemctl start avahi-daemon

echo ""
echo "=== Kész! ==="
echo "Következő lépés: bash /opt/hub/app/scripts/setup-app.sh"
