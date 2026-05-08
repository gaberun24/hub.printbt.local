# Hub Roadmap

A spec [`README.md`](README.md) §Roadmap szakaszán alapul, fázisokra
bontva. Minden fázis után egy működő, deploy-olható verzió.

> **Aktuális állás:** Fázis 1, 2, 3 (csak A4-PDF), 4 — kész és
> production-on fut a `192.168.1.69` LXC-n. A Rendelő modul a régi
> `nyomda_rendelo` repó **összes** funkcióját átvette (Malfini B2B,
> CSV-importer, archívum, cascade dropdown, live notification).

---

## Fázis 0 — Auth + skeleton ✅

- [x] Repo, FastAPI + SQLAlchemy 2.0 + SQLite (WAL) + Jinja2 + htmx
- [x] argon2id jelszó-hash, server-stored sessionök 60 napos cookie-val
- [x] Login / logout / meghívásos regisztráció flow (`/invite/{token}`)
- [x] CLI: `hub create-admin`, `list-users`, `generate-invite`
- [x] Multi-role flag rendszer (`is_intake`, `is_designer`, `is_workshop`,
      `is_quote_handler`, `is_orderer`, `is_admin`) — egy ember több role
- [x] Sidebar dinamikus (csak a megfelelő role-flagű item-ek látszanak)
- [x] Mockup design (Fraunces + Plus Jakarta Sans + JetBrains Mono,
      paper paletta, vermilion accent)
- [x] Healthcheck endpoint, alap logging
- [ ] LXC bootstrap script (a DEPLOY.md végigvezeti, de install-prereqs.sh
      és setup-app.sh megvan)

## Fázis 1 — Rendelő modul ✅

A régi `nyomda_rendelo` funkcionalitása **TELJES MÉRTÉKBEN** átvéve a
Hub-ba. Adatmigráció **NEM** lett elvégezve — a régi rendszer szépen
kifut, a Hub új igényekkel indul.

- [x] **Adatmodell**: `rendelo_categories`, `rendelo_items`,
      `rendelo_requests`, `rendelo_request_lines`, `rendelo_events`
      (közös DB-ben, `rendelo_*` prefixszel)
- [x] **CRUD**: új igény form, részletek, állapot-átléptetés, kommentek
- [x] **Igény szerkesztés** — csak `new` állapotban, csak felvevő/admin
- [x] **Multi-line igény** + részleges szállítás (qty_ordered/qty_arrived)
- [x] **Kép-csatolmány** (Pillow thumbnail, EXIF auto-rotate, max 1600px,
      Ctrl+V vágólapról beillesztés)
- [x] **Kategória chip-sáv** az aktív igények fölött pulzáló bogyókkal
- [x] **Live notification** (htmx polling 60mp + Web Audio ding + toast)
- [x] **Sidebar count auto-frissülés**
- [x] **Item katalógus** + autocomplete (htmx fetch, suggestions dropdown)
- [x] **CSV bulk-import** (admin UI, dry-run, eredmény-vizualizáció)
- [x] **Archívum** (2 év, dátum-szűrők, hónap-csoportosítás, nyomtatható)
- [x] **Bulk-rendelés export** (`kód;mennyiség` vágólapra)
- [x] **Igény nyomtatás** (a4-szerű @media print stílusokkal)
- [x] **Malfini cascade dropdown** (Pólóhoz: modell→szín swatch→méret)
- [x] **Malfini B2B integráció**:
  - [x] Login + stock-szinkron + admin UI
  - [x] Encrypted credential (Fernet, SECRET_KEY-ből származtatott kulcs)
  - [x] Debug raw-response viewer
  - [x] Kézi „Refresh now" gomb + admin-status
  - [x] **Worker timer** — hétköznap 7-18 helyi idő, fél óránként auto
- [x] **Malfini CSV importer**:
  - [x] `hub import-malfini-pricelist <csv>` — Standard Pricelist
  - [x] `hub import-malfini-variansok <csv>` — saját szűrt CSV
  - [x] Inaktiválja a CSV-ben nem szereplő régi rekordokat
- [x] **CLI**: `hub seed-rendelo-categories` (12 alap-kategória)

## Fázis 2 — Munkák modul ✅

