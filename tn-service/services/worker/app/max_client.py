import os, time, requests
from PIL import Image
from .config import DOWNLOAD_DIR

os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_API_URL = "https://platform-api.max.ru"
MAX_TOKEN = os.getenv("MAX_BOT_TOKEN")
HEADERS = {"Authorization": f"{MAX_TOKEN}"}

def send_message(chat_id, text, reply_markup=None, attempts=3):
    # В MAX API chat_id передается через параметры URL
    params = {"chat_id": chat_id}
    
    # А текст и вложения передаются в JSON теле
    body = {"text": text}
    
    if reply_markup and "inline_keyboard" in reply_markup:
        max_buttons = []
        for row in reply_markup["inline_keyboard"]:
            max_row = []
            for btn in row:
                if "callback_data" in btn:
                    max_row.append({
                        "type": "callback",
                        "text": str(btn["text"]),
                        "payload": str(btn["callback_data"])
                    })
                elif "url" in btn:
                    max_row.append({
                        "type": "link",
                        "text": str(btn["text"]),
                        "url": str(btn["url"])
                    })
            max_buttons.append(max_row)

        body["attachments"] = [{
            "type": "inline_keyboard",
            "payload": {"buttons": max_buttons}
        }]

    last_err = None
    for i in range(1, attempts + 1):
        try:
            resp = requests.post(f"{MAX_API_URL}/messages", params=params, json=body, headers=HEADERS, timeout=20)
            resp.raise_for_status()
            return True
        except requests.exceptions.HTTPError as e:
            # Теперь, если MAX вернет 400, мы увидим подробную причину прямо в логах!
            error_details = e.response.text
            print(f"❌ Подробности ошибки MAX API: {error_details}", flush=True)
            last_err = f"{e} - {error_details}"
            time.sleep(1.5)
        except Exception as e:
            last_err = str(e)
            time.sleep(1.5)
            
    raise RuntimeError(f"MAX sendMessage failed: {last_err}")

def download_photo(url):
    file_name = str(int(time.time() * 1000))
    local = f"{DOWNLOAD_DIR}/{file_name}.jpg"
    tmp_local = f"{DOWNLOAD_DIR}/{file_name}_tmp.file"

    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        with open(tmp_local, "wb") as f:
            for chunk in r.iter_content(1024 * 128):
                if chunk: f.write(chunk)
    try:
        with Image.open(tmp_local) as img:
            rgb_im = img.convert("RGB")
            rgb_im.save(local, "JPEG", quality=95)
        os.remove(tmp_local)
    except Exception as e:
        os.rename(tmp_local, local)
    return local
