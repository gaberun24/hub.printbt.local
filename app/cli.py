"""Hub CLI — bootstrap admin létrehozás, meghívók kezelése.

Használat:
    hub create-admin --name "Gábor" --email gabor@...
    hub list-users
    hub generate-invite --email kinga@... --roles quote_handler,orderer
"""

from __future__ import annotations

import argparse
import getpass
import sys
from datetime import timedelta

from sqlalchemy import select

from app.shared.config import settings
from app.shared.db import SessionLocal, init_db
from app.shared.models import ROLE_FLAGS, Invite, User, utcnow
from app.shared.security import generate_token, hash_password


def _prompt_password(min_length: int = 10) -> str | None:
    """Interaktív jelszókérés (silent input). None ha nem egyezik vagy túl rövid."""
    password = getpass.getpass("Jelszó: ")
    confirm = getpass.getpass("Jelszó újra: ")
    if password != confirm:
        print("HIBA: a két jelszó nem egyezik.", file=sys.stderr)
        return None
    if len(password) < min_length:
        print(f"HIBA: a jelszó legalább {min_length} karakter legyen.", file=sys.stderr)
        return None
    return password


def _parse_roles(roles_arg: str | None) -> dict[str, bool]:
    """A --roles opciót CSV-ből bontja role-flag dict-té.

    Pl. `--roles designer,intake` → {"is_designer": True, "is_intake": True, ...}.
    Az ismeretlen role-okat hibával jelzi.
    """
    flags = dict.fromkeys(ROLE_FLAGS, False)
    if not roles_arg:
        return flags
    raw = [r.strip() for r in roles_arg.split(",") if r.strip()]
    for r in raw:
        flag = f"is_{r}"
        if flag not in flags:
            valid = ", ".join(f.removeprefix("is_") for f in ROLE_FLAGS)
            raise SystemExit(f"HIBA: ismeretlen role: '{r}'. Érvényes: {valid}")
        flags[flag] = True
    return flags


def cmd_create_admin(args: argparse.Namespace) -> int:
    init_db()

    password = args.password
    if password is None:
        password = _prompt_password()
        if password is None:
            return 1

    with SessionLocal() as db:
        existing = db.execute(
            select(User).where(User.email == args.email.lower())
        ).scalar_one_or_none()
        if existing is not None:
            print(f"HIBA: már van user ezzel az email-lel: {args.email}", file=sys.stderr)
            return 1
        user = User(
            name=args.name,
            email=args.email.lower().strip(),
            password_hash=hash_password(password),
            is_admin=True,
            is_intake=True,
            is_designer=True,
            is_workshop=True,
            is_quote_handler=True,
            is_orderer=True,
            active=True,
        )
        db.add(user)
        db.commit()
        print(f"✓ Admin létrehozva: {user.name} <{user.email}> (id={user.id})")
        print("  Az admin minden role-flaget megkap (kényelmi default).")
    return 0


def cmd_list_users(_args: argparse.Namespace) -> int:
    init_db()
    with SessionLocal() as db:
        users = db.execute(select(User).order_by(User.id)).scalars().all()
        if not users:
            print("Nincsenek userek.")
            return 0
        print(f"{'ID':>3}  {'NÉV':<20}  {'EMAIL':<30}  {'AKTÍV':<6}  ROLE-OK")
        for u in users:
            roles = ", ".join(f.removeprefix("is_") for f in ROLE_FLAGS if getattr(u, f)) or "—"
            print(
                f"{u.id:>3}  {u.name[:20]:<20}  {u.email[:30]:<30}  "
                f"{'igen' if u.active else 'nem':<6}  {roles}"
            )
    return 0


def cmd_rescan_attachments(args: argparse.Namespace) -> int:
    """Minden nem-tiszta (pending/error/skipped) csatolmány újraszkennelése.

    Hasznos első telepítés után, amikor a ClamAV daemon még nem volt
    elérhető — a meglévő emailek csatolmányai `pending` vagy `skipped`
    státuszban maradtak, ezt egyenesbe rakja.
    """
    from pathlib import Path

    init_db()

    from app.modules.jobs.email_models import EmailAttachment, ScanStatus
    from app.modules.jobs.virus_scanner import _get_clamd, scan_attachment

    if _get_clamd() is None:
        print(
            "HIBA: ClamAV daemon nem elérhető. Indítsd el: "
            "sudo systemctl start clamav-daemon",
            file=sys.stderr,
        )
        return 1

    targets_filter = [ScanStatus.PENDING, ScanStatus.ERROR, ScanStatus.SKIPPED]
    if args.all:
        targets_filter.append(ScanStatus.CLEAN)

    with SessionLocal() as db:
        targets = (
            db.execute(
                select(EmailAttachment).where(EmailAttachment.scan_status.in_(targets_filter))
            )
            .scalars()
            .all()
        )

        if not targets:
            print("Nincs újraszkennelendő csatolmány.")
            return 0

        upload_dir = Path(settings.upload_dir)
        from collections import Counter

        results: Counter = Counter()
        print(f"Újraszkennelés: {len(targets)} csatolmány...")
        for att in targets:
            old = str(att.scan_status)
            new = scan_attachment(att, upload_dir)
            results[str(new)] += 1
            mark = "→" if str(new) != old else "·"
            print(f"  {mark} #{att.id} {att.filename[:50]:<50}  {old:<8} → {new}")

        db.commit()

        print()
        print("Eredmény:")
        for status, n in sorted(results.items()):
            print(f"  {status:<10} {n}")
    return 0