- [x] **Adatmodell**: `jobs_jobs`, `jobs_tasks`, `jobs_attachments`,
      `jobs_events`, `customers` (közös)
- [x] **Public ID** generátor (6 karakter, ütközés-retry, format `XXX-XXX`)
- [x] **Státusz életciklus**: `felvett → grafikán → kész_látvány →
      ügyfél_jóváhagyás_vár → műhelyben → kész → átadva` + `visszahívva`
- [x] **State-machine** explicit `ALLOWED_TRANSITIONS`-szel
- [x] **CRUD**: új munka, részletek, kommentek, idővonal-events
- [x] **Saját munkáim / Közös pool / Mind / Recycle bin** szűrők
- [x] **Műhely nézet** gép-szűrő chipekkel, task-kártyák határidő szerint
- [x] **Task-akciók**: claim / done / release
- [x] **Soft-delete** indoklással + 90 nap retention + restore
- [x] **Toast notifikáció** + Web Audio ding
- [x] **Customer integráció** — ügyfél-választó dropdown, "Új ügyfél" link
- [x] **Customer modell**: legal_type (magán/cég), customer_type
      (vásárló/viszonteladó), tax_number, magyar címszerkezet
      (irányítószám↔város autocomplete)
- [x] **Job-fájlok**: upload (vírusszűrt), download, delete (jogosultság-
      check), AttachmentKind (customer/design/production/other)

## Fázis 3 — A4 munkalap (és Corel makró) ⏳

- [x] **WeasyPrint A4 PDF** — `/sheet/{public_id}/pdf` letöltés
- [x] **Sheet preview** a böngészőben — `/sheet/{public_id}`
- [x] Layout: 56pt monospace public ID, ügyfél, határidő-doboz piros
      sürgős stemplivel, látvány-keret, task-checkbox lista, kézi
      megjegyzés-rubrika
- [ ] **PrintBT logo** a sheet fejlécben (WeasyPrint base_url konfig)
- [ ] **CorelDRAW VBA makró** F12 hotkey, PNG export 200 DPI
- [ ] **File watcher worker** (`watchdog` lib) a `\\storage\hub-previews`
      mappára, automatikus Job-hoz rendelés Public ID alapján
- [ ] **Multi-page Corel handling** (több preview → több A4 lap)
- [ ] **Drag-drop fallback** PNG feltöltéshez

## Fázis 4 — Email integráció ✅

- [x] **email_accounts** tábla + admin UI (`/admin/email-accounts`,
      titkosított `imap_password_encrypted`)
- [x] **IMAP poller worker** (`imap_tools`, asyncio, több fiók)
  - [x] Első poll: utolsó 50 levél (nem csak UNSEEN)
  - [x] Inkrementális: UID > last_poll_uid
  - [x] **3-napos IMAP cleanup** — Hub-ba lehúzott levelek törlése a
        szerverről (limitált tárhely miatt)
