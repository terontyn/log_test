from fastapi import FastAPI
import json, redis, os, requests, threading, time
from app.db import get_doc, update_field, add_operation_event, remove_last_operation_event, clear_operation_events
from app.formatting import format_for_driver

app = FastAPI(title="TN Service Polling")
rds = redis.Redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)

MAX_API_URL = "https://platform-api.max.ru"
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
HEADERS = {"Authorization": f"{MAX_TOKEN}"}
EDIT_STATE = {}

UNLOAD_SUGGESTIONS = [x.strip() for x in os.getenv("UNLOAD_SUGGESTIONS", "Нефтебаза,АЗС,Склад клиента").split(",") if x.strip()]
CARRIER_SUGGESTIONS = [x.strip() for x in os.getenv("CARRIER_SUGGESTIONS", "ИП,ООО,АО").split(",") if x.strip()]

FILE_BUFFER = {}
BUFFER_LOCK = threading.Lock()


def flush_buffer(chat_id):
    with BUFFER_LOCK:
        if chat_id not in FILE_BUFFER:
            return
        data = FILE_BUFFER.pop(chat_id)
    files = data["files"]
    if not files:
        return
    print(f"📦 Буфер сброшен. Файлов: {len(files)}", flush=True)
    rds.rpush("tasks", json.dumps({"type": "batch", "platform": "max", "chat_id": str(chat_id), "files": files}))
    send_max_message(chat_id, f"📥 Принято файлов: {len(files)}. Обрабатываю...")


def add_to_buffer(chat_id, new_urls):
    with BUFFER_LOCK:
        if chat_id in FILE_BUFFER:
            if FILE_BUFFER[chat_id].get("timer"):
                FILE_BUFFER[chat_id]["timer"].cancel()
            FILE_BUFFER[chat_id]["files"].extend(new_urls)
        else:
            FILE_BUFFER[chat_id] = {"files": new_urls}
        t = threading.Timer(2.5, flush_buffer, args=[chat_id])
        FILE_BUFFER[chat_id]["timer"] = t
        t.start()


def convert_kb(reply_markup):
    if not reply_markup or "inline_keyboard" not in reply_markup:
        return None
    max_buttons = []
    for row in reply_markup["inline_keyboard"]:
        max_row = []
        for btn in row:
            max_row.append({"type": "callback", "text": str(btn["text"]), "payload": str(btn.get("callback_data", btn.get("payload", "")))})
        max_buttons.append(max_row)
    return [{"type": "inline_keyboard", "payload": {"buttons": max_buttons}}]


def _extract_mid(resp_json):
    if not isinstance(resp_json, dict):
        return None
    for key in ("message_id", "mid"):
        if resp_json.get(key):
            return resp_json.get(key)

    result = resp_json.get("result")
    if isinstance(result, dict):
        if result.get("message_id"):
            return result.get("message_id")
        body = result.get("body")
        if isinstance(body, dict) and body.get("mid"):
            return body.get("mid")

    message = resp_json.get("message")
    if isinstance(message, dict):
        body = message.get("body")
        if isinstance(body, dict) and body.get("mid"):
            return body.get("mid")
    return None


def send_max_message(chat_id, text, reply_markup=None):
    body = {"text": text}
    atts = convert_kb(reply_markup)
    if atts:
        body["attachments"] = atts
    try:
        resp = requests.post(f"{MAX_API_URL}/messages", params={"chat_id": chat_id}, json=body, headers=HEADERS, timeout=20)
        if resp.ok:
            return _extract_mid(resp.json())
    except Exception:
        pass
    return None


def edit_max_message(mid, text, reply_markup=None):
    if not mid:
        return
    body = {"text": text}
    atts = convert_kb(reply_markup)
    body["attachments"] = atts if atts else []
    try:
        requests.put(f"{MAX_API_URL}/messages", params={"message_id": mid}, json=body, headers=HEADERS, timeout=20)
    except Exception:
        pass


