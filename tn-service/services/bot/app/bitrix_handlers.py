import logging
from app.db import get_doc, set_confirmed, set_bitrix_result
from app.bitrix_client import send_to_bitrix_sync
from app.formatting import format_for_driver

log = logging.getLogger("bitrix_handler")

async def handle_bitrix_callback(update, context) -> bool:
    query = update.callback_query
    if not query or not query.data.startswith("ok:"):
        return False

    doc_id = int(query.data.split(":")[1])
    doc = get_doc(doc_id)
    if not doc: 
        return True

    ocr = doc.get("ocr_data") or {}
    carrier = ocr.get("carrier_name", {}).get("value")
    
    if not carrier or carrier in ("—", "", None):
        await query.answer("⛔ ОШИБКА: Введите перевозчика перед подтверждением!", show_alert=True)
        return True

    await query.answer("🚀 Отправляю в Битрикс24 (может занять время из-за фото)...")
    
    try:
        msg_text = format_for_driver(doc_id, ocr, True, "", 1.0)
        
        # Читаем строку с путями и аккуратно разбиваем ее в список для отправки
        raw_paths = doc.get("photo_path")
        photo_paths = raw_paths.split(",") if raw_paths else []
        
        ok, resp, err, payload = send_to_bitrix_sync(text=msg_text, photo_paths=photo_paths)
        
        if ok:
            msg_id = str(resp.get("result", ""))
            set_confirmed(doc_id)
            set_bitrix_result(doc_id, msg_id, "success")
            await query.message.reply_text("✅ Успешно! Данные и все фото отправлены в Битрикс24.")
        else:
            log.error(f"Bitrix response error: {err}")
            await query.message.reply_text(f"❌ Ошибка отправки: {err}")
            
    except Exception as e:
        log.error(f"Bitrix Send Error: {e}")
        await query.message.reply_text(f"❌ Критическая ошибка: {e}")
    
    return True
