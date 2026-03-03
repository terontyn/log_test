import re
from typing import Optional, Tuple

import psycopg
from psycopg.rows import dict_row
from app.config import DATABASE_URL


def keyify(name: str | None, address: str | None) -> str:
    s = f"{name or ''} {address or ''}".upper()
    # приводим к "словам"
    s = re.sub(r"[^A-ZА-ЯЁ0-9]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    # уберём очень общие слова
    stop = {"Г", "ГОР", "ГОРОД", "УЛ", "УЛИЦА", "Д", "ДОМ", "СТР", "СТРОЕНИЕ", "ОБЛ", "ОБЛАСТЬ",
            "РФ", "РОССИЯ", "МУНИЦИПАЛЬНЫЙ", "ОКРУГ", "ТЕР", "ВН", "ВНУТР"}
    toks = [t for t in s.split() if t not in stop and len(t) >= 3]
    return " ".join(toks)[:240] if toks else s[:240]


def extract_city(address: str | None) -> Optional[str]:
    a = (address or "").strip()
    if not a:
        return None
    m = re.search(r"(?:г\.?|город)\s*([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z\-]+)", a)
    if m:
        return m.group(1)
    m2 = re.search(r"^\s*([А-ЯЁA-Z][А-ЯЁа-яёA-Za-z\-]+)\s*,", a)
    if m2:
        return m2.group(1)
    return None


def get_or_create_canonical(name: str | None, address: str | None) -> Tuple[str, Optional[str]]:
    """
    Авто-справочник:
    - base_key = keyify(name, address)
    - canonical_name = пока что как в OCR (name)
    - city = из адреса
    Если запись уже есть — используем её.
    """
    base_key = keyify(name, address)
    canonical = (name or "").strip() or "—"
    city = extract_city(address)

    q = """
    INSERT INTO base_directory (base_key, canonical_name, city, examples_count, last_seen_at)
    VALUES (%s, %s, %s, 1, now())
    ON CONFLICT (base_key) DO UPDATE
      SET examples_count = base_directory.examples_count + 1,
          last_seen_at = now()
    RETURNING canonical_name, city;
    """

    with psycopg.connect(DATABASE_URL, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(q, (base_key, canonical, city))
            row = cur.fetchone()
            conn.commit()

    return row["canonical_name"], row.get("city")