def delete_max_message(mid):
    if not mid:
        return
    try:
        requests.delete(f"{MAX_API_URL}/messages", params={"message_id": mid}, headers=HEADERS, timeout=10)
    except Exception:
        pass


def answer_max_callback(callback_id):
    if not callback_id:
        return
    try:
        requests.post(f"{MAX_API_URL}/answers", params={"callback_id": callback_id}, json={}, headers=HEADERS, timeout=5)
    except Exception:
        pass


def build_main_kb(doc_id):
    return {"inline_keyboard": [
        [{"text": "🔄 Статус / Операция", "callback_data": f"menu_op:{doc_id}"}],
        [{"text": "📍 Локация выгрузки", "callback_data": f"menu_unload:{doc_id}"}],
        [{"text": "🚚 Перевозчик", "callback_data": f"menu_carrier:{doc_id}"}],
        [{"text": "✅ Подтвердить", "callback_data": f"ok:{doc_id}"}],
        [{"text": "✏️ Исправить", "callback_data": f"edit:{doc_id}"}],
    ]}


def build_op_kb(doc_id):
    return {"inline_keyboard": [
        [{"text": "⬆️ Загрузился", "callback_data": f"set_op:{doc_id}:loading"}, {"text": "⬇️ Выгрузился", "callback_data": f"set_op:{doc_id}:unloading"}],
        [{"text": "⛽ Залился", "callback_data": f"set_op:{doc_id}:filling"}, {"text": "💧 Слился", "callback_data": f"set_op:{doc_id}:draining"}],
        [{"text": "↩️ Удалить последний статус", "callback_data": f"rm_last_op:{doc_id}"}],
        [{"text": "🧹 Очистить все статусы", "callback_data": f"clear_ops:{doc_id}"}],
        [{"text": "✍️ Свой статус", "callback_data": f"field:{doc_id}:operation_type"}],
        [{"text": "⬅️ Назад", "callback_data": f"back:{doc_id}"}],
    ]}


