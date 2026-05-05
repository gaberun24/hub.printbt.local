"""Malfini Standard Pricelist termék-név parser és színhex-térkép.

A CSV-ből importált variant-Item neve (`Item.name`) ezt a magyar formátumot
követi (mind a 2054 essential variansra ellenőrizve, 100%-os találat):

    <MODEL_NAME> <VARIANT_TYPE> <GENDER> <COLOR> <SIZE>

Példák:
    "Classic póló gyerek piros 122 cm/6 éves"
    "Heavy V-neck póló unisex fekete 2XL"
    "Cotton Heavy galléros póló férfi mandarinsárga XL"

A parser a Hungarian gender-szót (`férfi`/`női`/`gyerek`/`unisex`/`junior`) +
size token-eket (felnőtt: XS..6XL, gyerek: "X cm/Y éves") detektálja,
és ezekből vissza-számolja a `model_label` és `color_label` mezőket.

A cascading-dropdown UI ezt használja:
    Modell ▼      → "100 — Classic póló gyerek"
    Szín ▼        → "🟥 garnet"  (a hex térképben)
    Méret ▼       → "110 cm/4 éves"
"""

from __future__ import annotations

import re
from typing import NamedTuple

# Felnőtt méret-tokenek (utolsó token a névben)
ADULT_SIZES: frozenset[str] = frozenset(
    {"XS", "S", "M", "L", "XL", "XXL", "2XL", "3XL", "4XL", "5XL", "6XL"}
)

# Gender-szavak — a név pattern szerint a gender ELŐTT a model+variant van,
# UTÁNA a color + size.
GENDERS: tuple[str, ...] = ("férfi", "női", "gyerek", "unisex", "junior")

# Gyerek-méret minta: "110 cm/4 éves", "122 cm/6 éves", stb.
KIDS_SIZE_RE = re.compile(r"\d+\s*cm[/ ]\d+\s*éves", re.IGNORECASE)


class ParsedItem(NamedTuple):
    model_label: str  # "Classic póló gyerek"
    color_label: str  # "garnet"
    size_label: str  # "XS" vagy "110 cm/4 éves"


def parse_malfini_name(name: str) -> ParsedItem | None:
    """Hungarian név → (model_label, color_label, size_label).

    None ha nem parsolható (nem-Malfini formátumú név). Nem-essential
    Malfini variants is be tudják adni — ha követik a pattern-t.
    """
    name = (name or "").strip()
    if not name:
        return None

    # ── Step 1: méret a végén ──────────────────────────────────────────
    kids = KIDS_SIZE_RE.search(name)
    if kids:
        size_label = kids.group(0)
        rest = name[: kids.start()].rstrip()
    else:
        # Felnőtt méret = utolsó token
        parts = name.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].upper() in ADULT_SIZES:
            size_label = parts[1]
            rest = parts[0]
        else:
            return None

    # ── Step 2: gender pozíció a maradékban ────────────────────────────
    rest_lower = rest.lower()
    for gender in GENDERS:
        # " <gender> " pattern (gender körül szóköz, így nem matchel "férfias"-ra)
        needle = " " + gender + " "
        idx = rest_lower.find(needle)
        if idx >= 0:
            # model_label = a gender INCLUSIVE-ig (értelmes label)
            model_label = rest[: idx + len(gender) + 1].strip()
            color_label = rest[idx + len(gender) + 2 :].strip()
            return ParsedItem(model_label, color_label, size_label)

    return None


def size_sort_key(size: str) -> tuple[int, int | str]:
    """Méret-sorrend: XS<S<M<L<XL<2XL<…, gyerek pedig életkor szerint."""
    order = {
        "XS": 0,
        "S": 1,
        "M": 2,
        "L": 3,
        "XL": 4,
        "XXL": 5,
        "2XL": 5,
        "3XL": 6,
        "4XL": 7,
        "5XL": 8,
        "6XL": 9,
    }
    su = size.upper()
    if su in order:
        return (0, order[su])
    # Gyerek méret — első szám a "110 cm/4 éves"-ből
    m = re.match(r"(\d+)", size)
    if m:
        return (1, int(m.group(1)))
    return (2, size)


# ─── Hungarian color → CSS hex térkép ──────────────────────────────────────
# Az 49 egyedi színből a top ~35-öt fedi le. A többi `#9ca3af` (semleges
# szürke) marad — vizuálisan kevésbé hasznos, de a UI nem tört el.
HU_COLOR_HEX: dict[str, str] = {
    "fehér": "#FFFFFF",
    "fekete": "#0F0F0F",
    "piros": "#DC2626",
    "sárga": "#FBBF24",
    "narancssárga": "#F97316",
    "mandarinsárga": "#FB923C",
    "citrom": "#FACC15",
    "lila": "#7C3AED",
    "rózsaszín": "#EC4899",
    "bíborszín": "#7C2D12",
    "bordó": "#7F1D1D",
    # Kék árnyalatok
    "királykék": "#1E40AF",
    "tengerészkék": "#1E3A5F",
    "égszínkék": "#38BDF8",
    "azúrkék": "#0EA5E9",
    "éjkék": "#1E1B4B",
    "sötétkék": "#1E3A8A",
    # Zöld árnyalatok
    "üvegzöld": "#0F5132",
    "fűzöld": "#65A30D",
    "almazöld": "#4ADE80",
    "lime": "#84CC16",
    "menta": "#6EE7B7",
    "borsózöld": "#94BC42",
    "dark green": "#14532D",
    "khaki": "#A8A29E",
    "military": "#4A5D23",
    # Türkiz
    "türkiz": "#14B8A6",
    "sötét türkiz": "#0E7490",
    # Szürke / semleges
    "sötétszürke melírozott": "#4B5563",
    "világosszürke melírozott": "#9CA3AF",
    "ébenszürke": "#1F2937",
    "antracit": "#404040",
    "ezüstszürke": "#C0C0C0",
    # Föld-tónus
    "homok": "#D4A574",
    "kávé": "#6B4423",
    "garnet": "#7E2D40",
    "mályva": "#C026D3",
    # Camouflage
    "szürke terepszín": "#4A4A30",
    "zöld terepszín": "#3D5023",
    "homok terepszín": "#A89360",
}


def get_color_hex(color_label: str) -> str:
    """HU szín-név → CSS hex. Ismeretlen szín → semleges szürke (#9CA3AF)."""
    if not color_label:
        return "#9CA3AF"
    return HU_COLOR_HEX.get(color_label.lower().strip(), "#9CA3AF")
