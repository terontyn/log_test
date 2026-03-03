def _g(d, *path, default="—"):
    cur = d or {}
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if cur not in (None, "") else default


def format_for_driver(doc_id: int, data: dict, ok: bool, reason: str, conf: float) -> str:
    addr = _g(data, "sender_address", "value")
    load_date = _g(data, "loading_date", "value")
    status_date = _g(data, "operation_date", "value", default=load_date if load_date != "—" else "—")
    driver = _g(data, "driver_name", "value")
    kg = _g(data, "weight_total", "kg")
    prod = _g(data, "product_type", "value")

    carrier = _g(data, "carrier_name", "value")
    unload = _g(data, "unloading_address", "value")
    op_type = _g(data, "operation_type", "value")

    status_map = {
        "loading": "⬆️ Загрузился",
        "unloading": "⬇️ Выгрузился",
        "filling": "⛽ Залился",
        "draining": "💧 Слился",
    }

    if op_type in status_map:
        op_str = f"{status_map[op_type]} ({status_date})"
    elif op_type and op_type != "—":
        op_str = f"📝 {op_type} ({status_date})"
    else:
        op_str = "—"

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
