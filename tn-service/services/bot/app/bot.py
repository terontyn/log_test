import os, json, logging, redis, asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from app.db import set_status, update_field, get_doc
from app.formatting import format_for_driver
from app.bitrix_handlers import handle_bitrix_callback

logging.basicConfig(level=logging.INFO)
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
rds = redis.Redis.from_url(os.getenv("REDIS_URL"), decode_responses=True)

CHAT_BUFFERS = {}
EDIT_STATE = {}


def build_main_kb(doc_id, missing_carrier):
    kb = [
        [InlineKeyboardButton("🔄 Статус / Операция", callback_data=f"menu_op:{doc_id}")],
        [InlineKeyboardButton("📍 Локация выгрузки", callback_data=f"field:{doc_id}:unloading_address")],
    ]
    if missing_carrier:
        kb.append([InlineKeyboardButton("🚚 Ввести перевозчика", callback_data=f"field:{doc_id}:carrier_name")])
    kb.append([InlineKeyboardButton("✅ Подтвердить", callback_data=f"ok:{doc_id}")])
    kb.append([InlineKeyboardButton("✏️ Исправить", callback_data=f"edit:{doc_id}")])
    kb.append([InlineKeyboardButton("📸 Переснять", callback_data=f"reshoot:{doc_id}")])
    return InlineKeyboardMarkup(kb)


def build_op_kb(doc_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬆️ Загрузился", callback_data=f"set_op:{doc_id}:loading"),
            InlineKeyboardButton("⬇️ Выгрузился", callback_data=f"set_op:{doc_id}:unloading"),
        ],
        [
            InlineKeyboardButton("⛽ Залился", callback_data=f"set_op:{doc_id}:filling"),
            InlineKeyboardButton("💧 Слился", callback_data=f"set_op:{doc_id}:draining"),
        ],
        [InlineKeyboardButton("✍️ Свой статус", callback_data=f"field:{doc_id}:operation_type")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"back:{doc_id}")],
    ])


def build_edit_kb(doc_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Локация выгрузки", callback_data=f"field:{doc_id}:unloading_address")],
        [InlineKeyboardButton("Наименование перевозчика", callback_data=f"field:{doc_id}:carrier_name")],
        [InlineKeyboardButton("Грузоотправитель", callback_data=f"field:{doc_id}:sender_address")],
        [InlineKeyboardButton("Дата погрузки", callback_data=f"field:{doc_id}:loading_date")],
        [InlineKeyboardButton("ФИО водителя", callback_data=f"field:{doc_id}:driver_name")],
        [InlineKeyboardButton("Вес (кг)", callback_data=f"field:{doc_id}:weight_kg")],
        [InlineKeyboardButton("Вид продукции", callback_data=f"field:{doc_id}:product_type")],
        [InlineKeyboardButton("⬅️ Назад", callback_data=f"back:{doc_id}")]
    ])


async def flush_buffer(chat_id, context):
    await asyncio.sleep(3.0)
    if chat_id not in CHAT_BUFFERS:
        return
    files = CHAT_BUFFERS.pop(chat_id)
    if not files:
        return
    rds.rpush("tasks", json.dumps({"type": "batch", "chat_id": chat_id, "files": files}))
    await context.bot.send_message(chat_id, f"📥 Файлы ({len(files)} шт) приняты. Анализирую...")


async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    msg = update.message
    file_id = None
    if msg.photo:
        file_id = msg.photo[-1].file_id
    elif msg.document:
        file_id = msg.document.file_id
    elif msg.sticker:
        file_id = msg.sticker.file_id

    if not file_id:
        return
    if chat_id not in CHAT_BUFFERS:
        CHAT_BUFFERS[chat_id] = []
        asyncio.create_task(flush_buffer(chat_id, context))
    CHAT_BUFFERS[chat_id].append(file_id)


async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    if await handle_bitrix_callback(update, context):
        return
    await query.answer()

    if data.startswith("menu_op:"):
        doc_id = int(data.split(":")[1])
        await context.bot.send_message(chat_id, "👇 Что именно произошло?", reply_markup=build_op_kb(doc_id))

    elif data.startswith("set_op:"):
        _, did, op = data.split(":")
        doc_id = int(did)
        update_field(doc_id, "operation_type", op)
        doc = get_doc(doc_id)
        if doc:
            ocr = doc.get("ocr_data") or {}
            miss = not ocr.get("carrier_name", {}).get("value")
            msg = format_for_driver(doc_id, ocr, True, "", 1.0)
            await context.bot.send_message(chat_id, msg, reply_markup=build_main_kb(doc_id, miss))

    elif data.startswith("edit:"):
        doc_id = int(data.split(":")[1])
        await context.bot.send_message(chat_id, "Что именно нужно исправить?", reply_markup=build_edit_kb(doc_id))

    elif data.startswith("reshoot:"):
        await context.bot.send_message(chat_id, "📸 Пожалуйста, пришлите новое фото или альбом с накладной.")

    elif data.startswith("back:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        if doc:
            ocr = doc.get("ocr_data") or {}
            miss = not ocr.get("carrier_name", {}).get("value")
            msg = format_for_driver(doc_id, ocr, True, "", 1.0)
            await context.bot.send_message(chat_id, msg, reply_markup=build_main_kb(doc_id, miss))

    elif data.startswith("field:"):
        _, did, field = data.split(":")
        EDIT_STATE[chat_id] = {"doc_id": int(did), "field": field}
        prompt_map = {
            "carrier_name": "🚚 Введите Перевозчика:",
            "unloading_address": "📍 Введите Локацию выгрузки:",
            "sender_address": "🏭 Введите Грузоотправителя:",
            "loading_date": "📅 Введите Дату (ДД.ММ.ГГГГ):",
            "operation_type": "✍️ Напишите свой статус:",
        }
        await context.bot.send_message(chat_id, prompt_map.get(field, "Введите новое значение:"))


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = EDIT_STATE.pop(chat_id, None)
    if not state:
        return

    doc_id, field = state["doc_id"], state["field"]
    update_field(doc_id, field, update.message.text.strip())

    doc = get_doc(doc_id)
    ocr = doc.get("ocr_data") or {}
    miss = not ocr.get("carrier_name", {}).get("value")
    msg = format_for_driver(doc_id, ocr, True, "", 1.0)

    await update.message.reply_text(f"✅ Данные обновлены:\n\n{msg}", reply_markup=build_main_kb(doc_id, miss))


def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL | filters.Sticker.ALL, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.run_polling()


if __name__ == "__main__":
    main()