def cmd_reclassify_emails(args: argparse.Namespace) -> int:
    """Meglévő emailek újra-osztályozása az aktuális AI provider-rel.

    Default: csak a `RULE_FALLBACK` (= AI nem volt elérhető a poll idején)
    classified_by-jakat. `--all` kapcsolóval a meglévő AI-eredményeket is
    átfuttatja (Gemini→Ollama váltáskor pl. hasznos).

    A manuálisan átsorolt emailek `manual_category`-ja érintetlen marad —
    az `effective_category` nem változik, csak a háttér `category` mező frissül.
    A `RULE_CUSTOMER` / `RULE_SUPPLIER` / `RULE_SPAM` szabály-alapú
    kategóriákhoz nem nyúlunk (determinisztikus, nem érdemes újra-futtatni).
    """
    init_db()

    from collections import Counter

    from app.modules.jobs.ai_settings import get_ai_config
    from app.modules.jobs.email_classifier import apply_classification, classify_email
    from app.modules.jobs.email_models import ClassifiedBy, IncomingEmail
    from app.shared.models import AuditEntityType, AuditLog

    with SessionLocal() as db:
        cfg = get_ai_config(db)
        if cfg.provider == "none":
            print(
                "HIBA: nincs aktív AI provider. Állítsd be először az "
                "Admin → AI beállítások oldalon.",
                file=sys.stderr,
            )
            return 1

        # Mit célozunk meg?
        if args.all:
            # Minden AI-osztályozott rekord (manual NEM, rule_* NEM)
            targets_filter = [
                ClassifiedBy.RULE_FALLBACK,
                ClassifiedBy.GEMINI,
                ClassifiedBy.OLLAMA,
                ClassifiedBy.LM_STUDIO,
            ]
            mode_label = "minden AI-osztályozott"
        else:
            targets_filter = [ClassifiedBy.RULE_FALLBACK]
            mode_label = "csak RULE_FALLBACK (AI nélküli) emailek"

        stmt = select(IncomingEmail).where(
            IncomingEmail.classified_by.in_([c.value for c in targets_filter]),
            IncomingEmail.purged_at.is_(None),
        ).order_by(IncomingEmail.received_at.desc())

        if args.limit:
            stmt = stmt.limit(args.limit)

        targets = db.execute(stmt).scalars().all()

        if not targets:
            print(f"Nincs újra-osztályozandó email ({mode_label}).")
            return 0

        print(f"Reclassify: {len(targets)} email · provider: {cfg.provider} · módja: {mode_label}")
        print()

        category_changes: Counter = Counter()
        unchanged = 0

        for em in targets:
            old_category = str(em.category) if em.category else "—"
            old_classifier = str(em.classified_by) if em.classified_by else "—"

            try:
                result = classify_email(db, em)
            except Exception as exc:
                print(f"  ✗ #{em.id} hiba: {exc}")
                continue

            new_category = str(result.category)
            apply_classification(em, result)

            if new_category != old_category:
                category_changes[f"{old_category} → {new_category}"] += 1
                marker = "→"
                # Audit log csak változásnál
                db.add(
                    AuditLog(
                        entity_type=AuditEntityType.EMAIL,
                        entity_id=em.id,
                        action="reclassify",
                        old_value=f"{old_category} ({old_classifier})",
                        new_value=f"{new_category} ({result.classified_by})",
                    )
                )
            else:
                unchanged += 1
                marker = "·"

            subject = (em.subject or "(nincs tárgy)")[:50]
            print(
                f"  {marker} #{em.id:>4}  {old_category:<14} → {new_category:<14}  {subject}"
            )

        db.commit()

        print()
        print(f"Eredmény: {unchanged} változatlan, {sum(category_changes.values())} átkategorizálva")
        if category_changes:
            print()
            print("Átmenetek:")
            for change, n in sorted(category_changes.items(), key=lambda x: -x[1]):
                print(f"  {change:<30}  {n}")

    return 0