def build_unload_kb(doc_id):
    rows = [[{"text": f"📍 {x}", "callback_data": f"set_unload:{doc_id}:{x}"}] for x in UNLOAD_SUGGESTIONS]
    rows.append([{"text": "✍️ Свой вариант", "callback_data": f"field:{doc_id}:unloading_address"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": f"back:{doc_id}"}])
    return {"inline_keyboard": rows}


def build_carrier_kb(doc_id):
    rows = [[{"text": f"🚚 {x}", "callback_data": f"set_carrier:{doc_id}:{x}"}] for x in CARRIER_SUGGESTIONS]
    rows.append([{"text": "✍️ Свой вариант", "callback_data": f"field:{doc_id}:carrier_name"}])
    rows.append([{"text": "⬅️ Назад", "callback_data": f"back:{doc_id}"}])
    return {"inline_keyboard": rows}


def build_edit_kb(doc_id):
    return {"inline_keyboard": [
        [{"text": "📍 Локация выгрузки", "callback_data": f"menu_unload:{doc_id}"}],
        [{"text": "🚚 Перевозчик", "callback_data": f"menu_carrier:{doc_id}"}],
        [{"text": "🏭 Грузоотправитель", "callback_data": f"field:{doc_id}:sender_address"}],
        [{"text": "👤 Водитель", "callback_data": f"field:{doc_id}:driver_name"}],
        [{"text": "📅 Дата погрузки", "callback_data": f"field:{doc_id}:loading_date"}],
        [{"text": "⚖️ Вес (кг)", "callback_data": f"field:{doc_id}:weight_kg"}],
        [{"text": "🛢 Вид продукции", "callback_data": f"field:{doc_id}:product_type"}],
        [{"text": "⬅️ Назад", "callback_data": f"back:{doc_id}"}],
    ]}


def _set_edit_state(chat_id, doc_id, field, original_mid, prompt_text, pending_op_type=None):
    prev = EDIT_STATE.get(chat_id)
    if prev:
        delete_max_message(prev.get("prompt_mid"))
    prompt_mid = send_max_message(chat_id, prompt_text)
    EDIT_STATE[chat_id] = {
        "doc_id": int(doc_id),
        "field": field,
        "original_mid": original_mid,
        "prompt_mid": prompt_mid,
        "pending_op_type": pending_op_type,
    }


def _render_doc(doc_id, mid):
    doc = get_doc(doc_id) or {}
    edit_max_message(mid, format_for_driver(doc_id, doc.get("ocr_data", {}), True, "", 1.0), reply_markup=build_main_kb(doc_id))


def handle_callback(chat_id, data, callback_id, mid):
    answer_max_callback(callback_id)

    if data.startswith("menu_op:"):
        doc_id = int(data.split(":")[1])
        edit_max_message(mid, "👇 Что именно произошло?", reply_markup=build_op_kb(doc_id))

    elif data.startswith("menu_unload:"):
        doc_id = int(data.split(":")[1])
        edit_max_message(mid, "👇 Выберите локацию выгрузки или введите свою:", reply_markup=build_unload_kb(doc_id))

    elif data.startswith("menu_carrier:"):
        doc_id = int(data.split(":")[1])
        edit_max_message(mid, "👇 Выберите наименование перевозчика или введите своё:", reply_markup=build_carrier_kb(doc_id))

    elif data.startswith("set_unload:"):
        _, did, value = data.split(":", 2)
        doc_id = int(did)
        update_field(doc_id, "unloading_address", value)
        _render_doc(doc_id, mid)

    elif data.startswith("set_carrier:"):
        _, did, value = data.split(":", 2)
        doc_id = int(did)
        update_field(doc_id, "carrier_name", value)
        _render_doc(doc_id, mid)

    elif data.startswith("set_op:"):
        _, did, op = data.split(":")
        doc_id = int(did)
        doc = get_doc(doc_id) or {}
        ocr = doc.get("ocr_data") or {}
        default_date = ocr.get("loading_date", {}).get("value", "")
        _set_edit_state(
            chat_id,
            doc_id,
            "operation_date",
            mid,
            f"📅 Введите дату для статуса '{op}' (ДД.ММ.ГГГГ).\nПо умолчанию: {default_date or '—'}\nОтправьте '+' чтобы оставить дату погрузки.",
            pending_op_type=op,
        )

    elif data.startswith("rm_last_op:"):
        doc_id = int(data.split(":")[1])
        remove_last_operation_event(doc_id)
        _render_doc(doc_id, mid)

    elif data.startswith("clear_ops:"):
        doc_id = int(data.split(":")[1])
        clear_operation_events(doc_id)
        _render_doc(doc_id, mid)

    elif data.startswith("edit:"):
        doc_id = int(data.split(":")[1])
        edit_max_message(mid, "🛠 **Выберите поле для исправления:**", reply_markup=build_edit_kb(doc_id))

    elif data.startswith("field:"):
        _, did, field = data.split(":")
        prompt_map = {
            "carrier_name": "🚚 Введите Перевозчика (ИП...):",
            "unloading_address": "📍 Введите Локацию выгрузки:",
            "sender_address": "🏭 Введите Грузоотправителя:",
            "loading_date": "📅 Введите Дату (ДД.ММ.ГГГГ):",
            "operation_type": "✍️ Напишите свой статус:",
            "operation_date": "📅 Введите дату статуса (ДД.ММ.ГГГГ):",
        }
        _set_edit_state(chat_id, int(did), field, mid, prompt_map.get(field, "✍️ Введите новое значение:"))

    elif data.startswith("back:"):
        doc_id = int(data.split(":")[1])
        _render_doc(doc_id, mid)

    elif data.startswith("ok:"):
        doc_id = int(data.split(":")[1])
        doc = get_doc(doc_id)
        ocr = doc.get("ocr_data") or {}
        errors = []
        if not ocr.get("carrier_name", {}).get("value"):
            errors.append("Перевозчик")
        if not ocr.get("unloading_address", {}).get("value"):
            errors.append("Локация выгрузки")
        if not ocr.get("operation_type", {}).get("value"):
            errors.append("Статус")

        if errors:
            edit_max_message(mid, f"⛔ **ЗАПОЛНИТЕ ПОЛЯ:** {', '.join(errors)}\n\n{format_for_driver(doc_id, ocr, True, '', 1.0)}", reply_markup=build_main_kb(doc_id))
            return

        edit_max_message(mid, "🚀 Отправляю в Битрикс24...")
        rds.rpush("tasks", json.dumps({"type": "bitrix_export", "platform": "max", "chat_id": str(chat_id), "doc_id": doc_id, "mid": mid}))


def process_update(update):
    update_type = update.get("update_type")
    if update_type == "message_callback":
        cb = update.get("callback", {})
        chat_id = update.get("message", {}).get("recipient", {}).get("chat_id")
        if chat_id and cb.get("payload"):
            threading.Thread(target=handle_callback, args=(chat_id, cb.get("payload"), cb.get("callback_id"), update.get("message", {}).get("body", {}).get("mid"))).start()
        return

    if update_type not in ["message_created", "bot_started"]:
        return

    msg_obj = update.get("message", {})
    chat_id = msg_obj.get("recipient", {}).get("chat_id") or update.get("chat_id")
    text = msg_obj.get("body", {}).get("text", "")
    attachments = msg_obj.get("body", {}).get("attachments", [])

    if not chat_id:
        return

    state = EDIT_STATE.pop(chat_id, None)
    if state and text and update_type != "bot_started":
        doc_id, field = state["doc_id"], state["field"]
        value = text.strip()

        if field == "operation_type":
            doc = get_doc(doc_id) or {}
            ocr = doc.get("ocr_data") or {}
            default_date = ocr.get("loading_date", {}).get("value", "")
            _set_edit_state(
                chat_id,
                doc_id,
                "operation_date",
                state.get("original_mid"),
                f"📅 Введите дату для статуса '{value}' (ДД.ММ.ГГГГ).\nПо умолчанию: {default_date or '—'}\nОтправьте '+' чтобы оставить дату погрузки.",
                pending_op_type=value,
            )
            delete_max_message(msg_obj.get("body", {}).get("mid"))
            return

        if field == "operation_date":
            if value in ("+", "＋", ""):
                doc = get_doc(doc_id) or {}
                value = (doc.get("ocr_data") or {}).get("loading_date", {}).get("value", "")
            latest_doc = get_doc(doc_id) or {}
            op_type = state.get("pending_op_type") or (latest_doc.get("ocr_data") or {}).get("operation_type", {}).get("value")
            add_operation_event(doc_id, op_type, value)
        else:
            update_field(doc_id, field, value)

        doc = get_doc(doc_id)
        msg_text = format_for_driver(doc_id, doc.get("ocr_data", {}), True, "", 1.0)
        if state.get("original_mid"):
            edit_max_message(state["original_mid"], msg_text, reply_markup=build_main_kb(doc_id))
        delete_max_message(state.get("prompt_mid"))
        delete_max_message(msg_obj.get("body", {}).get("mid"))
        return

    if update_type == "bot_started" or text.lower() == "старт":
        send_max_message(chat_id, "👋 Привет! Я бот Альфамонолит.\nПришлите фото накладной.")
        return

    urls = [a.get("payload", {}).get("url") for a in attachments if (a.get("type") in ["image", "file"]) and a.get("payload", {}).get("url")]
    if urls:
        add_to_buffer(chat_id, urls)


def polling_loop():
    marker = None
    while True:
        try:
            resp = requests.get(f"{MAX_API_URL}/updates", headers=HEADERS, params={"marker": marker} if marker else {}, timeout=60)
            if resp.status_code == 200:
                data = resp.json()
                if "marker" in data:
                    marker = data["marker"]
                for u in data.get("updates", []):
                    process_update(u)
            else:
                time.sleep(2)
        except Exception:
            time.sleep(5)


@app.on_event("startup")
def startup_event():
    threading.Thread(target=polling_loop, daemon=True).start()