- [x] **ClamAV csatolmány-szkennelés** (instream, AppArmor-kompatibilis)
- [x] **AI klasszifikáció** — provider switch admin UI-ról (Gemini /
      Ollama / LM Studio / none), runtime DB-ben titkosított API-kulcs
  - [x] 4-lépcsős pipeline: ismert ügyfél → szállító domain → spam pattern → AI
  - [x] Hard spam patterns („spam", „leiratkoz", „unsubscribe")
  - [x] Cloud-fájlmegosztás (Drive / WeTransfer) → work
  - [x] Csatolmány-fájlnév + HTML body fallback a prompthoz
  - [x] `hub reclassify-emails` CLI (RULE_FALLBACK / `--all`)
- [x] **5-tab inbox** (Munka / Árajánlat / Szállító / Egyéb / Spam +
      Törölt-trash)
- [x] **Manuális kategória-felülbírálás** (audit-ba mentve)
- [x] **Spam auto-purge** (7 nap), **email soft-delete + restore**
- [x] **Szállító emailek** auto-purge (30 nap)
- [x] **Email reply** + **compose** (per-account SMTP credential)
- [x] **„Munkává alakítás"** flow:
  - Customer-match (matched_customer_id vagy from_address)
  - Új ügyfél prefilled-en, ha nincs match
  - Description prefilled (tárgy + AI summary + body)
  - Csatolmányok automatikusan átkerülnek a Job-hoz (kind=customer)
  - IncomingEmail.converted_to_job_id beállítva
- [x] **Karantén admin oldal** — fertőzött / hibás / pending csatolmány
      listával, rescan/delete, bulk-rescan gomb és CLI
      (`hub rescan-attachments`)

## Fázis 5 — Árajánlat shared inbox ❌

- [ ] **Lock mechanika** (locked_by + 5 perc auto-unlock)
- [ ] **Élő avatar-jelzés** (SSE vagy polling — ki nézi most)
- [ ] **AI válasz draft gomb** (Ollama / Gemini)
- [ ] „Magamhoz veszem" explicit hozzárendelés

## Fázis 6 — Készlet modul ❌

- [ ] `stock_items`, `stock_movements`, `job_material_requirements` táblák
- [ ] Item CRUD admin nézet
- [ ] Job-on anyagigény-szerkesztő
- [ ] Hiány-jelző + „Rendelés generál" gomb (Rendelő modulba auto-igény)
- [ ] Befejezéskor automatikus készlet-csökkentés
- [ ] Min-stock alá esés notifikáció
- [ ] Leltár nézet (havi)
- [ ] Bevételezés (kézi vagy Rendelő-igény-lezárásból)

## Fázis 7 — Csiszolás ❌

- [ ] Keresés régi munkákban (ID, ügyfél, dátumtartomány, státusz)
- [ ] Visszahívandó ügyfelek lista (kész >X napja, nincs átadva)
- [ ] Statisztika dashboard (havi munkaszám, csatorna-eloszlás,
      átlagos átfutás, készlet-fogyási trendek)
- [ ] Discord / JARVIS notifikáció
- [ ] PWA telepítés a műhelyes tabletekre
- [ ] Gemini-alapú „heti összefoglaló" jelentés admin-nak

## Háttér-feladatok / Ops

- [x] **install-prereqs.sh** — Ubuntu 24.04 + Debian 12 (LXC) — Python,
      ClamAV, nginx, avahi, gh CLI, restic
- [x] **setup-app.sh** — venv, .env, alembic, systemd unit-ok, nginx site
- [x] **update-app.sh** — git pull + rollback hibára
- [x] **systemd unit-ok** — `hub.service` + `hub-worker.service`
- [x] **DEPLOY.md** — teljes telepítési doku gh auth flow-val
- [ ] **Backup script** (`scripts/backup.sh`) — SQLite `.backup`,
      uploads tarball, Synology + Hetzner restic
- [ ] **PBS (Proxmox Backup Server)** integráció
- [ ] **Restore drill** — havi feladatként
- [ ] **TLS** — `mkcert` self-signed (vagy Let's Encrypt)

## Rendszer-szintű (superadmin) UI ⏳

A README-ben terveztük az `is_superadmin` flag-et és külön
`/system/...` route-okat. **Jelenleg `is_admin`-ként minden integráció
elérhető.** Ha kell finomabb privilégium-szétválasztás, ezt később
visszahozzuk.

- [ ] `is_superadmin` flag tényleges implementálása
- [ ] `/system/email-accounts`, `/system/api-keys`, `/system/storage`,
      `/system/audit-log` külön view-k

---

## Status timeline

| Fázis | Cél | Státusz | Verzió |
|-------|-----|---------|--------|
| 0 | Auth + skeleton | ✅ kész | 0.1.0 |
| 1 | Rendelő modul (full port) | ✅ kész | 0.2.0 |
| 2 | Munkák modul | ✅ kész | 0.3.0 |
| 3 | A4 munkalap | ⏳ A4-PDF kész, Corel makró nem | 0.4.0 |
| 4 | Email integráció | ✅ kész | 0.5.0 |
| 4.1 | Customer public_id + Ollama cloud-fix | ✅ kész | 0.5.1 |
| 5 | Árajánlat shared inbox | tervezett | 0.6.0 |
| 6 | Készlet modul | tervezett | 0.7.0 |
| 7 | Csiszolás | tervezett | 1.0.0 |

A „kész" kritérium minden fázisra: deploy-olva fut a `192.168.1.69`
LXC-n, és a fázis funkciói használhatóak production módban.
