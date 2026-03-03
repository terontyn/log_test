import base64, json, os
from typing import List, Dict, Any, Tuple
from PIL import Image, ImageFilter, ImageStat
from openai import OpenAI

MODEL_VISION = os.getenv("OPENAI_OCR_MODEL", "gpt-5.2")

USER_PROMPT = """Ты — логистический ИИ-ассистент, эксперт по распознаванию российских транспортных накладных (ТН) и товарно-транспортных накладных (ТТН).
Внимательно изучи приложенные изображения. Твоя главная задача — точно определить "Грузоотправителя", не перепутав его с Поставщиком, Плательщиком или Грузополучателем.

ТИПОВЫЕ ФОРМАТЫ, КОТОРЫЕ ТЫ ВИДИШЬ:
1. ТТН (форма 1-Т): Грузоотправитель обычно указан в верхней части документа ПОСЛЕ "Поставщика" и ДО "Грузополучателя".
2. ТН (Транспортная накладная): Грузоотправитель указан в самом верху, в Разделе "1. Грузоотправитель".

ПРАВИЛА ИЗВЛЕЧЕНИЯ:
1. loading_date: Дата составления документа.
2. sender_address: Строго из поля "Грузоотправитель" (Название компании/ИП и адрес). ИГНОРИРУЙ поля "Поставщик" или "Заказчик".
3. driver_name: ФИО водителя. Ищи в блоках "Водитель", "Груз к перевозке принял" или в разделе "Перевозчик".
4. product_type: Наименование груза (например, "Дизельное топливо ЕВРО...", "Бензин моторный...").
5. weight_total: Масса груза нетто СТРОГО В КИЛОГРАММАХ (целое число). Если в документе указано "24,705 т", это 24705 кг. Не используй десятичные дроби.

Верни JSON строго по схеме:
{
  "reasoning": "Кратко (1 предложение) объясни, в каком блоке ты нашел грузоотправителя, чтобы доказать свою точность",
  "loading_date": { "value": "DD.MM.YYYY" },
  "sender_address": { "value": "Название компании, Адрес" },
  "carrier_name": { "value": null },
  "driver_name": { "value": "Фамилия И. О." },
  "product_type": { "value": "ДТ-Е-К5" },
  "weight_total": { "kg": 24705 },
  "confidence": 0.99
}
"""


def _signal_metrics(path: str) -> Tuple[float, float]:
    with Image.open(path) as img:
        gray = img.convert("L")
        entropy = gray.entropy()
        edge_img = gray.filter(ImageFilter.FIND_EDGES)
        edge_mean = ImageStat.Stat(edge_img).mean[0]
        return entropy, edge_mean


def select_images_for_ocr(image_paths: List[str]) -> List[str]:
    valid_paths = [p for p in image_paths if p and os.path.exists(p)]
    if not valid_paths:
        return []

    likely_doc = []
    rejected = []
    for p in valid_paths:
        try:
            entropy, edge_mean = _signal_metrics(p)
            if entropy >= 2.2 or edge_mean >= 9.0:
                likely_doc.append(p)
            else:
                rejected.append((p, entropy, edge_mean))
        except Exception:
            rejected.append((p, 0.0, 0.0))

    if likely_doc:
        if rejected:
            print("🧹 [OCR] Пропущены фото с низким текстовым сигналом:")
            for path, entropy, edge_mean in rejected:
                print(f"  - {path}: entropy={entropy:.2f}, edges={edge_mean:.2f}")
        print(f"🧹 [OCR] На OCR отправляем {len(likely_doc)}/{len(valid_paths)} изображений")
        return likely_doc

    print("⚠️ [OCR] Не нашли явно документные фото, отправляем все валидные изображения (fallback).")
    return valid_paths


def extract_batch(image_paths: List[str]) -> Dict[str, Any]:
    selected_paths = select_images_for_ocr(image_paths)
    if not selected_paths:
        raise RuntimeError("Не найдено ни одного валидного изображения для OCR")

    print(f"🧠 [OCR] Инициализация модели {MODEL_VISION} для {len(selected_paths)} изображений...")
    client = OpenAI()
    content = [{"type": "text", "text": USER_PROMPT}]

    for i, p in enumerate(selected_paths, 1):
        print(f"🧠 [OCR] Кодирование изображения {i}/{len(selected_paths)} в Base64: {p}")
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    print("🧠 [OCR] Отправка запроса к серверам OpenAI API...")
    resp = client.chat.completions.create(
        model=MODEL_VISION,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    print("🧠 [OCR] Ответ успешно получен! Разбор JSON...")
    result = json.loads(resp.choices[0].message.content)
    print(f"🧠 [OCR] Финальный вердикт ИИ:\n{json.dumps(result, indent=2, ensure_ascii=False)}")
    return result
