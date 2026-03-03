import os
import json
import base64
import urllib.request
import urllib.parse
import urllib.error
from typing import Optional, Tuple, Dict, Any, List

BITRIX_WEBHOOK_URL = os.getenv("BITRIX_WEBHOOK_URL", "").rstrip("/") + "/"
BITRIX_METHOD = os.getenv("BITRIX_METHOD", "im.message.add")
BITRIX_CHAT_ID = os.getenv("BITRIX_CHAT_ID", "chat0")

def _call(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    url = BITRIX_WEBHOOK_URL + method
    data = urllib.parse.urlencode(payload, doseq=True).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            raw = r.read().decode("utf-8", errors="replace")
        return json.loads(raw)
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"HTTP {e.code}", "error_description": raw}
    except Exception as e:
        return {"error": "Request Failed", "error_description": str(e)}

def _chat_numeric_id(chat_id: str) -> int:
    digits = "".join([c for c in (chat_id or "") if c.isdigit()])
    return int(digits or "0")

def _get_chat_folder_id(chat_num_id: int) -> int:
    resp = _call("im.disk.folder.get", {"CHAT_ID": chat_num_id})
    result = resp.get("result") or {}
    folder_id = int(result.get("ID") or 0)
    if not folder_id:
        raise RuntimeError(f"im.disk.folder.get failed: {resp}")
    return folder_id

def _upload_to_folder(folder_id: int, file_path: str) -> int:
    filename = os.path.basename(file_path)
    with open(file_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")

    resp = _call(
        "disk.folder.uploadfile",
        {
            "id": folder_id,
            "data[NAME]": filename,
            "fileContent[0]": filename,
            "fileContent[1]": b64,
        },
    )
    result = resp.get("result") or {}
    disk_id = int(result.get("ID") or result.get("id") or 0)
    if not disk_id:
        raise RuntimeError(f"disk.folder.uploadfile failed: {resp}")
    return disk_id

def _commit_file_to_chat(chat_num_id: int, disk_id: int) -> Dict[str, Any]:
    return _call("im.disk.file.commit", {"CHAT_ID": chat_num_id, "DISK_ID": disk_id})

def send_to_bitrix_sync(text: str, photo_paths: List[str] = None) -> Tuple[bool, Dict[str, Any], str, Dict[str, Any]]:
    payload_for_db: Dict[str, Any] = {"text": text, "photo_paths": photo_paths}

    try:
        chat_num_id = _chat_numeric_id(BITRIX_CHAT_ID)
        
        # 1) СНАЧАЛА загружаем и публикуем ФОТО по одному
        if photo_paths:
            folder_id = _get_chat_folder_id(chat_num_id)
            for path in photo_paths:
                clean_path = path.strip()
                if clean_path and os.path.exists(clean_path):
                    disk_id = _upload_to_folder(folder_id, clean_path)
                    _commit_file_to_chat(chat_num_id, disk_id)

        # 2) ПОТОМ отправляем ТЕКСТ (он будет под фотографиями)
        resp = _call(BITRIX_METHOD, {"DIALOG_ID": BITRIX_CHAT_ID, "MESSAGE": text})
        
        if "error" in resp:
            err_msg = f'{resp.get("error")}: {resp.get("error_description")}'
            return False, resp, err_msg, payload_for_db

        return True, resp, "", payload_for_db

    except Exception as e:
        return False, {}, repr(e), payload_for_db
