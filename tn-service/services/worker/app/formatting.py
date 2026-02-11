def _g(d, *path, default=""):
    cur = d or {}
    for p in path:
        if not isinstance(cur, dict): return default
        cur = cur.get(p)
        if cur is None: return default
    return cur

def format_for_driver(doc_id: int, data: dict, ok: bool, reason: str, conf: float) -> str:
    base_name = _g(data, "loading_base", "name")
    base_addr = _g(data, "loading_base", "address")
    base_city = _g(data, "loading_base", "city")
    date_val  = _g(data, "loading_date", "value")
    driver    = _g(data, "driver_name", "value")
    product   = _g(data, "product_type", "value")
    kg   = _g(data, "weight_total", "kg")
    tons = _g(data, "weight_total", "value_tons")

    weight = ""
    # Логика отображения веса
    if kg not in ("", None):
        try:
            # Форматируем кг: 21 936
            kg_int = int(float(kg))
            weight = f"{kg_int:,}".replace(",", " ") + " кг"
            
            # Если есть тонны или можем вычислить из кг
            t_val = tons
            if t_val is None:
                t_val = kg_int / 1000.0
            
            # Форматируем тонны: запятая, до 3 знаков, убираем лишние нули
            t_str = f"{float(t_val):.3f}".rstrip("0").rstrip(".")
            t_str = t_str.replace(".", ",")
            
            weight += f" (≈ {t_str} т)"
        except Exception:
            weight = f"{kg} кг"
    elif tons not in ("", None):
        t_str = str(tons).replace(".", ",")
        weight = f"{t_str} т"

    base_line = base_name or ""
    city = base_city or ""
    if not city and isinstance(base_addr, str):
        import re
        m = re.search(r"\bг\.\s*([А-ЯЁA-Z][А-ЯЁA-Zа-яёa-z\- ]{2,})", base_addr)
        if m: city = m.group(1).strip()
    if city: base_line = f"{base_line} ({city})" if base_line else f"({city})"

    lines = []
    lines.append(f"✅ Документ распознан (#{doc_id})")
    lines.append("")
    lines.append(f"Базис погрузки\t{base_line}".rstrip())
    if base_addr: lines.append(f"Адрес\t{base_addr}".rstrip())
    lines.append(f"Дата погрузки\t{date_val}".rstrip())
    lines.append(f"ФИО водителя\t{driver}".rstrip())
    lines.append(f"Вес продукции\t{weight}".rstrip())
    lines.append(f"Вид продукции\t{product}".rstrip())

    return "\n".join(lines).strip()
