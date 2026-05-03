# Műhely

> Belső munkakövető rendszer a Gyorsnyomdához / PrintBT-hez és a Composit Studióhoz. Ügyfélmunkák felvételétől az átadásig: ki vette fel, ki tervezi, melyik gépen készül, mikor lesz kész.

> **Munkanév:** `Műhely`. Alternatívák: `Pipeline`, `Munkanapló`, `Folyam`. Lecserélhető bármikor (csak a domain és a service-nevek függenek tőle).

---

## Cél és scope

**Cél:** kiváltani az Excel + papír kombót egy olyan webes felülettel ahol minden munka digitálisan követhető, az ügyféltér és a műhely ugyanazt látja, és a látványterv-printeket egy okos A4-es munkalap váltja ki.

**Scope IGEN:**

- Munkák felvétele 4 csatornán (személyesen, email, műhelybe behozott B2B, telefon)
- Grafikus pipeline (felvétel → tervezés → kész látvány → műhely → kész → átadva)
- Műhelyi feladatok gép- és típus-szerinti szűréssel
- Email-fiókok (3 grafikus + 1 közös) IMAP-os pollozása, Gemini-alapú előszűrés
- Árajánlat-kezelés shared inbox lockkal (Gábor, édesapa, Kinga)
- A4-es munkalap automatikus PDF-generálás CorelDRAW makró integrációval
- Ügyfél (retail / reseller) törzsadat
- Multi-role user (egy ember több szerepkörrel)

**Scope NEM:**

- Számlázás, készletkezelés, anyagigény (külön rendszerek; a fogyásokat a Rendelő tracker oldja meg)
- Ügyfélportál (az ügyfél nem lát státuszt, nem tölt fel fájlt, mockupot nem hagy jóvá)
- Kapacitástervezés / gép-foglalási naptár (most még nem)
- Pénzügyi nyilvántartás (az ár csak referencia-mező, nem számlázunk)

---

## Stack

A Rendelő mintáját követjük, hogy a deploy és az ops konzisztens legyen.

- **Backend:** FastAPI + Uvicorn
- **DB:** SQLite (WAL módban) — külön DB fájl, nem közös a Rendelővel
- **Frontend:** Jinja2 templates + htmx (CDN, nincs build pipeline)
- **Auth:** közös `shared_auth` modul (a Rendelő auth-ját kiemelve), session cookie + argon2id, közös user tábla mindkét app számára
- **Email:** IMAP (`imap_tools` lib), Gemini API a klasszifikációhoz (`gemini-2.5-flash`)
- **PDF generátor:** WeasyPrint (HTML+CSS → A4 PDF)
- **Worker:** külön systemd service (IMAP polling + file watcher Corel preview-khez)
- **Notifikáció:** in-page toast + Web Audio ding élőben (htmx polling vagy SSE)
- **Deploy:** ugyanaz az Ubuntu Server VM mint a Rendelő, külön systemd unit, külön nginx site
- **Domain:** `muhely.printbt.hu` (vagy `studio.printbt.hu`)
- **Tárhely:** meglévő storage szerver mappákban (UNC/SMB path mezőként a DB-ben)

---

## Adatmodell

### `users` (közös a `shared_auth` modulon át)

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `name` | TEXT | |
| `email` | TEXT UNIQUE | |
| `password_hash` | TEXT | argon2id |
| `is_intake` | BOOL | felvevő |
| `is_designer` | BOOL | grafikus |
| `is_workshop` | BOOL | műhelyes |
| `is_quote_handler` | BOOL | árajánlat-kezelő |
| `is_admin` | BOOL | rendszergazda |
| `active` | BOOL | |
| `created_at` | TIMESTAMP | |

**Megjegyzés:** egy user egyszerre több role flag-et viselhet. Pl. Gábor mind az 5-öt; egy vasalós kolléga csak `is_workshop`-ot.

