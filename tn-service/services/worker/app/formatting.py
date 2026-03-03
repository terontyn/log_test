def _g(d, *path, default="—"):
    cur = d or {}
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if cur not in (None, "") else default


def _short_name(full_name):
    if not full_name or full_name == "—":
        return "—"
    text = str(full_name).strip()
    parts = [x for x in text.replace(".", " ").split() if x]
    if len(parts) < 2:
        return text
    surname = parts[0]
    initials = " ".join([f"{p[0].upper()}." for p in parts[1:] if p])
    return f"{surname} {initials}".strip()


def _status_label(op_type):
    status_map = {
        "loading": "⬆️ Загрузился",
        "unloading": "⬇️ Выгрузился",
        "filling": "⛽ Залился",
        "draining": "💧 Слился",
    }
    if op_type in status_map:
        return status_map[op_type]
    return f"📝 {op_type}" if op_type and op_type != "—" else "—"


def _format_statuses(data, fallback_date):
    events = data.get("operation_events") if isinstance(data, dict) else None
    if isinstance(events, list) and events:
        chunks = []
        for e in events:
            if not isinstance(e, dict):
                continue
            label = _status_label(e.get("type"))
            date = e.get("date") or fallback_date
            chunks.append(f"{label} ({date})")
        if chunks:
            return " | ".join(chunks)

    op_type = _g(data, "operation_type", "value")
    status_date = _g(data, "operation_date", "value", default=fallback_date)
    label = _status_label(op_type)
    if label == "—":
        return "—"
    return f"{label} ({status_date})"


def format_for_driver(doc_id: int, data: dict, ok: bool, reason: str, conf: float) -> str:
    addr = _g(data, "sender_address", "value")
    load_date = _g(data, "loading_date", "value")
    driver = _short_name(_g(data, "driver_name", "value"))
    kg = _g(data, "weight_total", "kg")
    prod = _g(data, "product_type", "value")
    carrier = _g(data, "carrier_name", "value")
    unload = _g(data, "unloading_address", "value")

    op_str = _format_statuses(data or {}, load_date if load_date != "—" else "—")

    lines = [f"📄 **Накладная #{doc_id}**", ""]
    lines.append(f"Грузоотправитель: {addr}")
    lines.append(f"Дата погрузки: {load_date}")
    lines.append(f"Локация выгрузки: {unload}")
    lines.append(f"Наименование перевозчика: {carrier}")
    lines.append(f"ФИО водителя: {driver}")
    lines.append(f"Вес продукции: {kg} кг" if kg != "—" else "Вес продукции: —")
    lines.append(f"Вид продукции: {prod}")
    lines.append(f"Статус: {op_str}")

    errors = []
    if carrier == "—":
        errors.append("• Перевозчик")
    if unload == "—":
        errors.append("• Локация выгрузки")
    if op_str == "—":
        errors.append("• Статус (Загрузился/Слился)")

    if errors:
        lines.append("\n⛔ **НЕ ЗАПОЛНЕНЫ:**")
        lines.extend(errors)

    return "\n".join(lines).strip()
