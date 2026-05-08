# Hub

> Belső munkakövető, igénykezelő és készletnyilvántartó rendszer a PrintBT / Gyorsnyomda és a Composit Studio számára. Három modul egy alkalmazásban, csak a céges hálón elérhető.

> **Domain:** `hub.printbt.local` (mDNS-en + belső DNS-szel a router szintjén) · **Hozzáférés:** csak céges LAN

---

## Doksik

- 📋 [`ROADMAP.md`](ROADMAP.md) — fázisok és státusz
- 📝 [`CHANGELOG.md`](CHANGELOG.md) — release notes
- 🚀 [`DEPLOY.md`](DEPLOY.md) — telepítési doku (Ubuntu 24.04, gh + setup-app.sh)
- 📜 Részletes UI mockup: `docs/hub_mockup.html` és `docs/muhely_mockup.html`

---

## Cél és scope

**Cél:** kiváltani az Excel + papír kombót egyetlen webes rendszerrel ahol az ügyfélmunkák, a belső anyagigények és a készlet ugyanabban a felületben élnek. Ne három különálló rendszer üzemeljen, hanem egy közös sidebar alatt három fókuszált modul.

A rendszer kizárólag a céges hálón érhető el, nincs publikus URL, nincs Cloudflare Tunnel. Ettől a fenyegetésmodell egyszerű, viszont auth még így is kell (alkalmazottak közt is).

### Modulok

**1. Munkák** — ügyfélmunkák felvételétől az átadásig. Ki vette fel, ki tervezi, melyik gépen készül, mikor lesz kész. Email-fiók-pollozás Gemini-szűréssel, A4 munkalap PDF-generálás, CorelDRAW makró integráció.

**2. Rendelő** — belső igénytracker. Tonerek, papír, laminálófólia, karbantartás. Aki észreveszi hogy fogy, felteszi; aki rendelni szokott, leveszi; mindenki látja az állapotot. (A meglévő `nyomda_rendelo` repo migrálva.)

**3. Készlet** — híd a Munkák és a Rendelő között. Job-ok anyagigénye, készletcsökkenés befejezéskor, automatikus rendelés-generálás a Rendelőbe ha valami a min-stock alá megy. **Nincs pénzügyi rész**: nincs FIFO, átlagár, áfakód, leltárkülönbözet, NAV-bizonylat.

### Scope IGEN

- Munkák: 4 csatornás felvétel, grafikus pipeline, műhelyi taskok gép szerint, A4 munkalap, IMAP poller, Gemini classifier, árajánlat shared inbox
- Rendelő: meglévő funkcionalitás migrálva, közös auth alá
- Készlet: stock_items, anyagigény-jelölés Job-on, auto-rendelés generálás
- Multi-role user (egy ember több szerepkörrel)
- Közös ügyfél-tábla (későbbi printbt.hu redesignhoz is használható)

### Scope NEM

- Számlázás (kézzel, vagy Számlázz.hu API integrációval később, külön projektként)
- Pénzügyi nyilvántartás (ár csak referencia-mező, nem számlázunk)
- Bér- és HR-modul
- Ügyfélportál (az ügyfél nem lát státuszt, nem tölt fel fájlt)
- Kapacitástervezés / gép-foglalási naptár (most még nem)
- Publikus URL, kintről elérés
- Mobil app (desktop/tablet a műhelyben elég)

---

## Stack

```
Backend       FastAPI + Uvicorn (Python 3.12)
DB            SQLite (WAL módban, busy_timeout=30s) — egy fájl, három modul közös
Frontend      Jinja2 + htmx (CDN, nincs build pipeline)
Auth          session cookie + argon2id, meghívásos regisztráció, multi-role flag
Email         imap_tools (IMAP poller, async loop), per-account SMTP, ClamAV instream
AI            provider switch admin UI-ról: Ollama (helyi) / Gemini Flash / LM Studio
              — runtime config a system_settings táblában, titkosított kulcsokkal
Vírusszűrő    ClamAV (clamd daemon + pyclamd, instream — AppArmor-kompatibilis)
PDF           WeasyPrint (HTML+CSS → A4), Pillow képfeltöltéshez
Worker        hub-worker.service: IMAP poll (60s) + email purge (7d) +
              IMAP cleanup (3d) + Malfini stock-szinkron (hétköznap 7-18, fél óránként)
Notifikáció   in-page toast + Web Audio ding (htmx polling, sidebar count auto-refresh)
Deploy        Ubuntu 24.04 LTS LXC (VMware vagy Proxmox), systemd, nginx
TLS           self-signed (mkcert local CA), vagy plain HTTP a belső hálón
Backup        Synology DS124+ (RAID1 SHR) + off-site Hetzner Storage Box (restic)
              — backup script + systemd timer még nincs (Roadmap)
```

A Rendelő stackjét örököljük, kibővítve azzal ami a Munkák és Készlet moduloknak kell. Ugyanaz az ops workflow.

---

## Architektúra áttekintés

