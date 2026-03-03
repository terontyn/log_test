def _g(d, *path, default="—"):
    cur = d or {}
    for p in path:
        cur = cur.get(p) if isinstance(cur, dict) else None
    return cur if cur not in (None, "") else default

def format_for_driver(doc_id: int, data: dict, ok: bool, reason: str, conf: float) -> str:
    addr    = _g(data, "sender_address", "value")
    date    = _g(data, "loading_date", "value")
    carrier = _g(data, "carrier_name", "value") # Тут всегда будет null из OCR
    driver  = _g(data, "driver_name", "value")
    kg      = _g(data, "weight_total", "kg")
    prod    = _g(data, "product_type", "value")

    lines = [f"✅ Накладная #{doc_id}", ""]
    lines.append(f"Грузоотправитель: {addr}")
    lines.append(f"Дата погрузки: {date}")
    lines.append(f"Наименование перевозчика — {carrier}")
    lines.append(f"ФИО водителя: {driver}")
    lines.append(f"Вес продукции: {kg} кг" if kg != "—" else "Вес продукции: —")
    lines.append(f"Вид продукции: {prod}")

    if carrier == "—":
        lines.append("\n⚠️ Обязательное поле: «Наименование перевозчика».")
        lines.append("Нажмите кнопку «🚚 Ввести перевозчика» ниже.")

    return "\n".join(lines).strip()
