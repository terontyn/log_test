import os
import time
import requests
from requests.exceptions import RequestException
from .config import API_BASE, FILE_BASE, DOWNLOAD_DIR
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
def send_message(chat_id, text, reply_markup=None, attempts=3):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup is not None: payload["reply_markup"] = reply_markup
    last_err = None
    for i in range(1, attempts + 1):
        try:
            print(f"📤 TG sendMessage attempt {i}/{attempts} chat_id={chat_id}")
            resp = requests.post(f"{API_BASE}/sendMessage", json=payload, timeout=20)
            print(f"📤 TG HTTP {resp.status_code}: {resp.text[:300]}")
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok"): raise RuntimeError(f"Telegram ok=false: {data}")
            return True
        except Exception as e:
            last_err = e
            print(f"❌ TG sendMessage error attempt {i}: {repr(e)}")
            time.sleep(1.5)
    raise RuntimeError(f"TG sendMessage failed after {attempts} attempts: {last_err}")
def get_file_path(file_id):
    resp = requests.get(f"{API_BASE}/getFile", params={"file_id": file_id}, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"): raise RuntimeError(f"Telegram getFile ok=false: {data}")
    return data["result"]["file_path"]
def download_photo(file_id):
    path = get_file_path(file_id)
    url = f"{FILE_BASE}/{path}"
    local = f"{DOWNLOAD_DIR}/{file_id}.jpg"
    with requests.get(url, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(local, "wb") as f:
            for chunk in r.iter_content(1024 * 128):
                if chunk: f.write(chunk)
    return local
