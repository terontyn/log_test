from .config import MIN_CONFIDENCE
def _conf(obj, *path):
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur: return 0.0
        cur = cur[p]
    try: return float(cur)
    except Exception: return 0.0
def _val(obj, *path):
    cur = obj
    for p in path:
        if not isinstance(cur, dict) or p not in cur: return None
        cur = cur[p]
    return cur
def validate(data):
    c_base = _conf(data, "loading_base", "confidence")
    c_date = _conf(data, "loading_date", "confidence")
    c_driver = _conf(data, "driver_name", "confidence")
    c_prod = _conf(data, "product_type", "confidence")
    c_wt = _conf(data, "weight_total", "confidence")
    conf = min([x for x in [c_base, c_date, c_driver, c_prod, c_wt] if x > 0] or [0.0])
    base_name = _val(data, "loading_base", "name")
    date_val = _val(data, "loading_date", "value")
    driver_val = _val(data, "driver_name", "value")
    prod_val = _val(data, "product_type", "value")
    wt_val = _val(data, "weight_total", "value")
    missing = []
    if not base_name: missing.append("база (название)")
    if not date_val: missing.append("дата погрузки")
    if not driver_val: missing.append("ФИО водителя")
    if not prod_val: missing.append("вид продукции")
    if wt_val is None: missing.append("вес")
    if missing: return False, "Не найдено: " + ", ".join(missing), conf
    if conf < MIN_CONFIDENCE: return False, f"Низкая уверенность распознавания ({conf:.2f})", conf
    return True, None, conf
