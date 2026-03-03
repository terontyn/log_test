from .config import MIN_CONFIDENCE

def validate(data):
    carrier = data.get("carrier_name", {}).get("value")
    base = data.get("loading_base", {}).get("name")
    date = data.get("loading_date", {}).get("value")
    driver = data.get("driver_name", {}).get("value")
    
    conf = data.get("confidence", 0.0)
    
    missing = []
    if not carrier: missing.append("перевозчик")
    if not base: missing.append("база")
    if not date: missing.append("дата")
    if not driver: missing.append("водитель")
    
    if missing:
        return False, f"Не найдено: {', '.join(missing)}", conf
    
    if conf < MIN_CONFIDENCE:
        return False, f"Низкая уверенность ({conf:.2f})", conf
        
    return True, None, conf