def cmd_import_malfini_pricelist(args: argparse.Namespace) -> int:
    """Malfini Standard Pricelist CSV → variant-szintű katalógus."""
    init_db()

    from app.modules.rendelo.malfini_csv import import_pricelist_csv

    print(f"CSV: {args.csv_path}")
    print(
        f"Mód:           {'minden sor (~14,800)' if args.all else 'csak essential modellek (~2,054)'}"
    )
    print(
        f"Régi tételek:  {'INACTIVE-ra állítjuk' if not args.keep_old else 'változatlanul hagyjuk'}"
    )
    if args.dry_run:
        print("DRY-RUN — nem commit-olunk")
    print()

    with SessionLocal() as db:
        try:
            stats = import_pricelist_csv(
                db,
                args.csv_path,
                only_essential=not args.all,
                deactivate_missing=not args.keep_old,
                dry_run=args.dry_run,
            )
        except ValueError as e:
            print(f"HIBA: {e}", file=sys.stderr)
            return 1

    label = "DRY-RUN" if args.dry_run else "Mentve"
    print(f"[{label}]")
    print(f"  CSV sor:           {stats.rows_seen:>6}")
    print(f"  Új Item:           {stats.added:>6}")
    print(f"  Frissítve:         {stats.updated:>6}")
    print(f"  Kihagyva (filter): {stats.skipped_filter:>6}")
    print(f"  Kihagyva (üres):   {stats.skipped_invalid:>6}")
    print(f"  Inactive-ra állva: {stats.deactivated:>6} (CSV-ben nem szerepel, régi)")
    if stats.by_category:
        print()
        print("Kategóriánként:")
        for cat, n in stats.by_category.most_common():
            print(f"  {cat:<20} {n:>6}")
    return 0


def cmd_refresh_malfini_stock(_args: argparse.Namespace) -> int:
    """Malfini B2B API → Item.stock_qty refresh.

    A credential-ek a `system_settings` táblában élnek (admin UI-n állítható).
    Ha nincs configolva, error kód és üzenet — nem fail-eli a systemd
    timer-t (egy nem-konfigurált rendszeren ne essen állandóan).
    """
    init_db()

    from app.modules.rendelo.malfini_stock import refresh_all_stocks

    with SessionLocal() as db:
        result = refresh_all_stocks(db)
    print(result.message)
    if result.ok:
        print(f"  Tétel összesen:    {result.items_total}")
        print(f"  Frissítve:         {result.items_updated}")
        print(f"  API-tól érkezett:  {result.api_returned}")
        print(f"  0-ra állítva:      {result.items_zeroed}")
    # Csak a "nincs configurálva" eset → exit 0 (nem hiba systemd szempontból)
    if not result.ok:
        if "Nincs Malfini B2B credential" in result.message:
            return 0
        return 1
    return 0


def cmd_seed_rendelo_categories(_args: argparse.Namespace) -> int:
    """A Rendelő modul alap-kategóriáit beülteti / frissíti idempotensen.

    A régi `nyomda_rendelo` rendszer 12 kategóriáját, név + sorrend +
    szín-hex hármasokkal. Meglévő név → szín és sort_order frissül.
    """
    init_db()

    from app.modules.rendelo.models import Category

    SEED: list[tuple[str, int, str]] = [
        ("Toner", 1, "#C5301F"),
        ("Festék", 20, "#F97316"),
        ("Papír", 30, "#FBBF24"),
        ("Vegyszer", 40, "#FEF3C7"),
        ("Gépkellék", 50, "#9CA3AF"),
        ("Iratfűzés", 60, "#A8A29E"),
        ("Bélyegző", 70, "#7F1D1D"),
        ("Póló", 80, "#65A30D"),
        ("Serleg/Érem/Üveg.", 90, "#D1D5DB"),
        ("Reklámajándék", 100, "#FB923C"),
        ("Ajándéktárgy", 110, "#6B7280"),
        ("EGYÉB", 120, "#8A8474"),
    ]

    with SessionLocal() as db:
        added = 0
        updated = 0
        for name, sort_order, color in SEED:
            existing = db.execute(
                select(Category).where(Category.name == name)
            ).scalar_one_or_none()
            if existing is None:
                db.add(Category(name=name, color=color, sort_order=sort_order))
                added += 1
                print(f"  + új: {name:<20}  {sort_order:>3}  {color}")
            else:
                changed = False
                if existing.color != color:
                    existing.color = color
                    changed = True
                if existing.sort_order != sort_order:
                    existing.sort_order = sort_order
                    changed = True
                if changed:
                    updated += 1
                    print(f"  → frissítve: {name:<20}  {sort_order:>3}  {color}")
        db.commit()
        print()
        print(f"Kész: {added} új, {updated} frissítve, {len(SEED) - added - updated} változatlan.")
    return 0


