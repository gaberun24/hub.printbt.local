"""Rendelő igényekhez tartozó képek feltöltése.

Pillow-val auto-orientation (EXIF-rotation), max 1600px oldalra méretezés,
JPEG újrakódolás (quality 85). EXIF metadata strippelve a privacy miatt.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from PIL import Image, ImageOps

from app.shared.config import settings

if TYPE_CHECKING:
    from fastapi import UploadFile

MAX_DIMENSION = 1600  # px — kisebbre méretezzük a feltöltött képet
JPEG_QUALITY = 85
ALLOWED_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

UPLOADS_SUBDIR = "rendelo"


def save_uploaded_image(upload: UploadFile) -> str | None:
    """Feltöltött kép mentése JPEG-ként, EXIF-orientáció alapján forgatva,
    és a `MAX_DIMENSION`-be méretezve.

    Visszatérési érték: a fájlnév az `uploads/rendelo/`-n belül (relatív path),
    vagy `None` ha nincs feltöltött fájl. ValueError ha nem támogatott típus.
    """
    if not upload or not upload.filename:
        return None

    if upload.content_type not in ALLOWED_TYPES:
        raise ValueError(f"Nem támogatott fájltípus: {upload.content_type}")

    img = Image.open(upload.file)
    img = ImageOps.exif_transpose(img)  # auto-orientation
    img.thumbnail((MAX_DIMENSION, MAX_DIMENSION), Image.Resampling.LANCZOS)

    if img.mode != "RGB":
        img = img.convert("RGB")

    out_dir = settings.upload_dir / UPLOADS_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}.jpg"
    out_path = out_dir / filename
    # EXIF strippelés a privacy miatt — nem rakunk vissza adatot
    img.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)

    return f"{UPLOADS_SUBDIR}/{filename}"
