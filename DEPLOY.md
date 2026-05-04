# Hub telepítés — Ubuntu 24.04 LTS VM (privát repó)

A Hub-repó privát, ezért `gh` CLI-vel klónozzuk. A telepítés három fázisból áll:

1. **Bootstrap** — `gh` CLI feltelepítése + auth + repó klónozás
2. **Prereqs** — system-szintű függőségek (Python 3.12, nginx, ClamAV, …)
3. **Setup** — app telepítés (venv, `.env`, alembic, systemd, nginx)

Csak a **VM-en** kell futtatni. A VM-en saját userrel SSH-zol be (nem root); a `sudo` jelszót pár lépés bekéri.

---

## 1) Bootstrap — `gh` CLI + privát repó klónozás

Másold be SSH-n egyben (a `gh auth login` interaktívan fog kérdezni):

```bash
# gh CLI hivatalos APT repo
sudo apt-get update
sudo apt-get install -y curl ca-certificates
sudo install -d -m 755 /etc/apt/keyrings
curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | sudo tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
sudo chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | sudo tee /etc/apt/sources.list.d/github-cli.list > /dev/null
sudo apt-get update
sudo apt-get install -y gh

# Hitelesítés — browser flow
gh auth login
#  → GitHub.com
#  → HTTPS
#  → Login with a web browser
#  → másold a 8 jegyű kódot a böngészőbe (https://github.com/login/device)

# Privát repó klónozás ideiglenes helyre
gh repo clone gaberun24/hub.printbt.local /tmp/hub-bootstrap
```

Ha a `gh auth login` kész, és a `gh repo clone` sikeres → kész vagyunk a bootstrap-pel.

---

## 2) Prereqs — system függőségek

```bash
sudo bash /tmp/hub-bootstrap/scripts/install-prereqs.sh
```

Ez ~5-10 percig tart (ClamAV vírusdef letöltés ~250 MB).

A script ezeket teszi:
- Python 3.12 + venv + dev headers
- nginx, sqlite3, avahi-daemon
- ClamAV (clamav-daemon + freshclam, vírusdef letöltve)
- WeasyPrint system deps (libpango, libcairo, …)
- restic (off-site backup-hoz)
- `hub` system user + `/opt/hub` mappa-szerkezet
- gh CLI (idempotens — már telepítve, no-op)

---

## 3) Setup — app

A repót átköltöztetjük a `/opt/hub/app`-ba a `hub` user alá, majd a setup script lefut:

```bash
sudo mv /tmp/hub-bootstrap /opt/hub/app
sudo chown -R hub:hub /opt/hub/app

sudo bash /opt/hub/app/scripts/setup-app.sh
```

Ez a script:
- Készíti a venv-et `/opt/hub/venv`-ben
- Telepíti a Python függőségeket (`[email,worker]` extrákkal)
- Generál egy random `SECRET_KEY`-jű `.env`-et `/opt/hub/.env`-ben
- Lefuttatja az alembic migrációkat → `/opt/hub/data/hub.db`
- Telepíti a systemd unit-okat (`hub.service`, `hub-worker.service`)
- Telepíti az nginx site-ot (port 80)
- Elindítja a service-eket
- `/health` endpoint-ot pingel ellenőrzésnek

A script végén kiírja a következő lépést.

---

## 4) Első admin

```bash
sudo -u hub /opt/hub/venv/bin/hub create-admin \
    --name "Gábor" --email gabor@example.com
# (a jelszót interaktívan, némán kéri — ne add meg --password-dal)
```

---

## 5) Hozzáférés

A VM IP-jéről (a fejlesztő gépen, NEM a VM-en):

```
http://192.168.1.69
```

Ha `hub.printbt.local` URL-en akarod elérni, két opció:

**A. `/etc/hosts` a fejlesztő gépen** (gyors, csak neked):
```
192.168.1.69  hub.printbt.local
```

**B. UniFi router DNS** (mindenkinek a céges hálón):
- UniFi Controller → Settings → Networks → DNS
- Hozzáadás: `hub.printbt.local` → `192.168.1.69`

---

## 6) Frissítés — git pull után

A repó a VM-en a `/opt/hub/app` alatt van, és a `hub` user a tulajdonos.
A frissítés egy paranccsal:

```bash
sudo bash /opt/hub/app/scripts/update-app.sh
```

Ez a script:
1. `git pull --ff-only` (a `hub` user nevében)
2. `pip install -e .[email,worker]` (ha változott a deps)
3. `alembic upgrade head` (ha új migráció)
4. `systemctl restart hub.service hub-worker.service`
5. `/health` endpoint pingelés
6. **Hibára rollback** — visszaáll az előző commitra, és restartolja a service-eket

---

## 7) Logok és hibaelhárítás

```bash
# Élő log (Ctrl+C kilép)
sudo journalctl -u hub.service -f
sudo journalctl -u hub-worker.service -f

# Utolsó 50 sor
sudo journalctl -u hub.service -n 50
sudo journalctl -u hub-worker.service -n 50

# Service státusz
sudo systemctl status hub.service hub-worker.service

# nginx
sudo nginx -t                       # config validálás
sudo systemctl reload nginx
sudo tail -f /var/log/nginx/error.log

# DB shell
sudo -u hub sqlite3 /opt/hub/data/hub.db
```

### Gyakori hibák

| Hiba | Megoldás |
|------|----------|
| `bash: \r: command not found` | Windows-ról CRLF — `dos2unix scripts/*.sh`. A `.gitattributes` ezt megelőzi, de ha mégis: `sed -i 's/\r$//' scripts/*.sh` |
| `gh auth login` 404 / "not found" | Ellenőrizd, hogy a fiókod hozzáfér-e a privát repóhoz. |
| `systemctl status hub.service` failed | `journalctl -u hub.service -n 50` — a leggyakoribb ok a `.env` hibás vagy a Python deps nincsenek telepítve. |
| `/health` 502 | A `hub.service` nem fut a 8080-on. Ellenőrizd a logot. |
| ClamAV nem skennel | `freshclam` még tölti a vírusdef-et. Pár perc, vagy `sudo systemctl restart clamav-daemon`. |

---

## 8) DEV mód (alternatíva — ha nem prod, csak iterálsz)

Ha nem akarod a teljes systemd + nginx + `/opt/hub` setupot, a 2. lépés (`install-prereqs.sh`) után:

```bash
# Repó a saját home-odban
mv /tmp/hub-bootstrap ~/hub
cd ~/hub

# venv + deps
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e '.[email,worker]'

# .env
cp .env.example .env
# Generálj egy SECRET_KEY-t, írd át a .env-ben:
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'

# Migráció + admin
alembic upgrade head
python -m app.cli create-admin --name "Gábor" --email gabor@example.com

# App futtatása (kódváltozásra automatikusan reload)
uvicorn app.main:app --host 0.0.0.0 --port 8080 --reload

# Worker (másik terminálban / tmux split)
python -m app.workers.main
```

Hozzáférés: `http://192.168.1.69:8080`
