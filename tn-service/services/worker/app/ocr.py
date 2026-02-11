import base64
import json
import os
import re
from datetime import datetime
from typing import Any, Dict, List
from PIL import Image, ImageEnhance, ImageOps
from openai import OpenAI

MODEL_VISION = os.getenv("OPENAI_OCR_MODEL", "gpt-5.2")

SYSTEM_PROMPT = """Ты — профессиональная система OCR для транспортных накладных (ТН, ТТН, УПД) на русском языке.
Твоя задача — извлечь конкретные сущности.
"""

USER_PROMPT_PASS1 = """Проанализируй изображение транспортной накладной.
Найди следующие данные:

1. **loading_base** (Базис/Грузоотправитель): Название компании и адрес погрузки.
2. **loading_date** (Дата): Дата отгрузки/погрузки (не путать с датой договора). Формат DD.MM.YYYY.
3. **driver_name** (Водитель): ФИО водителя.
   - Ищи в полях: "Водитель", "Водитель-экспедитор", "Принял", "Груз принял", "Перевозчик".
   - Часто написано от руки внизу документа.
   - Если есть только Фамилия И.О., извлеки как есть.
4. **product_type** (Груз): Наименование груза (Например: Дизельное топливо, Бензин, Щебень).
5. **weight_total** (Вес): Масса груза (Нетто/Брутто). Приоритет — Нетто.

Верни результат строго в JSON:
{
  "loading_base": { "name": string|null, "address": string|null, "city": string|null },
  "loading_date": { "value": "DD.MM.YYYY"|null, "source_label": string|null },
  "driver_name": { "value": string|null, "source_label": string|null },
  "product_type": { "value": string|null, "method": "single"|"multi"|null, "items": [string], "source_label": string|null },
  "weight_total": { "value_tons": number|null, "kg": integer|null, "source_label": string|null },
  "evidence": { "base": string|null, "date": string|null, "driver": string|null, "weight": string|null, "product": string|null },
  "missing": [string],
  "confidence": number,
  "need_second_pass": boolean,
  "second_pass_hints": [string]
}
"""

USER_PROMPT_PASS2 = """Второй проход. Уточняем данные.
Внимательно посмотри на обрезанные части (кропы).
ОСОБЕННОЕ ВНИМАНИЕ на ФИО ВОДИТЕЛЯ и ВЕС.
Если в первом проходе driver_name был null, поищи рукописный текст в нижней части документа или в графе "10. Перевозчик" / "16. Груз принял".
"""

def _b64_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")

def _save_variants(image_path: str) -> List[str]:
    img = Image.open(image_path)
    img = ImageOps.exif_transpose(img).convert("RGB")
    out_paths: List[str] = []
    base_dir = "/tmp/ocr_variants"
    os.makedirs(base_dir, exist_ok=True)
    def dump(im: Image.Image, suffix: str) -> str:
        p = os.path.join(base_dir, f"{os.path.basename(image_path)}.{suffix}.jpg")
        im.save(p, "JPEG", quality=92)
        out_paths.append(p)
        return p
    dump(img, "orig")
    im2 = ImageEnhance.Contrast(img).enhance(1.35)
    im2 = ImageEnhance.Sharpness(im2).enhance(1.25)
    dump(im2, "enh")
    w, h = img.size
    if w > h * 1.15:
        dump(img.rotate(90, expand=True), "rot90")
        dump(im2.rotate(90, expand=True), "enh_rot90")
    def crop_band(im: Image.Image, y0: float, y1: float) -> Image.Image:
        W, H = im.size
        return im.crop((0, int(H * y0), W, int(H * y1)))
    dump(crop_band(im2, 0.0, 0.40), "crop_top")
    dump(crop_band(im2, 0.30, 0.75), "crop_mid")
    dump(crop_band(im2, 0.60, 1.0), "crop_bot")
    return out_paths

def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^\s*```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```\s*$", "", t)
    return t.strip()

def _chat_json_from_images(images: List[str], user_prompt: str) -> Dict[str, Any]:
    client = OpenAI()
    content: List[Dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for p in images:
        b64 = _b64_image(p)
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"}
        })
    
    print(f"📡 Sending request to OpenAI model={MODEL_VISION}...")
    try:
        resp = client.chat.completions.create(
            model=MODEL_VISION,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            max_completion_tokens=1500, # Увеличили токены
            response_format={"type": "json_object"},
        )
    except Exception as e:
        print(f"❌ OpenAI API Request Error: {e}")
        return {"missing": ["API_ERROR"], "confidence": 0.0, "need_second_pass": False}

    text = resp.choices[0].message.content or ""
    print(f"🔍 DEBUG RAW RESPONSE: {text!r}")
    text = _strip_fences(text)
    
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"❌ JSON Decode Error: {e}. Raw text was: {text}")
        return {"missing": ["JSON_ERROR"], "confidence": 0.0, "need_second_pass": False}

def _merge_passes(p1: Dict[str, Any], p2: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(p1)
    def merge_obj(obj_key: str, fields: List[str]):
        a = p1.get(obj_key) or {}
        b = p2.get(obj_key) or {}
        m = dict(a)
        for f in fields:
            if b.get(f) not in (None, "", []):
                m[f] = b.get(f)
        out[obj_key] = m
    merge_obj("loading_base", ["name", "address", "city"])
    merge_obj("loading_date", ["value", "source_label"])
    merge_obj("driver_name", ["value", "source_label"])
    merge_obj("product_type", ["value", "method", "items", "source_label"])
    merge_obj("weight_total", ["value_tons", "kg", "source_label"])
    merge_obj("evidence", ["base", "date", "driver", "weight", "product"])
    missing = []
    if not (out.get("loading_base") or {}).get("name"): missing.append("loading_base.name")
    if not (out.get("loading_date") or {}).get("value"): missing.append("loading_date.value")
    if not (out.get("driver_name") or {}).get("value"): missing.append("driver_name.value")
    if not (out.get("product_type") or {}).get("value"): missing.append("product_type.value")
    wt = out.get("weight_total") or {}
    if wt.get("value_tons") is None and wt.get("kg") is None: missing.append("weight_total")
    out["missing"] = missing
    c1 = float(p1.get("confidence") or 0.0)
    c2 = float(p2.get("confidence") or 0.0)
    out["confidence"] = max(0.0, min(1.0, max(c1, c2)))
    out["need_second_pass"] = False
    out["second_pass_hints"] = []
    return out

def ocr_two_pass(image_path: str) -> Dict[str, Any]:
    variants = _save_variants(image_path)
    pass1 = []
    for suffix in ["orig", "enh", "enh_rot90", "rot90"]:
        for p in variants:
            if p.endswith(f".{suffix}.jpg"):
                pass1.append(p)
                break
    if not pass1: pass1 = [image_path]
    p1 = _chat_json_from_images(pass1[:3], USER_PROMPT_PASS1)
    need = bool(p1.get("need_second_pass")) or (float(p1.get("confidence") or 0.0) < 0.85) or (len(p1.get("missing") or []) > 0)
    if not need: return p1
    pass2 = []
    for suffix in ["enh", "enh_rot90", "crop_top", "crop_mid", "crop_bot", "orig", "rot90"]:
        for p in variants:
            if p.endswith(f".{suffix}.jpg"):
                pass2.append(p)
    pass2 = pass2[:6]
    p2 = _chat_json_from_images(pass2, USER_PROMPT_PASS2)
    return _merge_passes(p1, p2)

def extract(image_path: str) -> dict:
    return ocr_two_pass(image_path)
