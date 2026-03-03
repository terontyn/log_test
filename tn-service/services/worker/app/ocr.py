import base64, json, os
from typing import List, Dict, Any, Tuple
from PIL import Image, ImageFilter, ImageStat
from openai import OpenAI

MODEL_VISION = os.getenv("OPENAI_OCR_MODEL", "gpt-5.2")
MIN_ENTROPY = float(os.getenv("OCR_MIN_ENTROPY", "2.2"))
MIN_EDGE_MEAN = float(os.getenv("OCR_MIN_EDGE_MEAN", "9.0"))

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
    total_input = len(image_paths)
    valid_paths = [p for p in image_paths if p and os.path.exists(p)]
    invalid_count = total_input - len(valid_paths)

    print(
        f"🧾 [OCR] Статистика входа: всего={total_input}, валидных={len(valid_paths)}, невалидных={invalid_count}, "
        f"порог entropy>={MIN_ENTROPY}, edges>={MIN_EDGE_MEAN}"
    )

    if not valid_paths:
        return []

    likely_doc = []
    rejected = []

    for p in valid_paths:
        try:
            entropy, edge_mean = _signal_metrics(p)
            if entropy >= MIN_ENTROPY or edge_mean >= MIN_EDGE_MEAN:
                likely_doc.append((p, entropy, edge_mean))
            else:
                rejected.append((p, entropy, edge_mean))
        except Exception:
            rejected.append((p, 0.0, 0.0))

    if likely_doc:
        print(
            f"🧾 [OCR] Отбор: отправим={len(likely_doc)}, пропустим={len(rejected)}, "
            f"валидных={len(valid_paths)}"
        )
        if rejected:
            print("🧹 [OCR] Пропущены фото с низким текстовым сигналом:")
            for path, entropy, edge_mean in rejected:
                print(f"  - {path}: entropy={entropy:.2f}, edges={edge_mean:.2f}")
        return [p for p, _, _ in likely_doc]

    print(
        "⚠️ [OCR] Документные фото не определены по эвристике; fallback: отправляем все валидные "
        f"({len(valid_paths)}/{total_input})."
    )
    return valid_paths


def extract_batch(image_paths: List[str]) -> Dict[str, Any]:
    selected_paths = select_images_for_ocr(image_paths)
    if not selected_paths:
        raise RuntimeError("Не найдено ни одного валидного изображения для OCR")

    skipped = len(image_paths) - len(selected_paths)
    print(f"🧠 [OCR] К отправке в OpenAI: {len(selected_paths)} шт.; пропущено: {skipped} шт.")
    print(f"🧠 [OCR] Инициализация модели {MODEL_VISION}...")

    client = OpenAI()
    content = [{"type": "text", "text": USER_PROMPT}]

    for i, p in enumerate(selected_paths, 1):
        print(f"🧠 [OCR] Кодирование изображения {i}/{len(selected_paths)}: {p}")
        with open(p, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("ascii")
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    print("🧠 [OCR] Отправка запроса к OpenAI API...")
    resp = client.chat.completions.create(
        model=MODEL_VISION,
        messages=[{"role": "user", "content": content}],
        response_format={"type": "json_object"},
        temperature=0.0,
    )

    print("🧠 [OCR] Ответ получен, разбор JSON...")
    result = json.loads(resp.choices[0].message.content)
    print(f"🧠 [OCR] Финальный вердикт ИИ:\n{json.dumps(result, indent=2, ensure_ascii=False)}")
    return result
