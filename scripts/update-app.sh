#!/usr/bin/env bash
# update-app.sh — Hub frissítés git pull után.
#
# Egy paranccsal: pull, deps frissít ha kell, alembic migrate, restart, healthcheck.
# Hibára rollback előző commitra (a service-ek nem maradnak rossz állapotban).

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "HIBA: ezt a scriptet root-ként kell futtatni: sudo $0" >&2
    exit 1
fi

HUB_DIR="${HUB_DIR:-/opt/hub/app}"
VENV_DIR="${VENV_DIR:-/opt/hub/venv}"

cd "$HUB_DIR"

echo "▸ [1/6] git pull..."
PREV_COMMIT=$(sudo -u hub git -C "$HUB_DIR" rev-parse HEAD)
sudo -u hub git -C "$HUB_DIR" pull --ff-only

NEW_COMMIT=$(sudo -u hub git -C "$HUB_DIR" rev-parse HEAD)
if [[ "$PREV_COMMIT" == "$NEW_COMMIT" ]]; then
    echo "  → már naprakész ($NEW_COMMIT)."
    exit 0
fi
echo "  → $PREV_COMMIT → $NEW_COMMIT"

# Hibára rollback és service-restart
rollback() {
    echo "✗ HIBA — rollback előző commitra: $PREV_COMMIT"
    sudo -u hub git -C "$HUB_DIR" reset --hard "$PREV_COMMIT"
    systemctl restart hub.service hub-worker.service || true
    exit 1
}
trap rollback ERR

echo "▸ [2/6] pip install (ha változott)..."
# Mindig próbálkozunk reinstall-lal — gyors ha nincs változás
sudo -u hub "$VENV_DIR/bin/pip" install --quiet -e "$HUB_DIR[email,worker]"

echo "▸ [3/6] alembic migráció..."
sudo -u hub "$VENV_DIR/bin/alembic" upgrade head

echo "▸ [4/6] hub.service restart..."
systemctl restart hub.service

echo "▸ [5/6] hub-worker.service restart..."
systemctl restart hub-worker.service

echo "▸ [6/6] healthcheck..."
sleep 3
for i in 1 2 3 4 5; do
    if curl -fsS http://127.0.0.1:8080/health >/dev/null; then
        echo "  → /health: OK"
        trap - ERR
        echo ""
        echo "✅ Frissítés sikeres ($PREV_COMMIT → $NEW_COMMIT)"
        exit 0
    fi
    echo "  → /health: várakozás ($i/5)..."
    sleep 2
done

echo "  → /health: NEM válaszol 5 próba után — rollback" >&2
rollback
