import os
import json
import base64
import logging
import urllib.request
import urllib.parse
from typing import Optional, Tuple, Dict, Any

log = logging.getLogger("bitrix_client")

BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "").rstrip("/") + "/"
BITRIX_METHOD = os.getenv("BITRIX_METHOD", "im.message.add")
BITRIX_CHAT_ID = os.getenv("BITRIX_CHAT_ID", "chat0")

def _get_base_domain(webhook_url: str) -> str:
    parsed = urllib.parse.urlparse(webhook_url)
    return f"{parsed.scheme}://{parsed.netloc}"

def _call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = BITRIX_WEBHOOK_URL + method
    log.info(f"BX CALL: {method} keys={list(payload.keys())}")
    
    data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(req, timeout=40) as r:
            raw = r.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except Exception as e:
        log.error(f"BX FAIL {method}: {e}")
        return {"error": "http_error", "error_description": str(e)}

def _chat_numeric_id(chat_id: str) -> int:
    """Превращает 'chat55161' -> 55161 (int)"""
    digits = "".join([c for c in (chat_id or "") if c.isdigit()])
    return int(digits or "0")

def _get_storage_id() -> int:
    resp = _call("disk.storage.getlist", {})
    result = resp.get("result") or []
    if not result:
        return 0
    return int(result[0].get("ID") or 0)

def _get_or_create_root_folder(storage_id: int, folder_name: str) -> int:
    # 1. Поиск
    resp = _call("disk.storage.getchildren", {"id": storage_id})
    children = resp.get("result") or []
    for child in children:
        if child.get("NAME") == folder_name and child.get("TYPE") == "folder":
            return int(child.get("ID"))
    # 2. Создание
    resp = _call("disk.storage.addfolder", {"id": storage_id, "data[NAME]": folder_name})
    result = resp.get("result") or {}
    return int(result.get("ID") or 0)

def _get_or_create_subfolder(parent_id: int, folder_name: str) -> int:
    # 1. Поиск
    resp = _call("disk.folder.getchildren", {"id": parent_id})
    children = resp.get("result") or []
    for child in children:
        if child.get("NAME") == folder_name and child.get("TYPE") == "folder":
            return int(child.get("ID"))
    # 2. Создание
    resp = _call("disk.folder.addsubfolder", {"id": parent_id, "data[NAME]": folder_name})
    result = resp.get("result") or {}
    return int(result.get("ID") or 0)

def _upload_file_to_folder(folder_id: int, file_path: str) -> Dict[str, Any]:
    filename = os.path.basename(file_path)
    if not os.path.exists(file_path):
        raise RuntimeError(f"File not found: {file_path}")

    with open(file_path, "rb") as f:
        file_data = f.read()
    b64 = base64.b64encode(file_data).decode("ascii")

    resp = _call("disk.folder.uploadfile", {
        "id": folder_id,
        "data[NAME]": filename,
        "fileContent[0]": filename,
        "fileContent[1]": b64
    })
    
    result = resp.get("result") or {}
    if not result.get("ID"):
        raise RuntimeError(f"Upload failed: {resp}")
    return result

def send_to_bitrix_sync(text: str, photo_path: Optional[str] = None) -> Tuple[bool, Dict[str, Any], str, Dict[str, Any]]:
    payload_for_db = {"text": text, "photo_path": photo_path}
    
    try:
        base_domain = _get_base_domain(BITRIX_WEBHOOK_URL)
        disk_id = 0
        full_url = ""
        folder_path_log = ""
        
        chat_num_id = _chat_numeric_id(BITRIX_CHAT_ID) # ОБЯЗАТЕЛЬНО числовой ID для commit

        # --- 1. ЗАГРУЗКА ФАЙЛА ---
        if photo_path:
            try:
                storage_id = _get_storage_id()
                if storage_id:
                    it_id = _get_or_create_root_folder(storage_id, "it")
                    if it_id:
                        folder_id = _get_or_create_subfolder(it_id, "Telegram_Logist")
                        if folder_id:
                             folder_path_log = "it/Telegram_Logist"
                             file_res = _upload_file_to_folder(folder_id, photo_path)
                             disk_id = int(file_res.get("ID") or 0)
                             detail_url = file_res.get("DETAIL_URL") or ""
                             
                             if disk_id:
                                log.info(f"Photo uploaded to {folder_path_log}. DiskID={disk_id}")
                                payload_for_db["disk_id"] = disk_id
                                payload_for_db["url"] = detail_url
                                
                                if detail_url:
                                    if not detail_url.startswith("http"):
                                        full_url = base_domain + detail_url
                                    else:
                                        full_url = detail_url
            except Exception as e:
                log.error(f"Photo upload error: {e}")

        # --- 2. ОТПРАВКА СООБЩЕНИЙ ---

        # Сообщение А: Отдельное фото через COMMIT (Самый надежный способ)
        photo_sent = False
        if disk_id and chat_num_id:
            try:
                log.info(f"Committing file {disk_id} to chat {chat_num_id}...")
                # Важно: CHAT_ID здесь должно быть числом (не chat55161, а 55161)
                commit_resp = _call("im.disk.file.commit", {
                    "CHAT_ID": chat_num_id, 
                    "DISK_ID": disk_id
                })
                if "error" not in commit_resp:
                    photo_sent = True
                    log.info("Photo committed successfully.")
                else:
                    log.error(f"Commit failed: {commit_resp}")
            except Exception as e:
                log.error(f"Commit exception: {e}")

        # Резерв: Если commit не сработал, пробуем message.add с FILES[0]
        if disk_id and not photo_sent:
             try:
                log.info("Fallback: Sending message with FILES[0]...")
                _call(BITRIX_METHOD, {
                    "DIALOG_ID": BITRIX_CHAT_ID, 
                    "MESSAGE": "📄 Скан накладной", 
                    "FILES[0]": disk_id
                })
             except Exception as e:
                log.error(f"Fallback failed: {e}")

        # Сообщение Б: Текст + Ссылка
        if full_url:
             text += f"\n\n[URL={full_url}]📂 Открыть файл ({folder_path_log})[/URL]"

        log.info("Sending Message 2 (Text)...")
        resp = _call(BITRIX_METHOD, {"DIALOG_ID": BITRIX_CHAT_ID, "MESSAGE": text})
        
        if "error" in resp:
            return False, resp, str(resp), payload_for_db

        return True, resp, "", payload_for_db

    except Exception as e:
        log.exception("Global Bitrix error")
        return False, {}, str(e), payload_for_db