```
hub.printbt.local
        │
        ▼ nginx (:443 / :80)
┌─────────────────────────────────────────────┐
│  Hub LXC (Proxmox)                          │
│  ────────────────                           │
│  hub.service        FastAPI app    :8080    │
│  hub-worker.service IMAP + Corel watcher    │
│                                             │
│  /opt/hub/                                  │
│    ├── app/                                 │
│    │   ├── shared/      auth, db, models   │
│    │   ├── modules/                        │
│    │   │   ├── jobs/    Munkák modul       │
│    │   │   ├── rendelo/ Rendelő modul      │
│    │   │   └── stock/   Készlet modul      │
│    │   ├── workers/     IMAP, watcher      │
│    │   └── main.py      FastAPI bootstrap  │
│    ├── data/            SQLite DB          │
│    ├── uploads/         email csatolmányok │
│    └── venv/                                │
│                                             │
│  /mnt/grafika/    SMB-mount, read           │
│                   (grafikus storage szerver)│
└─────────────────────────────────────────────┘
        │
        ▼ napi backup
┌─────────────────────────────────────────────┐
│  Synology DS124+ (céges LAN)                │
│  RAID1, 2× 3 TB WD Red                      │
│    /backups/hub/        restic repo         │
│    /backups/grafika/    rsync mirror        │
└─────────────────────────────────────────────┘
        │
        ▼ Hyper Backup (titkosított, napi)
┌─────────────────────────────────────────────┐
│  Hetzner Storage Box (off-site, EU)         │
└─────────────────────────────────────────────┘
```

---

## Vizuális design

A Hub UI-ja szándékosan **nem** a tipikus AI-generált webapp esztétika. A célközönség nyomdai szakemberek, és a felület ennek felel meg: **letterpress / paper feeling**, monospace dominancia a technikai adatokon, vermilion piros akcent (mint a régi nyomdai színkódolás), warm-tone neutral háttér.

A vizuális referencia implementálva: `docs/mockup.html` — 10 oldal mindkét témában. **A Hub fejlesztése során minden UI elem ezzel vizuálisan konzisztens kell legyen.** Ha valami a mockup-on nincs benne, vagy más színű / fontos, az hibás.

### Tipográfia

Három font Google Fontsról:

- **Fraunces** (display, serif) — fejlécek, oldal-címek, ügyfél-nevek, hangsúlyos elemek. Italic verzió a „kedves" szövegekhez (greeting, idézet, Gemini-összefoglaló).
- **Plus Jakarta Sans** (body) — minden hosszabb szöveg, leírás, label, nav.
- **JetBrains Mono** — minden ami **technikai adat**: Public ID, SKU, fájl elérési út, dátum-időpont, mennyiség, kategória-címke, audit log entry.

**Heuristika:** ha egy szöveg-elemet *kézzel beír* egy ember, az body. Ha a *rendszer generálja* vagy kategorizálja, az mono.

### Szín-rendszer

CSS változók egy `:root [data-theme="..."]` szelektorban. **Mindkét téma warm earth-tone**, sosem hideg / kék árnyalatú.

**Light (papír-érzet):**
- `--bg`: `#F5F1E8` (krémfehér papír)
- `--surface`: `#FFFFFF`
- `--ink`: `#1F1B16` (sötét meleg fekete, *nem* koromfekete)
- `--accent`: `#C5301F` (vermilion piros)

**Dark (meleg fekete):**
- `--bg`: `#161310` (meleg sötét, *nem* `#000`)
- `--surface`: `#221F1B`
- `--ink`: `#F0EBDC` (krémfehér, *nem* 100% fehér)
- `--accent`: `#E85A4F` (világosabb vermilion, kontraszthoz)

**Funkcionális színek** mindkét témában van `-soft` (világos háttér) és `-ink` (sötét szöveg) variánsa is, amit a státusz-pillek és banner-ek használnak:

- `--accent` (vermilion piros): **csak sürgős és kritikus akcentek**. Soha nem dekoráció, nem szegély-elem.
- `--success` (zöld): kész, megérkezett, OK.
- `--warning` (sárga-okker): folyamatban, figyelem.
- `--info` (kék-szürke): info, semleges státusz.
- `--purple` (lila): csak „rendszer" / „AI" jelzés (Gemini-card, Hub auto-generált tartalom).