### `customers`

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `name` | TEXT | |
| `email` | TEXT INDEX | a feladó cím alapján match-elünk inbox emaileket |
| `phone` | TEXT | |
| `customer_type` | ENUM | `retail` \| `reseller` |
| `discount_pct` | DECIMAL(5,2) | reseller esetén tipikus, retail-nél NULL/0 |
| `notes` | TEXT | |
| `created_at` | TIMESTAMP | |
| `created_by_user_id` | FK | |

### `jobs`

A munkalap fő entitása. Egy ügyfél-megrendelés egy Job, akkor is ha több gépen készül.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | belső |
| `public_id` | VARCHAR(8) UNIQUE | a 6-karakteres azonosító, később bővíthető |
| `customer_id` | FK | |
| `intake_user_id` | FK | ki vette fel |
| `intake_channel` | ENUM | `personal` \| `email` \| `workshop_dropoff` \| `phone` |
| `source_email_id` | FK NULL | ha emailből jött, az `incoming_emails` rekord |
| `assigned_designer_id` | FK NULL | NULL = közös poolban |
| `deadline` | TIMESTAMP | dátum + óra + perc, kötelező |
| `is_urgent` | BOOL | piros stempli az A4-en |
| `price_huf` | INT NULL | csak referencia, nem számlázunk |
| `description` | TEXT | grafikai utasítás, anyag, méret, hőfok stb. |
| `source_file_path` | TEXT | UNC/SMB elérési út a storage szerveren |
| `status` | ENUM | lásd lejjebb |
| `notes` | TEXT | belső megjegyzés |
| `created_at` | TIMESTAMP | |
| `closed_at` | TIMESTAMP NULL | |

### `job_tasks`

Egy Job 1+ task-ból áll. Egy task = egy gyártási lépés egy géppel/típussal. Pl. egy „bögre+póló" rendelés 2 task; egy gravírozott fa 1 task.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `job_id` | FK | |
| `task_type` | ENUM | `uv_print`, `co2_laser`, `fiber_laser`, `dtf_print`, `dtf_press`, `mug_press`, `engrave_manual`, `stamp`, `business_card`, `sticker`, `large_format`, `other` |
| `assigned_to_user_id` | FK NULL | NULL = bárki felveheti |
| `status` | ENUM | `pending`, `in_progress`, `done` |
| `instructions` | TEXT | task-specifikus utasítás (hőfok, idő, nyomás, stb.) |
| `quantity` | INT | darabszám |
| `created_at` | TIMESTAMP | |
| `completed_at` | TIMESTAMP NULL | |

### `job_attachments`

Egy Job-hoz tartozó fájlok: forrásfájlok és Corel-macro által generált preview PNG-k.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `job_id` | FK | |
| `kind` | ENUM | `source` \| `preview` |
| `filename` | TEXT | |
| `file_path` | TEXT | abszolút útvonal a storage-on |
| `page_index` | INT NULL | preview esetén többoldalas Corel doc oldalszáma |
| `uploaded_at` | TIMESTAMP | |

### `email_accounts`

A 4 IMAP fiók konfigja.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `email` | TEXT | pl. `gyorsnyomda@printbt.hu` |
| `imap_host`, `imap_port`, `imap_user`, `imap_password_encrypted` | TEXT/INT | |
| `default_assigned_user_id` | FK NULL | ha `gyorsnyomda@` → srác1; ha `info@` → NULL (közös pool) |
| `last_polled_at` | TIMESTAMP | |
| `active` | BOOL | |

### `incoming_emails`

