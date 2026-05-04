#!/usr/bin/env bash
# setup-app.sh — Hub app telepítése (venv, .env, alembic, systemd, nginx).
#
# Előfeltétel:
#   1) install-prereqs.sh már lefutott
#   2) a repó klónozva van a /opt/hub/app (HUB_DIR) alá
#
# Idempotens: többszöri futtatás nem törik el. Root-ként kell futtatni.

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
    echo "HIBA: ezt a scriptet root-ként kell futtatni: sudo $0" >&2
    exit 1
fi

HUB_DIR="${HUB_DIR:-/opt/hub/app}"
VENV_DIR="${VENV_DIR:-/opt/hub/venv}"
DATA_DIR="${DATA_DIR:-/opt/hub/data}"
UPLOAD_DIR="${UPLOAD_DIR:-/opt/hub/uploads}"
ENV_FILE="${ENV_FILE:-/opt/hub/.env}"
PYTHON_BIN="${PYTHON_BIN:-/usr/bin/python3.12}"

if [[ ! -d "$HUB_DIR" ]]; then
    echo "HIBA: $HUB_DIR nem létezik. Klónozd először:" >&2
    echo "  sudo -u hub git clone https://github.com/gaberun24/hub.printbt.local.git $HUB_DIR" >&2
    exit 1
fi

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "HIBA: $PYTHON_BIN nem található. Futott az install-prereqs.sh?" >&2
    exit 1
fi

# A hub user által írható mappák
chown -R hub:hub "$DATA_DIR" "$UPLOAD_DIR" "$HUB_DIR"

# ─── 1) venv létrehozás ────────────────────────────────────────
echo "▸ [1/7] venv létrehozás $VENV_DIR-ben..."
if [[ ! -d "$VENV_DIR" ]]; then
    sudo -u hub "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
sudo -u hub "$VENV_DIR/bin/pip" install --upgrade --quiet pip wheel setuptools

# ─── 2) Python függőségek ──────────────────────────────────────
echo "▸ [2/7] Python függőségek telepítése (~2-3 perc)..."
sudo -u hub "$VENV_DIR/bin/pip" install --quiet -e "$HUB_DIR[email,worker]"

# ─── 3) .env fájl ──────────────────────────────────────────────
echo "▸ [3/7] .env konfig..."
if [[ ! -f "$ENV_FILE" ]]; then
    SECRET_KEY=$("$PYTHON_BIN" -c 'import secrets; print(secrets.token_urlsafe(48))')
    cat > "$ENV_FILE" <<EOF
# Hub konfiguráció — production
# Generálva: $(date -Iseconds)

SECRET_KEY=$SECRET_KEY
BASE_URL=http://hub.printbt.local
SECURE_COOKIES=false
SESSION_LIFETIME_DAYS=60

DATABASE_URL=sqlite:///$DATA_DIR/hub.db
UPLOAD_DIR=$UPLOAD_DIR
COREL_PREVIEW_DIR=$UPLOAD_DIR/corel-previews

# Töltsd ki:
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
IMAP_POLL_INTERVAL_SEC=60

SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
EOF
    chown hub:hub "$ENV_FILE"
    chmod 640 "$ENV_FILE"
    echo "  → $ENV_FILE létrehozva (random SECRET_KEY-jel)"
else
    echo "  → $ENV_FILE már létezik, nem írom felül"
fi

# ─── 4) Alembic migráció ───────────────────────────────────────
echo "▸ [4/7] DB séma migrálás..."
cd "$HUB_DIR"
sudo -u hub "$VENV_DIR/bin/alembic" upgrade head

# ─── 5) systemd unit-ok ────────────────────────────────────────
echo "▸ [5/7] systemd unit-ok..."
install -m 644 "$HUB_DIR/scripts/systemd/hub.service" /etc/systemd/system/hub.service
install -m 644 "$HUB_DIR/scripts/systemd/hub-worker.service" /etc/systemd/system/hub-worker.service
systemctl daemon-reload
systemctl enable hub.service hub-worker.service >/dev/null

# ─── 6) nginx site ─────────────────────────────────────────────
echo "▸ [6/7] nginx site..."
install -m 644 "$HUB_DIR/scripts/nginx/hub.conf" /etc/nginx/sites-available/hub.conf
ln -sf /etc/nginx/sites-available/hub.conf /etc/nginx/sites-enabled/hub.conf
# A default site-ot kivesszük (különben az HTTP root oda megy)
rm -f /etc/nginx/sites-enabled/default
if ! nginx -t; then
    echo "HIBA: nginx config invalid — javítsd a /etc/nginx/sites-available/hub.conf-ot" >&2
    exit 1
fi
systemctl reload nginx

# ─── 7) Service-ek indítás ─────────────────────────────────────
echo "▸ [7/7] Service-ek indítás..."
systemctl restart hub.service hub-worker.service

# Healthcheck
sleep 2
if curl -fsS http://127.0.0.1:8080/health >/dev/null; then
    echo "  → /health: OK"
else
    echo "  → /health: NEM válaszol — ellenőrizd: journalctl -u hub.service -n 50" >&2
fi

cat <<EOF

✅ Hub telepítve.

┌─────────────────────────────────────────────────────────────────┐
│ 1) Első admin létrehozása:                                      │
│                                                                 │
│   sudo -u hub $VENV_DIR/bin/hub create-admin \\
│       --name "Gábor" --email gabor@example.com                  │
│                                                                 │
│ 2) Hozzáférés a böngészőből:                                    │
│                                                                 │
│   http://$(hostname -I | awk '{print $1}')                      │
│   http://hub.printbt.local  (ha a DNS / /etc/hosts beállítva)   │
│                                                                 │
│ 3) Logok és státusz:                                            │
│                                                                 │
│   systemctl status hub.service hub-worker.service               │
│   journalctl -u hub.service -f                                  │
│   journalctl -u hub-worker.service -f                           │
│                                                                 │
│ 4) Frissítés (git pull után):                                   │
│                                                                 │
│   sudo bash $HUB_DIR/scripts/update-app.sh                      │
└─────────────────────────────────────────────────────────────────┘

EOF
