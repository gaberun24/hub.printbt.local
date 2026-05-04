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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
