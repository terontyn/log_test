import os, json, psycopg
from psycopg.rows import dict_row

DATABASE_URL = os.getenv("DATABASE_URL", "").replace("DATABASE_URL=", "").strip("'\"")


def db_connect():
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_doc(doc_id):
    with db_connect() as conn:
        return conn.execute("SELECT * FROM transport_documents WHERE id=%s", (doc_id,)).fetchone()


def _save_ocr(doc_id, ocr):
    with db_connect() as conn:
        conn.execute(
            "UPDATE transport_documents SET ocr_data=%s::jsonb, status='edited' WHERE id=%s",
            (json.dumps(ocr, ensure_ascii=False), doc_id),
        )
        conn.commit()


def update_field(doc_id, field, value):
    doc = get_doc(doc_id)
    ocr = doc.get("ocr_data") or {}

    if field == "carrier_name":
        ocr.setdefault("carrier_name", {})["value"] = value
    elif field == "unloading_address":
        ocr.setdefault("unloading_address", {})["value"] = value
    elif field == "operation_type":
        ocr.setdefault("operation_type", {})["value"] = value
    elif field == "operation_date":
        ocr.setdefault("operation_date", {})["value"] = value
    elif field == "sender_address":
        ocr.setdefault("sender_address", {})["value"] = value
    elif field == "loading_date":
        ocr.setdefault("loading_date", {})["value"] = value
    elif field == "driver_name":
        ocr.setdefault("driver_name", {})["value"] = value
    elif field == "weight_kg":
        ocr.setdefault("weight_total", {})["kg"] = value
    elif field == "product_type":
        ocr.setdefault("product_type", {})["value"] = value

    _save_ocr(doc_id, ocr)


def add_operation_event(doc_id, op_type, op_date):
    doc = get_doc(doc_id)
    ocr = doc.get("ocr_data") or {}
    events = ocr.get("operation_events")
    if not isinstance(events, list):
        events = []
    events.append({"type": op_type, "date": op_date})
    ocr["operation_events"] = events
    ocr.setdefault("operation_type", {})["value"] = op_type
    ocr.setdefault("operation_date", {})["value"] = op_date
    _save_ocr(doc_id, ocr)


def remove_last_operation_event(doc_id):
    doc = get_doc(doc_id)
    ocr = doc.get("ocr_data") or {}
    events = ocr.get("operation_events")
    if not isinstance(events, list) or not events:
        ocr.setdefault("operation_type", {})["value"] = None
        ocr.setdefault("operation_date", {})["value"] = None
        _save_ocr(doc_id, ocr)
        return

    events.pop()
    ocr["operation_events"] = events
    if events:
        last = events[-1]
        ocr.setdefault("operation_type", {})["value"] = last.get("type")
        ocr.setdefault("operation_date", {})["value"] = last.get("date")
    else:
        ocr.setdefault("operation_type", {})["value"] = None
        ocr.setdefault("operation_date", {})["value"] = None
    _save_ocr(doc_id, ocr)


def clear_operation_events(doc_id):
    doc = get_doc(doc_id)
    ocr = doc.get("ocr_data") or {}
    ocr["operation_events"] = []
    ocr.setdefault("operation_type", {})["value"] = None
    ocr.setdefault("operation_date", {})["value"] = None
    _save_ocr(doc_id, ocr)


def set_status(doc_id, status):
    with db_connect() as conn:
        conn.execute("UPDATE transport_documents SET status=%s WHERE id=%s", (status, doc_id))
        conn.commit()


def set_confirmed(doc_id):
    with db_connect() as conn:
        conn.execute("UPDATE transport_documents SET status='confirmed', confirmed_at=NOW() WHERE id=%s", (doc_id,))
        conn.commit()


def set_bitrix_result(doc_id, deal_id, status):
    with db_connect() as conn:
        conn.execute("UPDATE transport_documents SET bitrix_deal_id=%s, bitrix_status=%s WHERE id=%s", (deal_id, status, doc_id))
        conn.commit()