Minden bejövő mail egy rekord, függetlenül attól hogy munka lesz-e belőle.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `account_id` | FK | melyik fiókba érkezett |
| `message_id` | TEXT UNIQUE | RFC822 Message-ID, idempotencia |
| `from_email`, `from_name` | TEXT | |
| `to_email` | TEXT | |
| `subject`, `body_text`, `body_html` | TEXT | |
| `received_at` | TIMESTAMP | |
| `gemini_category` | ENUM | `work` \| `quote_request` \| `spam` \| `other` |
| `gemini_confidence` | FLOAT | 0.0–1.0 |
| `gemini_summary` | TEXT | 1 mondatos magyar összefoglaló |
| `customer_id` | FK NULL | ha matched a feladó cím |
| `status` | ENUM | `inbox` \| `converted_to_job` \| `dismissed` \| `spam_purged` |
| `converted_job_id` | FK NULL | ha lett belőle Job |
| `assigned_user_id` | FK NULL | a fiók default-ja vagy közös pool |
| `locked_by_user_id` | FK NULL | ki vette épp magához (5 perc) |
| `locked_at` | TIMESTAMP NULL | |
| `manual_category_override` | ENUM NULL | ha manuálisan átsorolták |

### `email_attachments`

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `email_id` | FK | |
| `filename`, `mime_type`, `size_bytes` | | |
| `file_path` | TEXT | mentett másolat a storage-on (`inbox/YYYY-MM-DD/feladó/...`) |

### `audit_log`

Státusz-átléptetések minimum.

| Mező | Típus | Megjegyzés |
|------|-------|------------|
| `id` | INT PK | |
| `entity_type` | ENUM | `job` \| `task` \| `email` |
| `entity_id` | INT | |
| `action` | TEXT | pl. `status_change`, `assign`, `convert_to_job` |
| `old_value`, `new_value` | TEXT | |
| `user_id` | FK | |
| `at` | TIMESTAMP | |

---

## Public ID generálás

- **Karakterkészlet:** `ABCDEFGHJKMNPQRSTVWXYZ23456789` (kihagyva: `0/O`, `1/I/L`, `U`, `?`)
- **Hossz:** 6 karakter alapból (`30^6 ≈ 729 millió kombináció`)
- **Generálás:** crypto-random, ütközés esetén retry (max 5x), utána +1 karakterre hosszabbít
- **Megjelenítés:** `XXX-XXX` tagolva (pl. `K7M-2X9`), backend kötőjel nélkül tárolja, kereső mindkettőt elfogadja
- **A4-en:** monospace, ~36pt, bal felső sarok

---

## Státusz életciklus

### Job státuszok

```
felvett ──► grafikán ──► kész_látvány ──► [ügyfél_jóváhagyás_vár] ──► műhelyben ──► kész ──► átadva
                                                                                       │
                                                                                       └──► visszahivva (ha ügyfél nem jön át)
```

- **`felvett`:** új Job, még nincs hozzárendelt grafikus VAGY van de még nem nyúlt hozzá
- **`grafikán`:** grafikus dolgozik rajta
- **`kész_látvány`:** Corel makró exportálta a preview-t, kész a nyomtatható A4
- **`ügyfél_jóváhagyás_vár`:** opcionális, csak ha kell mockup-egyeztetés
- **`műhelyben`:** legalább 1 task aktív
- **`kész`:** minden task `done`
- **`átadva`:** ügyfél elvitte / kiszállítva

### Task státuszok

```
pending ──► in_progress ──► done
```

Egy Job akkor lép `kész` állapotba, amikor minden task-ja `done`.

### Audit

Minden státusz-átlépés `audit_log`-ba megy: ki, mikor, miről mire. Job-nézeten timeline-szerűen látszik.

---

## Szerepkörök és menü

A user role flagjei alapján a menü dinamikusan jelenik meg.

| Role | Mit lát |
|------|---------|
| `is_intake` | „Új munka", saját felvett munkák listája |
| `is_designer` | „Saját munkáim" + „Közös pool" + email inbox (saját fiók) |
| `is_workshop` | „Műhely" task-listák gép szerint szűrve, „Készre jelentés" gomb |
| `is_quote_handler` | „Árajánlat tab" (közös shared inbox 3 főnek) |
| `is_admin` | minden + user, ügyfél, email-fiók, beállítás kezelés |

**Konkrét eloszlás:**

- **Gábor:** mind az 5 (saját VM, saját rendszer)
- **Édesapa, Kinga:** `is_quote_handler` (+ ami még kell)
- **3 grafikus srác:** `is_intake` + `is_designer`
- **Vasalós + gépkezelő kollégák:** `is_workshop`