def cmd_generate_invite(args: argparse.Namespace) -> int:
    init_db()
    flags = _parse_roles(args.roles)
    if not any(flags.values()):
        print(
            "HIBA: legalább egy role-t adj meg --roles opcióval. " "Pl: --roles intake,designer",
            file=sys.stderr,
        )
        return 1

    with SessionLocal() as db:
        admin = (
            db.execute(select(User).where(User.is_admin.is_(True), User.active.is_(True)))
            .scalars()
            .first()
        )
        if admin is None:
            print("HIBA: nincs aktív admin. Először: hub create-admin", file=sys.stderr)
            return 1

        token = generate_token(32)
        invite = Invite(
            token=token,
            email_hint=args.email,
            created_by_id=admin.id,
            expires_at=utcnow() + timedelta(days=args.expires_days),
            **flags,
        )
        db.add(invite)
        db.commit()

        active = ", ".join(f.removeprefix("is_") for f, v in flags.items() if v)
        print(f"✓ Meghívó létrehozva. Role-ok: {active}")
        print(f"  Lejár: {invite.expires_at:%Y-%m-%d %H:%M} UTC")
        print(f"  Link:  {settings.base_url}/invite/{token}")
    return 0


def main() -> int:
    # Windows konzol cp1250 alapból nem tud minden Unicode karaktert (✓, ❯, …).
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(prog="hub", description="Hub CLI")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_admin = sub.add_parser("create-admin", help="Új admin user létrehozása (minden role aktív)")
    p_admin.add_argument("--name", required=True)
    p_admin.add_argument("--email", required=True)
    p_admin.add_argument(
        "--password",
        default=None,
        help="Ha nem adod meg, interaktívan, némán kéri (ajánlott).",
    )
    p_admin.set_defaults(func=cmd_create_admin)

    p_list = sub.add_parser("list-users", help="Userek listázása")
    p_list.set_defaults(func=cmd_list_users)

    p_inv = sub.add_parser(
        "generate-invite",
        help="Meghívó link generálás. Pl: --roles intake,designer",
    )
    valid_roles = ", ".join(f.removeprefix("is_") for f in ROLE_FLAGS)
    p_inv.add_argument(
        "--roles",
        required=True,
        help=f"Vesszővel elválasztott role-ok ({valid_roles}). Példa: intake,designer",
    )
    p_inv.add_argument("--email", help="Email hint (kihez küldöd)", default=None)
    p_inv.add_argument("--expires-days", type=int, default=7, help="Lejárat napokban (default: 7)")
    p_inv.set_defaults(func=cmd_generate_invite)

    p_rescan = sub.add_parser(
        "rescan-attachments",
        help="Csatolmányok újraszkennelése ClamAV-vel (pending/error/skipped)",
    )
    p_rescan.add_argument(
        "--all",
        action="store_true",
        help="A `clean` státuszúakat is újraszkenneli (pl. ha új vírus-def jött)",
    )
    p_rescan.set_defaults(func=cmd_rescan_attachments)

    p_seed_cats = sub.add_parser(
        "seed-rendelo-categories",
        help="A Rendelő alap-kategóriáit beülteti / frissíti (Toner, Festék, …)",
    )
    p_seed_cats.set_defaults(func=cmd_seed_rendelo_categories)

    p_reclass = sub.add_parser(
        "reclassify-emails",
        help="Emailek újra-osztályozása az aktuális AI provider-rel",
    )
    p_reclass.add_argument(
        "--all",
        action="store_true",
        help="A meglévő AI-eredményeket is átfuttatja (default: csak RULE_FALLBACK)",
    )
    p_reclass.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Max ennyi email-en futtatja (a legfrissebbektől)",
    )
    p_reclass.set_defaults(func=cmd_reclassify_emails)

    p_pricelist = sub.add_parser(
        "import-malfini-pricelist",
        help="Malfini Standard Pricelist CSV import — variant-szintű (méret+szín+kód) Item-ek",
    )
    p_pricelist.add_argument(
        "csv_path",
        help="A Malfini Standard Pricelist CSV-fájl elérési útja",
    )
    p_pricelist.add_argument(
        "--all",
        action="store_true",
        help="MINDEN CSV sort importál (~14,800). Default: csak az essential 26 modell (~2,054).",
    )
    p_pricelist.add_argument(
        "--keep-old",
        action="store_true",
        help="A meglévő Malfini Item-eket változatlanul hagyja. "
        "Default: a CSV-ben nem szereplő régiek inactive-ra mennek.",
    )
    p_pricelist.add_argument(
        "--dry-run",
        action="store_true",
        help="Nem commit-ol, csak számol",
    )
    p_pricelist.set_defaults(func=cmd_import_malfini_pricelist)

    p_stock = sub.add_parser(
        "refresh-malfini-stock",
        help="Malfini B2B → Item.stock_qty szinkronizáció (systemd timer hívja)",
    )
    p_stock.set_defaults(func=cmd_refresh_malfini_stock)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
