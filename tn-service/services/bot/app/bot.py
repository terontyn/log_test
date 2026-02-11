import os
import json
import logging
import redis
from telegram.request import HTTPXRequest
from telegram.error import TimedOut
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler, CallbackQueryHandler,
    ContextTypes, filters
)
from app.db import set_status, update_field, get_doc
from app.bitrix_handlers import handle_bitrix_callback

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
log = logging.getLogger("tn_bot")

# ОТКЛЮЧАЕМ ШУМ HTTPX
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# Включаем логи битрикса
logging.getLogger("bitrix_client").setLevel(logging.INFO)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
rds = redis.Redis.from_url(REDIS_URL, decode_responses=True)
EDIT_STATE = {}

def build_main_keyboard(doc_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok:{doc_id}")],
        [InlineKeyboardButton("✏️ Исправить", callback_data=f"edit:{doc_id}")],
        [InlineKeyboardButton("📸 Переснять", callback_data=f"reshoot:{doc_id}")],
    ])

def build_edit_fields_keyboard(doc_id: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Базис погрузки", callback_data=f"field:{doc_id}:base_name")],
        [InlineKeyboardButton("Дата погрузки", callback_data=f"field:{doc_id}:loading_date")],
        [InlineKeyboardButton("ФИО водителя", callback_data=f"field:{doc_id}:driver_name")],
        [InlineKeyboardButton("Вес (кг)", callback_data=f"field:{doc_id}:weight_kg")],
        [InlineKeyboardButton("Вид продукции", callback_data=f"field:{doc_id}:product_type")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"back:{doc_id}")],
    ])

def format_doc_for_driver(doc):
    # Упрощенная версия для превью в боте
    data = doc["ocr_data"] or {}
    base = (data.get("loading_base") or {}).get("name") or "—"
    dt = (data.get("loading_date") or {}).get("value") or "—"
    driver = (data.get("driver_name") or {}).get("value") or "—"
    
    wt = data.get("weight_total") or {}
    kg = wt.get("kg")
    
    if kg:
        wt_str = f"{int(kg):,} кг".replace(",", " ")
    else:
        wt_str = "—"

    lines = [f"✅ Накладная #{doc['id']}"]
    lines.append(f"Базис: {base}")
    lines.append(f"Дата: {dt}")
    lines.append(f"Водитель: {driver}")
    lines.append(f"Вес: {wt_str}")
    return "\n".join(lines)

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.exception("❌ Bot error: %s", context.error)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    log.info("✅ /start chat_id=%s user_id=%s", update.effective_chat.id, update.effective_user.id)
    await update.message.reply_text("Отправьте фото/файл накладной (ТН/ТТН).")

async def enqueue_task(chat_id: int, file_id: str):
    task = {"type": "photo", "chat_id": chat_id, "file_id": file_id}
    rds.rpush("tasks", json.dumps(task, ensure_ascii=False))
    log.info("✅ Enqueued task chat_id=%s file_id=%s", chat_id, file_id)

async def on_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    file_id = update.message.photo[-1].file_id
    await enqueue_task(chat_id, file_id)
    await update.message.reply_text("Фото принято. Ожидайте...")

async def on_document_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    file_id = update.message.document.file_id
    await enqueue_task(chat_id, file_id)
    await update.message.reply_text("Файл принят. Ожидайте...")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        await query.answer()
        # Если это callback битрикса (подтверждение)
        if await handle_bitrix_callback(update, context): return

    q = update.callback_query
    data = q.data or ""
    chat_id = q.message.chat_id
    
    log.info(f"Callback: {data} chat_id={chat_id}")

    if data.startswith("reshoot:"):
        doc_id = int(data.split(":")[1])
        set_status(doc_id, "need_reshoot")
        await q.message.reply_text(f"📸 Переснимите накладную #{doc_id}.")
        return

    if data.startswith("edit:"):
        doc_id = int(data.split(":")[1])
        await q.message.reply_text("Что исправить?", reply_markup=build_edit_fields_keyboard(doc_id))
        return

    if data.startswith("back:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if not doc:
            await q.message.reply_text("Документ не найден.")
            return
        await q.message.reply_text(format_doc_for_driver(doc), reply_markup=build_main_keyboard(doc_id))
        return

    if data.startswith("field:"):
        _, doc_id_s, field = data.split(":", 2)
        doc_id = int(doc_id_s)
        EDIT_STATE[chat_id] = {"doc_id": doc_id, "field": field}
        prompts = {
            "base_name": "Введите Базис погрузки:",
            "loading_date": "Введите Дату (ДД.ММ.ГГГГ):",
            "driver_name": "Введите ФИО:",
            "weight_kg": "Введите Вес (кг):",
            "product_type": "Введите Продукцию:",
        }
        await q.message.reply_text(prompts.get(field, "Значение:"))
        return

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    txt = (update.message.text or "").strip()
    st = EDIT_STATE.get(chat_id)
    if not st: return
    
    doc_id = st["doc_id"]
    field = st["field"]
    
    try:
        update_field(doc_id, field, txt)
        set_status(doc_id, "edited")
    except Exception as e:
        await update.message.reply_text(f"Ошибка сохранения: {e}")
        return
    finally:
        EDIT_STATE.pop(chat_id, None)
    
    doc = get_doc(doc_id)
    # Возвращаем клавиатуру подтверждения после редактирования
    from app.formatting import format_for_driver 
    msg = format_for_driver(doc_id, doc["ocr_data"], True, "", doc["confidence"])
    
    await update.message.reply_text(
        "✅ Сохранено.\n\n" + msg, 
        reply_markup=build_main_keyboard(doc_id)
    )

def main():
    log.info("✅ Bot booting...")
    try:
        rds.ping()
        log.info("✅ Connected to Redis")
    except Exception as e:
        log.error("❌ Redis error: %s", e)
        
    app = Application.builder().token(TOKEN).request(HTTPXRequest(connect_timeout=20, read_timeout=40, write_timeout=40, pool_timeout=40)).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.PHOTO, on_photo))
    app.add_handler(MessageHandler(filters.Document.IMAGE, on_document_image))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(error_handler)
    
    log.info("✅ Handlers registered")
    app.run_polling()

if __name__ == "__main__":
    main()