---

## Munkafolyamatok

### 1) Új munka felvétele (személyesen vagy telefonon)

1. Grafikus a UI-on `Új munka` gombot nyom
2. Ügyfél kiválasztása (autocomplete név/email/telefon alapján) vagy új ügyfél létrehozása inline
3. Kitölti: leírás, határidő (dátum + óra:perc), ár (opcionális), task-ok (típus + darabszám) hozzáadása
4. Választás: **„Én csinálom"** (alapértelmezett) vagy **„Közös pool"** (jelölőnégyzet)
5. Mentés → Job létrejön `felvett` státusszal, kap egy 6-karakteres `public_id`-t
6. Grafikus megnyitja a forrásfájlt (Corel, Illustrator, stb.), kreatív munka a meglévő storage-mappában

### 2) Email beérkezés és előszűrés

**Worker process** (külön systemd service, `muhely-worker.service`):

1. Percenként IMAP-on lehúzza az új mailt mind a 4 fiókból (asyncio párhuzamos)
2. Csatolmányokat lement a storage-ra: `inbox/YYYY-MM-DD/feladó-email/`
3. Minden új mailre Gemini hívás (`gemini-2.5-flash`):
   - Input: feladó, subject, body első 2000 karaktere, csatolmányok neve+típusa, ismert ügyfél-e flag
   - Output: JSON `{kategória, biztosság, összefoglaló, ügyfél_jellegű}`
4. **Felülbírálás:** ha a feladó ismert ügyfél (`customers.email` match) → kategória `work` (felülírja a Gemini-t)
5. **Csatolmány-jel:** ha PDF/AI/EPS/PNG/JPG csatolmány van → erős jel hogy munka, prompt ezt is kapja
6. `incoming_emails` rekord mentése, `assigned_user_id` a fiók default-ja alapján
7. Élő frissítés: a célzott user toast notification-t kap (htmx polling vagy SSE)

**UI az inbox-on:**

- **4 tab:** `Munka` (default megnyitás), `Árajánlat`, `Egyéb`, `Spam`
- Spam tabnál 7 nap után auto-purge (csak a `incoming_emails` rekord törlődik, a fizikai fájlok megmaradnak — eredeti emailt fontos megtartani)
- Manuális áthúzás más tabra → `manual_category_override` mezőbe kerül (későbbi finomhangoláshoz)
- **„Munkává alakítás"** gomb a Munka tabon: prefilled Job form (ügyfél, leírás = subject + body, csatolmány elérési út → `source_file_path`), grafikus kitölti a határidőt + árat + task-okat

### 3) Grafikus pool

- Minden grafikus saját nézete: „Saját munkáim" (státusz-csoportokba szedve)
- Közös pool nézet: minden Job ahol `assigned_designer_id IS NULL`
- **„Felveszem"** gomb: magához rendeli, `assigned_designer_id` saját
- A műhely is direkt felvehet a poolból ha grafika nem kell (pl. előre kész fájllal jön az ügyfél)

### 4) CorelDRAW makró + preview generálás

**A makró (VBA, telepítve mind a 3 grafikus gépére):**

1. Custom toolbar gomb (és/vagy F12 hotkey)
2. Felugrik kis dialógus: „Munka azonosító:" mező
3. Beírod/bemásolod a 6 karakteres ID-t (kötőjellel vagy anélkül)
4. A makró az aktív dokumentum minden oldalát PNG-be exportálja, 200 DPI-n
5. Mentés egy közös hálózati mappába: `\\storage\muhely-previews\K7M2X9_1.png`, `_2.png`, …
6. Confirm dialógus, makró bezárul

**A watcher (worker process):**

