"""ClamAV vírusszkenner integráció email csatolmányokhoz.

A `clamd` daemon-on keresztül működik (Unix socket vagy TCP).
Ha nincs elérhető ClamAV → graceful skip, nem blokkol.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.modules.jobs.email_models import EmailAttachment, ScanStatus

log = logging.getLogger(__name__)

_clamd = None
_clamd_available: bool | None = None


def _get_clamd():
    """Lazy init — egyszer próbálja meg a kapcsolatot."""
    global _clamd, _clamd_available  # noqa: PLW0603

    if _clamd_available is False:
        return None
    if _clamd is not None:
        return _clamd

    try:
        import pyclamd

        # Először Unix socket (macOS brew default + Linux)
        cd = pyclamd.ClamdUnixSocket()
        if cd.ping():
            _clamd = cd
            _clamd_available = True
            log.info("ClamAV elérhető (Unix socket)")
            return _clamd

        # Fallback: TCP (Docker, remote)
        cd = pyclamd.ClamdNetworkSocket()
        if cd.ping():
            _clamd = cd
            _clamd_available = True
            log.info("ClamAV elérhető (TCP 3310)")
            return _clamd

    except Exception as exc:
        log.debug("ClamAV nem elérhető: %s", exc)

    _clamd_available = False
    log.warning("ClamAV nem elérhető — csatolmányok szkennelése kimarad.")
    return None


def _interpret_clamd_result(result: dict | None) -> tuple[ScanStatus, str | None]:
    """A `cd.scan_stream` válaszának értelmezése.

    A pyclamd None-t ad ha tiszta, és `{'stream': ('FOUND', detail)}`-et
    ha találat van. Az `ERROR` is ide kerülhet.
    """
    if result is None:
        return ScanStatus.CLEAN, None
    status_str, detail = result.get("stream", ("ERROR", "unexpected response"))
    if status_str == "FOUND":
        return ScanStatus.INFECTED, detail
    if status_str == "ERROR":
        return ScanStatus.ERROR, detail
    return ScanStatus.CLEAN, None


def scan_bytes(data: bytes) -> tuple[ScanStatus, str | None]:
    """Memóriában lévő bytes szkennelése (instream).

    Akkor hasznos ha a fájl még nincs a fájlrendszeren — pl. UploadFile-ból
    olvasott bytes, és csak akkor mentenénk le, ha tiszta.

    Returns: (status, részlet) — pl. (INFECTED, "Win.Trojan.Agent-123")
    """
    cd = _get_clamd()
    if cd is None:
        return ScanStatus.SKIPPED, None

    try:
        result = cd.scan_stream(data)
        return _interpret_clamd_result(result)
    except Exception as exc:
        log.exception("ClamAV scan_bytes hiba (%d byte)", len(data))
        return ScanStatus.ERROR, str(exc)[:300]


def scan_file(filepath: Path) -> tuple[ScanStatus, str | None]:
    """Egyetlen fájl szkennelése (instream — a fájl tartalmát küldi a daemonnak).

    Az instream megoldás nem igényel fájlrendszer-hozzáférést a ClamAV
    daemon-tól, így AppArmor / ProtectSystem korlátozás mellett is működik.

    Returns: (status, részlet) — pl. (INFECTED, "Win.Trojan.Agent-123")
    """
    cd = _get_clamd()
    if cd is None:
        return ScanStatus.SKIPPED, None

    try:
        with open(filepath, "rb") as f:
            result = cd.scan_stream(f.read())
        return _interpret_clamd_result(result)
    except Exception as exc:
        log.exception("ClamAV scan hiba: %s", filepath.name)
        return ScanStatus.ERROR, str(exc)[:300]


def scan_attachment(attachment: EmailAttachment, upload_dir: Path) -> ScanStatus:
    """EmailAttachment rekord szkennelése — frissíti a scan_status/scan_result mezőket."""
    filepath = upload_dir / attachment.storage_path

    if not filepath.exists():
        attachment.scan_status = ScanStatus.ERROR
        attachment.scan_result = "Fájl nem található"
        return ScanStatus.ERROR

    status, detail = scan_file(filepath)
    attachment.scan_status = status
    attachment.scan_result = detail

    if status == ScanStatus.INFECTED:
        log.warning(
            "FERTŐZÖTT csatolmány: %s [%s] — %s",
            attachment.filename,
            attachment.email_id,
            detail,
        )
        quarantine_dir = upload_dir / "quarantine"
        quarantine_dir.mkdir(parents=True, exist_ok=True)
        quarantine_dest = quarantine_dir / f"{attachment.id}_{filepath.name}"
        filepath.rename(quarantine_dest)
        attachment.storage_path = str(quarantine_dest.relative_to(upload_dir))

    return status
