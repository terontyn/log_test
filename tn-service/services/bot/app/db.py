import os
import json
from typing import Any, Dict, Optional
import psycopg
from psycopg.rows import dict_row
DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("DATABASE_URL="): DATABASE_URL = DATABASE_URL.split("=", 1)[1].strip()
def db_connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)
def get_doc(doc_id: int) -> Optional[Dict[str, Any]]:
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM transport_documents WHERE id=%s", (doc_id,))
            return cur.fetchone()
def set_status(doc_id: int, status: str, error_reason: Optional[str] = None):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE transport_documents SET status=%s, error_reason=%s WHERE id=%s", (status, error_reason, doc_id))
        conn.commit()
def _apply_field_patch(ocr: Dict[str, Any], field: str, value: str) -> Dict[str, Any]:
    ocr = ocr or {}
    field = (field or "").strip().lower()
    value = (value or "").strip()
    if field in ("base", "loading_base", "loading_base.name", "base_name"):
        ocr.setdefault("loading_base", {})
        ocr["loading_base"]["name"] = value
        return ocr
    if field in ("base_addr", "loading_base.address", "address"):
        ocr.setdefault("loading_base", {})
        ocr["loading_base"]["address"] = value
        return ocr
    if field in ("date", "loading_date", "loading_date.value"):
        ocr.setdefault("loading_date", {})
        ocr["loading_date"]["value"] = value
        return ocr
    if field in ("driver", "driver_name", "driver_name.value"):
        ocr.setdefault("driver_name", {})
        ocr["driver_name"]["value"] = value
        return ocr
    if field in ("product", "product_type", "product_type.value"):
        ocr.setdefault("product_type", {})
        ocr["product_type"]["value"] = value
        return ocr
    if field in ("weight", "weight_kg", "weight_total", "weight_total.kg"):
        ocr.setdefault("weight_total", {})
        v = value.replace(" ", "").replace("\xa0", "")
        try:
            kg = int(float(v.replace(",", ".")))
            ocr["weight_total"]["kg"] = kg
            ocr["weight_total"]["value_tons"] = None
            ocr["weight_total"]["edited_by_user"] = True
        except Exception:
            ocr["weight_total"]["kg"] = None
            ocr["weight_total"]["value_tons"] = None
            ocr["weight_total"]["edited_by_user"] = True
            ocr["weight_total"]["source_label"] = f"user:{value}"
        return ocr
    ocr["notes"] = (ocr.get("notes") or "") + f"\nuser_edit {field}={value}"
    return ocr
def update_field(doc_id: int, field: str, value: str):
    doc = get_doc(doc_id)
    if not doc: return
    ocr = doc.get("ocr_data") or {}
    ocr2 = _apply_field_patch(ocr, field, value)
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE transport_documents SET ocr_data=%s::jsonb WHERE id=%s", (json.dumps(ocr2, ensure_ascii=False), doc_id))
        conn.commit()
def set_confirmed(doc_id: int):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE transport_documents SET status='confirmed', confirmed_at=NOW() WHERE id=%s", (doc_id,))
        conn.commit()
def set_bitrix_result(doc_id: int, status: str, payload: Dict[str, Any], resp: Dict[str, Any], err: str):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE transport_documents
                SET bitrix_status=%s,
                    bitrix_sent_at=CASE WHEN %s='sent' THEN NOW() ELSE bitrix_sent_at END,
                    bitrix_payload=%s::jsonb,
                    bitrix_response=%s::jsonb,
                    bitrix_error=%s
                WHERE id=%s
                """,
                (status, status, json.dumps(payload, ensure_ascii=False), json.dumps(resp, ensure_ascii=False), err, doc_id),
            )
        conn.commit()
