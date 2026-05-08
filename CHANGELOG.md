# Changelog

A jelentős változások verziók szerint csoportosítva. A részletes
git-history ad pontosabb képet — ez egy magas szintű összefoglaló.

A formátumot a [Keep a Changelog](https://keepachangelog.com) ihlette.
Verziózás: szemantikus, fázisokat követve (lásd [`ROADMAP.md`](ROADMAP.md)).

---

## [0.5.1] — 2026-05-08 — Customer azonosító + Ollama cloud-fix

### Hozzáadva

- **`Customer.public_id`** — egyedi 5-karakteres ügyfél-azonosító (XX###
  formátum, 2 betű + 3 szám, kötőjel nélkül; pl. `KM472`). Regisztráláskor
  automatikusan generálódik, az alembic migration retroaktív backfill-t ad
  a meglévő ügyfeleknek.
  - Megjelenítés: customer detail hero, customer list, Job detail
    hero (név mellett mono+bold), A4 munkalap fejléc.
  - Új helper: `generate_unique_customer_public_id()` — 50 retry után
    +1 számjegy fallback (XX####).
- **Generic public_id helper** — `generate_unique_for(db, model_class)`
  a Job-os mintát általánosítja (Customer + jövőbeli rekordtípusokra).

### Javítva

- **Ollama code-fence stripping** — a cloud-modellek (pl.
  `gemma4:31b-cloud`) néha NEM tisztelik a `format: "json"` paramétert
  és markdown ```` ```json ```` blokkba csomagolják a választ. A parser
  most levágja a code-fence-t, mint az LM Studio kliens (eddig az
  Ollama-os JSON-mode garantált válaszra építettünk — ez cloud-on nem
  garancia).

---

## [0.5.0] — 2026-05-05 — Rendelő modul teljes port + Email integráció

A Hub a régi `nyomda_rendelo` repó **összes** funkcionalitását átvette,
és a Munkák modul már email integrációval is működik.

### Hozzáadva

**Rendelő modul** — teljes feature-port:
- Image upload az igényekhez (Pillow thumbnail, EXIF auto-rotate, max
  1600px JPEG, Ctrl+V vágólapról beillesztés)
- Igény szerkesztése (csak `new` állapotban, csak felvevő/admin)
- Bulk-rendelés export (`kód;mennyiség` formátum vágólapra a Malfini
  B2B „Tömeges kosárba helyezés" mezőjéhez)
- CSV bulk-import az item-katalógushoz (admin UI, dry-run, eredmény-
  vizualizáció)
- Archívum nézet (2 év, dátum-szűrők, hónap-csoportosítás, nyomtatható)
- Igény nyomtatás (`@media print` stílusokkal, sidebar/toolbar elrejtve)
- Item katalógus autocomplete (htmx fetch, suggestions dropdown)
- Live notification (htmx polling 60mp + Web Audio ding + toast)
- Sidebar count auto-frissülés
- **Kategória chip-sáv** az aktív igények fölött, pulzáló bogyókkal a
  NEW állapotú kategóriákon
- 12 alap-kategória seed CLI parancs (`hub seed-rendelo-categories`)
- `Item.stock_qty` + `stock_fetched_at` mezők (Malfini stock-szinkronhoz)

**Malfini integráció**:
- B2B API kliens (login, fetch_availabilities, raw debug)
- Stock-szinkron orchestration (refresh_all_stocks)
- Cascade dropdown a Pólóhoz (modell→szín swatch→méret), live stock-jelzés
- Admin UI `/admin/integrations/malfini` — credential save (Fernet
  titkosítva), test connection, kézi refresh, raw debug viewer
- CSV importerek:
  - `hub import-malfini-pricelist <csv>` — Standard Pricelist (~14k sor)
  - `hub import-malfini-variansok <csv>` — saját szűrt CSV (~2.4k variant)
- **Worker timer** — hétköznap 7-18 helyi idő, fél óránként auto-szinkron

**Email integráció**:
- IMAP poller worker (több fiók, első poll utolsó 50 levél, inkrementális
  UID-tracking, 3 napos auto-cleanup a szerverről)
- ClamAV csatolmány-szkennelés (instream, AppArmor-kompatibilis)
- AI klasszifikáció — provider switch admin UI-ról (Gemini / Ollama /
  LM Studio / none), runtime DB-ben titkosított API-kulcs
- 4-lépcsős pipeline: ismert ügyfél → szállító domain → spam pattern → AI
- 5-tab inbox (Munka / Árajánlat / Szállító / Egyéb / Spam) + Trash
- Manuális kategória-felülbírálás
- Spam auto-purge (7 nap), Szállító auto-purge (30 nap)
- Email soft-delete + 7 napos retention + restore
- Email reply + compose (per-account SMTP credential)
- **„Munkává alakítás"** flow — customer-match, prefilled new munka form,
  csatolmányok automatikus átemelése a Job-hoz
- Karantén admin oldal (fertőzött/hibás/pending csatolmány listával,
  rescan/delete, bulk-rescan gomb és `hub rescan-attachments` CLI)
- `hub reclassify-emails` CLI (RULE_FALLBACK / `--all`)

**Munkák modul kibővítés**:
- Job-fájlok upload/download/delete vírusszűrve, jogosultság-check
- AttachmentKind: customer / design / production / preview / source / other
- Soft-delete indoklással + recycle bin (90 nap retention)

**A4 munkalap** (Fázis 3 részleges):
- WeasyPrint-tel PDF letöltés (`/sheet/{public_id}/pdf`)
- Böngészős preview (`/sheet/{public_id}`)
- Layout: 56pt monospace public ID, határidő-doboz piros sürgős
  stemplivel, task-checkbox lista

**Branding**:
- PrintBT logo (login, sidebar, favicon) — dark/light theme `filter:
  invert(1)` automatikus váltással

**Telepítő scriptek**:
- `install-prereqs.sh` — Ubuntu 24.04 + Debian 12 (LXC) — Python 3.12,
  ClamAV, nginx, avahi, gh CLI, restic
- `setup-app.sh` — venv, .env, alembic, systemd unit-ok, nginx site
- `update-app.sh` — git pull + rollback hibára
- systemd unit-ok: `hub.service`, `hub-worker.service`
- `DEPLOY.md` — teljes telepítési doku gh auth flow-val

### Javítva

- DB busy_timeout 5s → 30s (concurrent write-ok lock-ablaka csökkenti
  a "database is locked" hibát)
- Malfini variansok importer: 200-batch commit (a 2400 INSERT egy
  tranzakcióban "database is locked"-be esett)
- Dark theme select option + form-input olvashatóság (color-scheme +
  explicit color)
- Alembic logger override (a `command.upgrade` átírta a root logger-t
  WARN-ra, az INFO log-ok eltűntek a journalctl-ből)
- IMAP poller első poll: utolsó 50 levél (régen csak UNSEEN)
- ClamAV scan_file → scan_stream (instream, AppArmor-kompatibilis)
- IMAP cleanup 3 napnál régebben lehúzott levelek törlése a szerverről
- AI prompt: csatolmány-fájlnevek + HTML body fallback (csak-fájlos
  emailek `work`-be sorolódnak)
- Cloud-fájlmegosztás (Drive / WeTransfer) explicit work-ként a
  system promptban
- Hard spam patterns („spam", „leiratkoz", „unsubscribe") a 3. lépcsőben
- Job-fájl upload jogosultság-check (admin / intake / designer / workshop)
- Job-fájl upload vírusszűrés `scan_bytes`-szal (atomikus reject)
- Customer form: `discount_pct` üres string → int parsing fix
- Inbox törölt emailek tab + 7 napos auto-purge
- Per-account SMTP credential a reply/compose route-okhoz (eddig minden
  válasz a globális `.env` SMTP-n ment ki)
- Admin count query `select(User).all().__len__()` → `func.count()`
- Spam pattern: `nore[p]?ly@` átkerült subject patterns-ből sender
  patterns-be (subject ritkán tartalmaz `@`-et)
- Gemini fallback `classified_by` `RULE_FALLBACK` enum-mal jelölve
  (eddig hamisan `GEMINI`-ként logolt)
- Pyproject WeasyPrint duplikáció megszüntetve

---

## [0.4.0] — 2026-05-04 — Email integráció (Fázis 4-5 első része)

### Hozzáadva

- IMAP poller, Gemini klasszifikáció, csatolmány-mentés
- 4-tab inbox UI
- ClamAV vírusszűrő
- SMTP küldés, válasz, új email compose
- email_account_viewers many-to-many (közös vs viewer-restricted fiókok)
- Avatar-iniciálék + szín testreszabás
- Szállítói email kategória + auto-purge (30 nap)
- IncomingEmail.is_outgoing + sent_by_user_id

---

## [0.3.0] — 2026-05-03 — Munkák modul (Fázis 2)

### Hozzáadva

- Munkák modul DB séma (`jobs_jobs`, `jobs_tasks`, `jobs_attachments`,
  `jobs_events`)
- Public ID generátor (`XXX-XXX` 6 karakter, ütközés-retry)
- State-machine + CRUD + kommentek
- Customer modul (közös tábla — legal_type, customer_type, tax_number,
  magyar címszerkezet, irányítószám↔város autocomplete)
- Új munka flow + jobs-lista (saját / pool / mind / törölt)
- Műhely nézet gép-szűrő chipekkel
- Job soft-delete indoklással + recycle bin

---

## [0.2.0] — 2026-05-03 — Rendelő modul migráció (Fázis 1)

### Hozzáadva

- Rendelő modul tábla-séma (közös DB-ben, `rendelo_*` prefixszel)
- CRUD: új igény form, részletek, állapot-átléptetés, kommentek
- Admin nézetek: kategóriák, tételek, userek, meghívók
- Mockup-faithful UI (Fraunces + Plus Jakarta Sans + JetBrains Mono)

---

## [0.1.0] — 2026-05-03 — Auth + skeleton (Fázis 0)

### Hozzáadva

- FastAPI + SQLAlchemy 2.0 + SQLite + Jinja2 + htmx skeleton
- argon2id auth, server-stored session, meghívásos regisztráció
- Multi-role flag rendszer (6 flag)
- CLI: `hub create-admin`, `list-users`, `generate-invite`
- Közös DB séma: `users`, `customers`, `audit_log`, `notifications`