1. `inotify` (Linux) vagy `watchdog` lib figyeli a `\\storage\muhely-previews\` mappát
2. Új PNG fájl: parse-olja a fájlnévből az ID-t és oldalszámot
3. `job_attachments` rekord létrehozása (`kind=preview`, `page_index=N`)
4. Ha még nem volt preview: Job státusza `kész_látvány`-ra megy
5. Toast notification a műhely-pool nézeten: „Új kész látvány: K7M-2X9"

**Fallback:** drag-drop zóna a Job nézeten belül, ha valamiért a makró nem megy.

### 5) A4 munkalap PDF generálás

**Generálás:** WeasyPrint, `templates/job_sheet.html` Jinja2 sablonból. A „Munkalap nyomtatás" gomb a Job nézetben.

**Layout (egy Job = 1+N lap, ahol N a preview-k száma):**

```
┌─────────────────────────────────────────────────────────────────┐
│  K7M-2X9                       Pelikán Kft. / +36 30 123 4567   │
│  (36pt monospace)              gabor@pelikan.hu                  │
│                                                                  │
│                                ┌─────────────────────┐           │
│                                │ HATÁRIDŐ            │           │
│                                │ 2026.05.15. P 14:30 │           │
│                                │ ⚠ SÜRGŐS            │           │
│                                │ Ár: 12 500 Ft       │           │
│                                └─────────────────────┘           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│              [LÁTVÁNYTERV PNG, ~140mm magas, keretben]           │
│                                                                  │
├─────────────────────────────────────────────────────────────────┤
│  TASKOK:                                                         │
│  □ DTF nyomtatás (50 db)                                         │
│  □ Vasalás 200°C, 15s, közepes nyomás                            │
│  □ Csomagolás                                                    │
│                                                                  │
│  GRAFIKAI MEGJEGYZÉS:                                            │
│  Gildan Heavy Cotton, fekete, S/M/L vegyesen                     │
│  Mell-méret 28×20 cm, középre                                    │
├─────────────────────────────────────────────────────────────────┤
│  Fájl: \\storage\grafika\karoly\2026\pelikan\K7M2X9.cdr          │
│  Felvette: Károly  •  2026.05.10. 10:32  •  Csatorna: email      │
│                                                                  │
│  Műhely megjegyzés (kézzel): _________________________________   │
└─────────────────────────────────────────────────────────────────┘
```

- **Fejléc (~40 mm):** ID balra, ügyfél középen, határidő+ár jobbra (sürgős esetben piros stempli)
- **Látvány (~140 mm):** preview PNG, keretben, középre
- **Utasítások (~70 mm):** task-checkbox lista, grafikai megjegyzés
- **Lábléc (~25 mm):** fájl elérési út monospace, felvette/dátum/csatorna, üres rubrika kézi jelzéshez

**Több oldal:** ha 2+ preview van (több póló egy fájlban), automatikusan 2., 3. lap generálódik ugyanazzal a fejléc/lábléc-cel, csak a látvány változik. Az utasítás-blokk minden lapon ugyanaz.

### 6) Műhely

**Műhelyes nézet:**

- Felül szűrők: gép-típus checkboxok (UV, CO2, fiber, DTF press, …), státusz (pending / in_progress), határidő-rendezés
- Alul kártya-lista: Job public_id, ügyfél, határidő (sürgős = piros keret), task megnevezés
- **„Megcsinálom"** gomb → `assigned_to_user_id` saját, `status = in_progress`
- **„Kész"** gomb → `status = done`, ha az adott Job minden task-ja kész → Job státusza `kész`-re lép
- A papír A4-et tartja kézben a műhelyes, a webes UI csak a tickeléshez kell — egy közös műhelyes gép vagy tablet elég, nem kell minden gép mellé

### 7) Lezárás és átadás

- Ha minden task `done` → Job `kész`
- Amikor az ügyfél átveszi: `Átadtam` gomb → `átadva` + `closed_at` timestamp
- Egy „Visszahívásra" listán azok a Job-ok, ahol kész már >X napja és nincs átadva (értesítés)

---

## Árajánlat tab — shared inbox

A 3 árajánlat-kezelő (Gábor, édesapa, Kinga) ugyanazt látja, hogy ne válaszoljanak ugyanarra ketten.

**Mechanika:**

- Mail mellett avatar/iniciálé jelzi, ha valaki épp **megnyitotta** (5 perces auto-lock)
- **„Magamhoz veszem"** gomb explicit hozzárendelés: `locked_by_user_id` + `locked_at` set
- Listában mindenki látja, de „Gábornál van" jelzéssel — más nem tudja megnyitni amíg nem fel nem szabadul
- Válasz/elvet után a mail lekerül a listáról, log marad ki intézte
- Élő frissítés htmx + SSE-vel vagy 10–15 mp-es polling-gal

**„AI válasz draft"** gomb (`gemini-2.5-flash`):

- Input: az árajánlat-kérés szövege, ügyfél típusa (retail/reseller), tipikus árazási kontextus (paraméter)
- Output: udvarias visszaigazolás-válasz magyarul
- A user átolvas, módosít, küld (vagy elveti)
- Később, ha a `printbt.hu` redesign élesedik a kalkulátor link automatikus küldésével lecserélhető

---

## Integráció a meglévő infrával

### Közös auth (`shared_auth` modul)

A Rendelő jelenlegi auth logikáját kiemeljük egy közös Python package-be (`shared_auth/`), amit mindkét app `pip install -e ../shared_auth`-szal behúz.

**Mit tartalmaz:**

- `User` modell és session kezelés
- Argon2id hash + verify
- Login/logout view-k és Jinja2 partial-ek
- Meghívásos regisztráció flow
- CLI parancsok (create-admin, generate-invite, list-users)
- Cookie domain konfig (`.printbt.hu`) hogy az SSO működjön

**Migráció:**

1. A Rendelő jelenlegi `app/auth.py`, `app/users.py`, `app/cli.py` releváns részei átkerülnek a `shared_auth/`-ba
2. A Rendelő `pip install -e`-vel hivatkozik rá, kódváltozás minimális
3. A Műhely ugyanezt használja a kezdettől fogva
4. **Közös DB?** Két opció:
   - **(a) Közös user tábla** egy harmadik mini DB-ben (`/opt/shared/users.db`), mindkét app onnan olvas
   - **(b) Külön user tábla** mindkét app-ban, regisztrációkor szinkron HTTP API-n keresztül
   - Javaslat: **(a)** — egyszerűbb, transzparens, minimális overhead

**SSO:**

- Cookie domain `.printbt.hu` → ha a Rendelő is `printbt.hu` aldomain alá költözik (`rendelo.printbt.hu`), egyszer login és minden app-ba be vagyunk lépve
- Ha a Rendelő a `gyorsnyomda.hu` domainen marad, akkor külön login kell — vagy egy redirect-flow-val átadjuk a session-t

### Deploy elrendezés

```
Ubuntu Server VM:
  /opt/rendelo/         ← már megvan
  /opt/muhely/          ← új app
  /opt/shared_auth/     ← közös auth modul (Python package)
  /opt/shared/users.db  ← (opcionális) közös user DB

