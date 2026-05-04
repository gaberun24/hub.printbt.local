#!/usr/bin/env bash
# Hub előfeltételek telepítése — Debian 12 (Proxmox LXC) vagy Ubuntu 24.04 LTS.
#
# Idempotens: többszöri futtatás nem törik el. Root-ként kell futtatni.
#
# Futtatás:
#   sudo bash scripts/install-prereqs.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "HIBA: ezt a scriptet root-ként kell futtatni: sudo $0" >&2
    exit 1
fi

echo "=== Hub előfeltételek telepítése ==="

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends \
  python3.12 python3.12-venv python3.12-dev python3-pip \
  build-essential pkg-config \
  libffi-dev libssl-dev \
  libpango-1.0-0 libpangoft2-1.0-0 libcairo2 libgdk-pixbuf-2.0-0 \
  libharfbuzz0b libxml2 libxslt1.1 \
  fonts-liberation fonts-dejavu \
  nginx \
  sqlite3 \
  avahi-daemon \
  clamav clamav-daemon clamav-freshclam \
  restic \
  curl wget git ca-certificates

# ── Hub rendszeruser ──
if ! id hub &>/dev/null; then
  useradd --system --shell /usr/sbin/nologin --home /opt/hub hub
  echo "hub user létrehozva"
fi

# Csak a stabil mappákat hozzuk létre. Az /opt/hub/app a klónozás
# célja (ne legyen előre), az /opt/hub/venv-et a setup-app.sh készíti.
# Ha most előre létrehoznánk az `app` mappát, a `mv /tmp/hub-bootstrap
# /opt/hub/app` parancs a forrást a meglévő mappa ALÁ tenné — confusing.
install -d -o hub -g hub -m 755 /opt/hub
install -d -o hub -g hub -m 755 /opt/hub/data
install -d -o hub -g hub -m 755 /opt/hub/uploads

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

# ── GitHub CLI (gh) — privát repo eléréshez ──
if ! command -v gh &>/dev/null; then
    echo "GitHub CLI telepítés..."
    install -d -m 755 /etc/apt/keyrings
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
    chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list
    apt-get update
    apt-get install -y gh
fi

echo ""
echo "=== Kész! ==="
echo "Következő lépés: bash /opt/hub/app/scripts/setup-app.sh"