**Modul-markerek.** A három modul külön színnel van jelölve a sidebar nav-label előtt és minden kontextus-jelzésnél (pl. „RENDELŐ · IGÉNY #142" cimke):

| Modul | Szín |
|-------|------|
| Munkák | `--accent` (vermilion) |
| Rendelő | `--info` (kék) |
| Készlet | `--success` (zöld) |

### Public ID megjelenítés

A 6-karakteres Job ID a rendszer **legfontosabb vizuális eleme** — a Hub és a fizikai műhely közötti híd. Megjelenítési szabályok minden helyen:

- Mindig **monospace** (JetBrains Mono)
- Mindig **bold** (700 weight)
- Tagolva `XXX-XXX` formában kötőjellel (a backend kötőjel nélkül tárolja)
- A Job-detail hero-ban 48-56pt
- Listákban / kártyán 14-16pt
- A4 munkalap fejlécben 56pt
- Mindig kontrasztosabb mint a környező szöveg — soha nem szürkül el

### Komponens-elvek

**Státusz pill-ek:** lekerekített kis doboz, balra színes kör, mono font, kis caps-mez. Soha nem nagyobb mint a környező szöveg.

**Kártyák (Job, Task, Item, Request):**
- Sima `--surface` háttér, `1px solid --border`
- Kerekített sarok 10px
- Hover: enyhe `translateY(-1px)` + árnyék, 0.15s transition
- **Sürgős** → bal oldalon `3px solid --accent` szegély (`urgent` osztály)
- **Folyamatban** → bal oldalon `3px solid --warning` szegély
- **Auto-generált** (Hub csinálta) → bal oldalon `3px solid --success` szegély
- A teljes kártya háttere SOSEM színesedik, csak a szegély

**Badge-ek és chip-ek:** mono, 9-11px, kis caps-mez. Csak a kritikus értékek kapnak vermilion hátteret (`badge.urgent`).

**Modul-azonosítás kontextusban:** ha egy nézet egy konkrét modulhoz tartozik (pl. igény-részlet vagy item-részlet), a hero blokk tetején egy mono kis-caps szöveg azonosítja a modult: `KÉSZLET · ITEM · PÓLÓ` vagy `RENDELŐ · IGÉNY #142`, balra a modul-marker pöttyel.

### Layout

- **Sidebar:** 260px fix széles, sticky bal oldalt, scrollozható
- **Topbar:** sticky, page-title + search + ikon-gombok
- **Content:** padding 32px, max-width nincs (a táblázatos nézetek tudnak szélesedni)
- **Mobil:** nem támogatott — desktop-only, opcionálisan tablet a műhelyben

### Animáció és mozgás

Minimális és funkcionális, sosem dekoratív.

- Page-váltás: `fadeIn 0.2s ease`, enyhe `translateY(4px)` átmenettel
- Hover: 0.15s transition border-en és transzformon
- Folyamatban-pulzálás: a workshop kártya `FOLYAMATBAN` badge-én, 1.5s ciklus, opacity (`pulse` keyframe)
- Audio: új munka érkezésekor rövid Web Audio ding (~80ms, ~880Hz), nem zavaró

Sehol nem ugráló-csilingelő-figyelemfelhívó.

### Mit NE használjunk

A klasszikus AI-generált webapp jegyek **mind kerülendők**:

- Inter, Roboto, system fontok body-ra
- Lila / pink / kék gradiens hátterek
- „Glass morphism" / blur+saturate kompozíciók
- Cliched dashboard-card-ok hatalmas árnyékkal
- „Modern flat" hideg neutrálok (`#FFFFFF` + `#F8F9FA`)
- Floating decorative shapes, abstract blobs
- Lottie animációk
- Toaster-szivárvány emoji ikonok mindenhol

A Hub identitása **anti-cuki, anti-trendi nyomdai feeling**. Letterpress, paper, ink. A vermilion az egyetlen hangsúlyos szín, és csak ott ahol érdemes.

### Új komponens hozzáadásakor

A claude code session során, ha új komponenst tervezel:

1. Először nézd meg a `docs/mockup.html`-en ha van hasonló komponens (kártya, gomb, státusz-pill, lista-row, hero blokk, panel)
2. Ha van: másold a tokeneket (CSS-változók, spacing, font-méret, weight)
3. Ha nincs hasonló: tartsd magad a fenti elvekhez (mono technikai adatra, vermilion csak akcentre, hideg szín soha)
4. Soha ne adj hozzá új színt a palettához ad-hoc — ha új funkcionális szín kell, az tervezett változás

---

## Modulok részletesen

### Munkák modul

A teljes Műhely-spec, korábban külön doksiban. Lényegi pontjai:

**Adatmodell.** `jobs`, `job_tasks`, `job_attachments`, `customers`, `email_accounts`, `incoming_emails`, `email_attachments`, `audit_log`. A `customers` és `users` táblák közösek a többi modullal.

**Public ID.** 6 karakteres, `ABCDEFGHJKMNPQRSTVWXYZ23456789` készletből (kihagyva: `0/O/1/I/L/U`), ütközés esetén retry, fogyás után +1 karakter. Megjelenítés: `XXX-XXX` tagolt formában (`K7M-2X9`), monospace fonttal kiemelve mindenhol.

**Státusz életciklus.** `felvett → grafikán → kész_látvány → [ügyfél_jóváhagyás_vár] → műhelyben → kész → átadva`. Audit log minden átléptetésnél.

**Pool.** Job felvételkor két irány: hozzárendelés a felvevőhöz (default), vagy közös pool (jelölőnégyzet). Pool-ból bárki magához veheti.

**Email integráció.**
- 4 IMAP fiók pollozása percenként (3× grafikus + 1× közös műhely)
- Csatolmányok mentése `/opt/hub/uploads/inbox/YYYY-MM-DD/feladó-email/`
- ClamAV vírusszűrés minden csatolmányon (fertőzött → karantén, piros jelzés az UI-n)
- Gemini előszűrés (`gemini-2.5-flash`): `work` / `quote_request` / `spam` / `other`
- Ismert ügyfél (`customers.email` match) felülírja a Gemini-t → `work`
- 4-tab inbox UI: Munka / Árajánlat / Egyéb / Spam
- Spam tabnál 7 nap után auto-purge a `incoming_emails` rekordra (fizikai mailt megtartjuk)
- Manuális felülbírálás a `manual_category_override` mezőbe kerül
- „Munkává alakítás" gomb → prefilled Job form, csatolmányok automatikusan hozzá

**CorelDRAW makró.** VBA makró mind a 3 grafikus gépén, F12 hotkey:
1. Felugrik dialógus „Munka azonosító:" mezővel
2. Beírod/bemásolod a 6 karakteres ID-t
3. Aktív Corel doc minden oldala PNG-be exportálva, 200 DPI
4. Mentés: `\\storage\hub-previews\K7M2X9_1.png`, `_2.png`, …
5. Worker (`watchdog` lib) figyeli a mappát, parse-olja az ID-t, hozzárendeli a Job-hoz, státuszt `kész_látvány`-ra lépteti
6. Fallback: drag-drop zóna a Job nézeten belül

**A4 munkalap.** WeasyPrint-tel HTML+CSS sablonból. Layout: fejléc (ID 56pt monospace + ügyfél + határidő-doboz piros sürgős stemplivel), látvány-keret középen (~140 mm), task-checkbox lista + grafikai megjegyzés, lábléc (fájl elérési út monospace, felvette/dátum, kézi rubrika). Több preview → több A4 lap automatikusan.

**Műhelyes nézet.** Gép-szűrő chipek (UV / CO2 / Fiber / DTF press / Bögre press / Gravír kézi / Bélyegző / Matrica / Nagyformátum), task-kártyák határidő szerint rendezve, „Megcsinálom" / „Kész" gombok. Egy közös műhelyes gép vagy tablet elég, nem kell minden gép mellé.

**Árajánlat shared inbox.** Gábor + édesapa + Kinga közös. 5 perces auto-lock (kinél van megnyitva), avatar-jelzés, „Magamhoz veszem" explicit hozzárendelés. AI válasz draft gomb (Gemini), válasz SMTP-vel.

A részletes táblaséma és UI a `docs/mockup.html`-ben és a Munkák spec külön dokumentumban.

### Rendelő modul

A meglévő `nyomda_rendelo` repó funkcionalitása változatlanul, integrálva. Aki észreveszi hogy fogy egy alapanyag (toner, papír, laminálófólia, karbantartási cikk), feltesz egy igényt; aki rendelni szokott (Gábor / édesapa), leveszi; mindenki látja az állapotot.

**Adatmodell.** `items`, `requests`, `request_comments`. Külön tartva a Készlet modul `stock_items` táblájától: a Rendelő egy **igény-tracker**, nem készletnyilvántartó. Egy ember mond „kell még papír", erre lesz egy `request`. A Készlet modul ettől független — az tudja meg hány raklap papír van fizikailag.

**Migráció a meglévő Rendelőből.**
1. SQL dump a régi `rendelo.db`-ből
2. Séma-import az új közös DB-be (`rendelo_items`, `rendelo_requests`, ... prefix vagy schema-elválasztással)
3. User-mapping a közös `users` táblára
4. Teszt-import staging környezetben, regression test
5. DNS átírás: `rendelo.gyorsnyomda.hu` → 301 redirect a Hub `/rendelo` route-jára (fade-out időszak), vagy aldomain marad de proxy-zol az új app-ra
6. Régi service kikapcs

A migrációt **a Munkák modul építése előtt** csináljuk — addigra az új közös skeleton már igazi forgalmat szolgál ki.

### Készlet modul

**Cél:** a Job felvételekor és teljesítésekor tudni, hogy mi van fizikailag a polcon, és automatikusan jelezni ha valamiből kevés van.

**Adatmodell.**

| Tábla | Mezők |
|-------|-------|
| `stock_items` | `id`, `sku`, `name`, `category` (póló / bögre / fólia / festék / egyéb), `unit` (db / m / kg), `current_qty`, `min_stock`, `lead_days`, `supplier_note`, `last_movement_at`, `notes` |
| `stock_movements` | `id`, `item_id`, `delta` (±), `reason` (`job_consumption`, `delivery`, `manual_correction`, `count_adjustment`), `ref_type` + `ref_id` (pl. `job` + Job ID), `user_id`, `at`, `note` |
| `job_material_requirements` | `id`, `job_id`, `item_id`, `required_qty`, `consumed_qty`, `notes` |

**Munkafolyamat.**

1. **Job felvételkor** opcionális: a felvevő hozzáad anyagigényt a Job-hoz (`job_material_requirements`). Pl. `polo_basic_blue_M × 50`. Az UI azonnal mutatja: jelenlegi készlet 30 db → **20 db hiányzik**.
2. **Hiánykor** egy gomb: „Rendelés generál" → létrehoz egy `rendelo_request`-et a Rendelő modulban a hiányzó mennyiségre, megjegyzéssel hogy ki és melyik Job miatt kérte.
3. **Job kész** → automatikusan `stock_movements` rekordok generálódnak, `delta = -required_qty`, `ref_type=job`. Készlet csökken.
4. **Beérkezett szállítmány** → két út: (a) kézzel `stock_movements` `delivery` reason, vagy (b) Rendelő `request` lezárásánál opcionális gomb „Készletbe írta" ami auto-generálja.
5. **Min-stock alá esés** → automatikus toast notification a `is_admin` és `is_workshop` userek számára, opcionálisan auto-Rendelő-igény (konfigurálható).
6. **Leltár** (havi vagy negyedéves) → admin nézet, kézzel beírod a fizikai darabszámot, a különbség `count_adjustment` reason-nel rögzítődik.

**Mit NEM csinál a modul.**

- Nem számol értéket, áfát, FIFO-t, átlagárat
- Nem ad ki bizonylatot
- Nem kezel többraktárt (egy raktár = a műhely)
- Nem auditál a hatóságnak (csak audit log saját használatra)
- Nem csinál PO-t (a „rendelés" amit generál csak egy Rendelő-igény belső használatra)

A határ pontosan ott van, ahol a pénz belép. Amíg a rendszer csak fizikai darabszámot mond, addig operatív segédeszköz; amint árat, áfát, számlázást húz be, ERP-vé válik és ezt szándékosan kerüljük. **Soha** ne kerüljön `price`, `vat`, `invoice` mező a stock-ba — ezt a kódban is tiltani kell, és a code review-n ezt nézni.

### Közös táblák

A három modul egy DB-ben él, és néhány tábla közös:

- `users` — multi-role flag-ekkel (`is_intake`, `is_designer`, `is_workshop`, `is_quote_handler`, `is_orderer`, `is_admin`, `is_superadmin`)
- `customers` — a Munkák modul használja, de elérhető más modulnak is (későbbi printbt.hu redesignhoz API-n is)
- `audit_log` — `entity_type` mező különbözteti meg melyik modulé (`job`, `task`, `email`, `request`, `stock`)
- `notifications` — közös értesítési csatorna toast-okhoz

---

## Szerepkörök

A user role flagjei alapján a sidebar dinamikusan jelenik meg.

| Role | Munkák | Rendelő | Készlet |
|------|--------|---------|---------|
| `is_intake` | új munka, saját felvett | — | — |
| `is_designer` | saját munkák, közös pool, email inbox | igények listázása | — |
| `is_workshop` | task-listák gép szerint | igény feladás | készlet böngészés |
| `is_quote_handler` | árajánlat shared inbox | — | — |
| `is_orderer` | — | rendelések felvétele/lezárása | készlet bevételezés |
| `is_admin` | minden + ügyfél | minden | leltár, item kezelés |
| `is_superadmin` | minden + email-fiók-konfig + API kulcs + SMB mount | minden | minden |

**`is_admin` vs `is_superadmin`:** az `is_admin` az **operatív** admin (userek, meghívók, ügyfelek, kategóriák, tételek). A `is_superadmin` ezenfelül a **rendszer-szintű** integrációkat is kezeli: IMAP fiók-credentials (titkosítva), Gemini/SMTP API kulcsok, SMB mount config. Több `is_admin` lehet (pl. Kinga is), de a host-szintű titkokhoz csak a `is_superadmin` fér hozzá.

**Konkrét eloszlás:**
- **Gábor:** mind a 7 (rendszergazda + mindenes, egyetlen `is_superadmin`)
- **Édesapa:** `is_quote_handler` + `is_orderer`
- **Kinga:** `is_quote_handler` + `is_orderer` + `is_admin` (operatív segítő)
- **3 grafikus srác:** `is_intake` + `is_designer`
- **Vasalós + gépkezelő kollégák:** `is_workshop`

---

## Telepítés (Proxmox LXC)

### 1) LXC létrehozás

A Proxmox node-on root user-ként:

```bash
# Debian 12 template letöltése ha még nincs
pveam update
pveam download local debian-12-standard_12.7-1_amd64.tar.zst

# LXC létrehozás
pct create 110 local:vztmpl/debian-12-standard_12.7-1_amd64.tar.zst \
  --hostname hub \
  --cores 2 \
  --memory 2048 \
  --swap 1024 \
  --rootfs local-lvm:30 \
  --net0 name=eth0,bridge=vmbr0,ip=192.168.1.110/24,gw=192.168.1.1 \
  --nameserver 192.168.1.1 \
  --searchdomain printbt.local \
  --features nesting=1 \
  --unprivileged 1 \
  --start 1
```

A grafikus szerver SMB share-jéhez:

```bash
# Az LXC config fájlba (/etc/pve/lxc/110.conf) hozzáadás:
echo "mp0: /mnt/pve/grafika,mp=/mnt/grafika,ro=1" >> /etc/pve/lxc/110.conf
pct restart 110
```

### 2) Bootstrap az LXC-n belül

```bash
pct enter 110
```

Az LXC-n belül:

```bash
apt-get update && apt-get install -y wget gnupg ca-certificates curl

# GitHub CLI (privát repo eléréshez)
install -d -m 755 /etc/apt/keyrings
wget -qO- https://cli.github.com/packages/githubcli-archive-keyring.gpg \
  | tee /etc/apt/keyrings/githubcli-archive-keyring.gpg > /dev/null
chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
  | tee /etc/apt/sources.list.d/github-cli.list > /dev/null
apt-get update && apt-get install -y gh

gh auth login   # GitHub.com → HTTPS → "Login with a web browser"
```

### 3) Előfeltételek

```bash
gh repo clone gaberun24/hub /tmp/hub-bootstrap
bash /tmp/hub-bootstrap/scripts/install-prereqs.sh
```

Ez telepíti:
- Python 3.12 (deadsnakes PPA, vagy Debian backport)
- nginx
- sqlite3
- avahi-daemon (mDNS, hogy `hub.printbt.local` is megy LAN-on)
- ClamAV (`clamav-daemon` + `clamav-freshclam`) — email csatolmányok vírusszűrése
- WeasyPrint rendszerfüggőségei (`libpango`, `libcairo`, ...)
- restic
- létrehozza a `hub` rendszerusert (no-shell) és az `/opt/hub/` könyvtárat
- `freshclam` frissíti a vírus-definíciókat, `clamd` daemon elindul

### 4) App telepítése

```bash
gh repo clone gaberun24/hub /opt/hub/app
bash /opt/hub/app/scripts/setup-app.sh
```

A setup script:
- venv-et hoz létre `/opt/hub/venv`-be, telepíti a `requirements.txt`-t
- `/opt/hub/.env`-et készít random `SECRET_KEY`-jel és üres Gemini API kulcs placeholderrel
- `hub.service` és `hub-worker.service` systemd unit-okat regisztrálja és bekapcsolja
- nginx site-ot beleköti, reloadolja
- inicializálja a SQLite DB-t `/opt/hub/data/hub.db`-be migrációkkal

### 5) `.env` konfigurálás

```bash
nano /opt/hub/.env
```

Kötelező mezők:

```bash
SECRET_KEY=<random — már generálva>
BASE_URL=http://hub.printbt.local
SECURE_COOKIES=false              # mert nincs HTTPS belül (vagy true mkcert-tel)

# Adatbázis
DATABASE_URL=sqlite:////opt/hub/data/hub.db

# Gemini API
GEMINI_API_KEY=<innen: https://aistudio.google.com/app/apikey>
GEMINI_MODEL=gemini-2.5-flash

# Storage
UPLOAD_DIR=/opt/hub/uploads
GRAFIKA_MOUNT=/mnt/grafika
COREL_PREVIEW_DIR=/mnt/grafika/hub-previews

# IMAP poller intervallum
IMAP_POLL_INTERVAL_SEC=60

# Email küldéshez (árajánlat válasz)
SMTP_HOST=smtp.printbt.hu
SMTP_PORT=587
SMTP_USER=info@printbt.hu
SMTP_PASSWORD=<jelszó>
```

Email-fiókok IMAP konfigja **a Rendszer (superadmin) UI-n** kerül felvitelre, nem a `.env`-be (titkosítva tárolódnak a `email_accounts.imap_password_encrypted` mezőben, a `SECRET_KEY`-vel). Csak `is_superadmin` flag-gel rendelkező user fér hozzá.

### 6) Első admin

```bash
sudo -u hub /opt/hub/venv/bin/hub create-admin \
    --name "Gábor" --email gabor@example.com
# → Jelszó:        (némán beír)
# → Jelszó újra:   (megerősítés)
```

A jelszó interaktívan, némán kerül megadásra. **Ne használd a `--password` paramétert**, mert akkor a bash history-ban és a `ps` listában is látszani fog.

További CLI parancsok:

```bash
sudo -u hub /opt/hub/venv/bin/hub list-users
sudo -u hub /opt/hub/venv/bin/hub generate-invite --email kinga@example.com --roles quote_handler,orderer
sudo -u hub /opt/hub/venv/bin/hub import-rendelo /tmp/old-rendelo.db
```

A `import-rendelo` parancs migrálja a meglévő `nyomda_rendelo` DB-t. Ezt csak egyszer futtatjuk, az első deploy után.

### 7) DNS és mDNS

A `hub.printbt.local` domain belső LAN-on:

**Opció A — UniFi DNS:** UniFi Network controller → Settings → Networks → DNS, hozzáadás: `hub.printbt.local → 192.168.1.110`. Ez a kényelmes út, mert mindenki magától felveszi a DNS-t a routertől.

**Opció B — mDNS / avahi:** ha az UniFi-n nem akarod beállítani, az avahi-daemon az LXC-n hirdeti `hub.local` és `hub.printbt.local` neveken. Mac/Linux automatikusan tudja, Windows-on Bonjour Print Services kell hozzá (vagy egyszerűen IP-vel mész).

### 8) TLS (opcionális, belső)

Mivel csak belső, sima HTTP is megy. De ha akarsz HTTPS-t (browser ne sírjon, jelszó-mező ne legyen sárga):

**`mkcert`-tel** lokális CA, amit egyszer feltelepítesz minden gépre:

```bash
# Az adminisztrátor gépedről (nem az LXC-n!):
mkcert -install   # local CA telepítése a gép trust store-jába
mkcert hub.printbt.local hub.local 192.168.1.110

# Az így kapott .pem és -key.pem fájlokat felmásolod az LXC-re:
scp hub.printbt.local+2.pem root@192.168.1.110:/etc/nginx/ssl/hub.crt
scp hub.printbt.local+2-key.pem root@192.168.1.110:/etc/nginx/ssl/hub.key
```

Az nginx config TLS része (a setup script már elkészíti, csak engedélyezni kell). A többi gépre (kollégák) a CA cert-jét fel kell tenned egyszer.

---

## Frissítés

Egy parancs az LXC-n belül:

```bash
bash /opt/hub/app/scripts/update-app.sh
```

Ez:
1. `git pull` root-ként a privát repóból
2. `chown` vissza a `hub` user-re
3. `pip install -r requirements.txt` ha változott a `requirements.txt`
4. Adatbázis-migrációk futtatása (`alembic upgrade head`)
5. `systemctl restart hub.service hub-worker.service`
6. `systemctl reload nginx` ha a site config is változott
7. Healthcheck: GET `http://localhost:8080/health` — ha 200, OK; ha nem, rollback előző commit-ra

---

## Backup

A 3-2-1 szabály a céges felállásban: élő LXC + lokális Synology + off-site Hetzner.

### Szint 1 — App-szintű backup (a Hub-on belül)

Cron, naponta `02:00`:

```bash
# /etc/cron.d/hub-backup
0 2 * * * hub /opt/hub/app/scripts/backup.sh
```

A `backup.sh` a következőket csinálja:

1. **DB konzisztens dump:** `sqlite3 /opt/hub/data/hub.db ".backup /tmp/hub-$(date +%F).db"`
2. **Uploads tarball:** `/opt/hub/uploads/` → `tar.gz`
3. **`.env` konfig** → titkosított csomag (mert benne SMTP jelszó és Gemini API kulcs)
4. **`restic backup`** → Hetzner Storage Box (lásd lent)
5. **Lokális másolat** a Synology SMB share-en (`//nas.printbt.local/backups/hub/`)
6. **Retention:** local 14 nap, Hetzner restic policy szerint (7 napi + 4 heti + 12 havi snapshot)

### Szint 2 — VM/LXC szintű backup (Proxmox PBS)

Proxmox Backup Server (PBS) datastore a **Synology NFS share**-en (a NAS exportálja `/backups/pbs/`-t NFS-en). Heti egy teljes LXC backup, deduplikált, blokkszintű. Ez gyors restore-t ad ha az LXC maga sérül meg vagy a Proxmox node halna meg.

```
Proxmox UI → Datacenter → Backup → Add
  Storage: pbs-synology
  Schedule: weekly Sunday 03:00
  Selection: ct/110 (hub)
  Mode: snapshot (no downtime)
  Compression: zstd
  Retention: keep-last 4, keep-monthly 6
```

### Szint 3 — Off-site (Hetzner Storage Box)

A Synology natív **Hyper Backup** alkalmazása napi 1×, éjszaka:

```
Forrás:   /volume1/backups/
Cél:      Hetzner Storage Box (Rsync over SSH target)
Titkosítás: client-side, jelszó (Synology-n eltárolva)
Retention: utolsó 7 napi + 4 heti + 12 havi
```

Ez a Hub-szintű restic mellett egy második titkosított rétegként megy fel — overkill, de a Synology natívan tudja, miért ne.

A `restic` (Szint 1-ből közvetlenül Hetznerre) mellett a Synology Hyper Backup átfogóbb (a grafikus szerver mirror is benne van). A két megoldás párhuzamosan fut, redundánsan.

### Restore drill — havonta

Naptárba bekötött havi feladat: kihúzol egy backupot egy másik gépre és ellenőrzöd hogy a DB ép és visszatölthető. Sok ember ezt kihagyja, és aztán amikor kellene, kiderül hogy a backup évek óta korrupt volt.

```bash
# Egy másik gépen:
restic -r sftp:user@hetzner-storagebox:hub-restic restore latest --target /tmp/hub-restore
sqlite3 /tmp/hub-restore/data/hub.db "SELECT COUNT(*) FROM jobs;"   # nem zéró → OK
```

### Restore esetén

Egy LXC-pusztulás után:
1. Új LXC létrehozása ugyanazzal a hostname-mel és IP-vel
2. PBS-ből restore (ha van friss): `pct restore 110 backup:ct/110/<timestamp>` → 5 perc, kész
3. Vagy bootstrap-ből újra + Hetznerből restic restore: `restic restore latest --target /opt/hub/`
4. systemd service-ek bekapcs

---

## Lokális fejlesztés (Windows / Mac / Linux)

```bash
# Repo klón
gh repo clone gaberun24/hub
cd hub

# Virtualenv
python3.12 -m venv .venv
source .venv/bin/activate              # Linux/Mac
.venv\Scripts\Activate.ps1             # Windows PowerShell

pip install -r requirements.txt
pip install -r requirements-dev.txt    # pytest, ruff, alembic dev tools

cp .env.example .env                   # majd írd át a SECRET_KEY-t és a GEMINI_API_KEY-t
alembic upgrade head                   # DB migrációk

python -m app.cli create-admin --name "Gábor" --email a@b.hu --password 'fejlesztói-jelszó'

# App
uvicorn app.main:app --reload --port 8080

# Worker (másik terminálban)
python -m app.workers.main
```

Aztán `http://127.0.0.1:8080`.

A Gemini API kulcs nélkül a fejlesztés is megy, csak az IMAP poller egy stub klasszifikátort használ (mindent `other`-be sorol).

A grafikus storage szervert lokál fejlesztésnél nem mountoljuk — a `COREL_PREVIEW_DIR` lehet `./test_previews/` és kézzel pakolj bele PNG-t teszteléshez.

---

## Roadmap

Részletes fázis-by-fázis tracker: [`ROADMAP.md`](ROADMAP.md).
Release notes: [`CHANGELOG.md`](CHANGELOG.md).

**Aktuális állás (2026-05-08):** v0.5.1 — **Fázis 0, 1, 2, 4 kész**, **Fázis 3** A4-PDF-fel részben kész (Corel makró még nincs). A Hub production-on fut a `192.168.1.69` LXC-n, és a régi `nyomda_rendelo` repó **összes** funkcióját átvette (Malfini B2B, CSV-importer, archívum, cascade dropdown, live notification). Az ügyfeleknek 5-karakteres egyedi azonosító (`XX###`) jár regisztráláskor, retroaktív backfill-lel a meglévőkre.

| Fázis | Cél | Státusz |
|-------|-----|---------|
| 0 | Auth + skeleton | ✅ kész |
| 1 | Rendelő modul (full port) | ✅ kész |
| 2 | Munkák modul | ✅ kész |
| 3 | A4 munkalap + Corel makró | ⏳ A4-PDF kész, Corel makró nem |
| 4 | Email integráció (IMAP + AI klasszifikáció) | ✅ kész |
| 5 | Árajánlat shared inbox | tervezett |
| 6 | Készlet modul (belső raktár) | tervezett |
| 7 | Csiszolás (statisztika, keresés, PWA) | tervezett |

### Lehetséges későbbi modulok

Ide kerülnek azok az ötletek amik most nem indokoltak, de a Hub-architektúra később megengedi:

- **Számlázz.hu integráció** — egy gomb a Job-on → API hívás → kész számla. Két napos meló, NAV-konformitás a Számlázz.hu felelőssége.
- **printbt.hu redesign integráció** — közös `customers` táblán keresztül a publikus weboldal AI chat widget-jéből származó leadek automatikusan a Munkák modul inboxába kerülnek.
- **Composit Studio gallery hivatkozás** — befejezett fotós Job-ból egy gomb, ami publikálja a `galeria.compositstudio.hu`-ra a kész képeket (PIN-védett).
- **JARVIS integráció** — sürgős munkák Discord-ra, készlet-figyelmeztetések, heti AI-összefoglaló a működésről.

---

## Nyitott kérdések

1. **`hub.printbt.local` vs `hub.local`:** UniFi DNS-szel az előbbi tisztább, mDNS-szel az utóbbi egyszerűbb. (Javaslat: `hub.printbt.local` UniFi DNS-en.)
2. **Reseller Job-ok csoportosítása:** egyesével külön Job-ok maradnak, vagy később egy „project/batch" entitás alá szervezve havonta gyűjtve? (Számlázáshoz/exporthoz lesz hasznos, ha nem most akkor később.)
3. **Discord/JARVIS notifikáció:** mikor és miért szóljon? (Sürgős határidő közelében? Pool-ban túl régóta lógó munka? Új árajánlat-kérés? Készlet kritikus?)
4. **Reseller kedvezmény:** csak info mező, vagy az ár-mezőhöz is automatikusan alkalmazódik?
5. **Készlet item-ek SKU-ja:** szabadon kiosztott, vagy beszállítói cikkszám alapján? (Pl. Gildan H6400 fekete S → `polo_gildan_h6400_blk_s`?)
6. **Anyagigény szerkesztő UX:** Job felvételkor egy mező-listával, vagy egy „task → mit fogyaszt" hozzárendeléssel? (Az utóbbi rugalmasabb, de bonyolultabb.)
7. **A4-en a fájl elérési út rövidítése:** ha a teljes UNC path 100+ karakter, mit vágunk le? (Pl. csak az utolsó 2-3 mappa + fájlnév?)
8. **Restore drill ütemezés:** kalendárba beépített havi feladat, vagy egy admin UI-ban gomb „Last drill: 2026-04-15" kijelzéssel és egy „Mark as done" akcióval?

---

## Licenc

Belső projekt, nincs nyilvános licenc. Tilos a kódot harmadik fél számára kiadni a Gyorsnyomda / PrintBT engedélye nélkül.