systemd:
  rendelo.service       (FastAPI, :8001)
  muhely.service        (FastAPI, :8002)
  muhely-worker.service (IMAP poller + Corel watcher)

nginx:
  rendelo.gyorsnyomda.hu  → :8001
  muhely.printbt.hu       → :8002

cron:
  napi backup mindkét DB-ről (sqlite3 .backup) UNAS Pro share-re
  hetente spam-purge (incoming_emails ahol category=spam és received_at < now-7d)
```

---

## Roadmap

### Fázis 0 — Auth refaktor (előkészítés)

- [ ] Rendelő auth-jának kiemelése `shared_auth` package-ba
- [ ] Rendelő átállítása az új közös package-re (regression test)
- [ ] Közös user DB döntés: közös vagy szinkron
- [ ] Cookie domain és SSO setup ha kell

### Fázis 1 — Csontváz

- [ ] FastAPI app + Jinja2 + htmx + SQLite séma
- [ ] `customers`, `users`, `jobs`, `job_tasks`, `audit_log` táblák + migrációk
- [ ] Auth integráció (`shared_auth`)
- [ ] CRUD: ügyfél, Job, JobTask
- [ ] Public ID generátor (collision retry-jal)
- [ ] Státusz-átléptetés UI + audit log

### Fázis 2 — Pool és nézetek

- [ ] „Új munka" form (felvevő nézet)
- [ ] „Saját munkáim" / „Közös pool" / „Műhely" nézetek
- [ ] Multi-role menü dinamika
- [ ] Műhelyes szűrők (gép-típus, státusz, határidő)
- [ ] Toast notifikáció + Web Audio ding (htmx polling)

### Fázis 3 — A4 munkalap és Corel makró

- [ ] WeasyPrint + Jinja2 sablon az A4-hez
- [ ] PDF preview a Job-nézetben + nyomtatás gomb
- [ ] CorelDRAW VBA makró (3 gépre telepítve)
- [ ] File watcher worker (`watchdog` lib) a preview-k beemelésére
- [ ] Multi-page Corel handling (több preview → több A4 lap)
- [ ] Drag-drop fallback PNG feltöltéshez

### Fázis 4 — Email integráció

- [ ] `email_accounts` konfig + admin UI
- [ ] IMAP poller worker (`imap_tools`, asyncio, 4 fiók párhuzamos)
- [ ] Csatolmány-mentés storage-ra
- [ ] Gemini előszűrés (`gemini-2.5-flash`) + `incoming_emails` mentés
- [ ] 4-tab inbox UI (Munka / Árajánlat / Egyéb / Spam)
- [ ] „Munkává alakítás" prefilled form
- [ ] Manuális kategória-felülbírálás (audit-ba mentve)
- [ ] Spam auto-purge cron (7 nap)

### Fázis 5 — Árajánlat shared inbox

- [ ] Shared inbox lock mechanika (locked_by + 5 perc auto-unlock)
- [ ] Élő avatar-jelzés (SSE vagy polling)
- [ ] AI válasz draft gomb (Gemini)
- [ ] Válasz küldés SMTP-vel (vagy mailto: link a felhasználó saját kliensébe)

### Fázis 6 — Csiszolás

- [ ] Keresés régi munkákban (ID, ügyfél, dátumtartomány, státusz)
- [ ] Visszahívandó ügyfelek lista (kész >X napja, nincs átadva)
- [ ] Statisztika dashboard (admin): havi munkaszám, csatorna-eloszlás, átlagos átfutás
- [ ] Discord/JARVIS notifikáció integráció (sürgős munka, ki nem vett pool-elem)
- [ ] Off-site backup automatizálás

---

## Nyitott kérdések

1. **Közös user DB vagy külön + szinkron?** (Fázis 0 előtt eldönteni)
2. **Cookie domain átállás:** Rendelő átköltözik `rendelo.printbt.hu`-ra, vagy marad `gyorsnyomda.hu` és külön login lesz?
3. **A4-en a fájl elérési út rövidítése:** ha a teljes UNC path 100+ karakter, mit vágunk le? Pl. csak az utolsó 2-3 mappa + fájlnév?
4. **Reseller Job-ok csoportosítása:** egyesével külön Job-ok maradnak, vagy később egy „project/batch" entitás alá szervezve havonta gyűjtve? (Számlázáshoz/exporthoz lesz hasznos, ha nem most akkor később.)
5. **Discord/JARVIS notifikáció:** mikor és miért szóljon? (Sürgős határidő közelében? Pool-ban túl régóta lógó munka? Új árajánlat-kérés?)
6. **Reseller kedvezmény:** csak info mező, vagy az ár-mezőhöz is automatikusan alkalmazódik?
7. **Telefonos felvétel:** ugyanaz mint a személyes, vagy külön gyorsbeviteli flow kell?
8. **„Visszahivva" státusz:** tényleg kell, vagy elég ha „kész" marad amíg át nem veszik?

---

## Licenc

Belső projekt, nincs nyilvános licenc.
