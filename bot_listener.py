import requests
import urllib3
import os
import time
import sys
import io
import json
import sqlite3
import logging

# ================= 📝 LOGGING 系統設定 (中文化) =================
# 設定格式：時間 - 層級 - 訊息 (完全無 Emoji，確保 NAS 日誌整潔)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
try:
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

# 強制 UTF-8 輸出，避免 NAS 終端機中文亂碼
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")


# ================= 📦 資料庫工具邏輯 =================
def get_config(key):
    """從資料庫讀取設定值"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"資料庫查詢失敗 (鍵名: {key}): {e}")
        return None


# 初始化設定
TOKEN = get_config('tele_token')
CHAT_ID = get_config('tele_chat_id')
BASE_PATH = os.path.dirname(os.path.abspath(__file__))
user_state = {}


# ================= 🤖 Telegram 通訊邏輯 =================
def send_with_keyboard(chat_id, text, custom_keyboard=None):
    """發送訊息至 Telegram (允許使用 Emoji)"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    default_keyboard = {
        "keyboard": [
            ["查股價", "掃描BT"],
            ["整理檔案", "清理空間"],
            ["管理股票", "全部執行"]
        ],
        "resize_keyboard": True,
        "one_time_keyboard": False
    }
    keyboard = custom_keyboard if custom_keyboard else default_keyboard

    data = {
        'chat_id': chat_id,
        'text': text,
        'reply_markup': json.dumps(keyboard),
        'parse_mode': 'HTML'
    }

    try:
        requests.post(url, data=data, verify=False, timeout=10)
    except Exception as e:
        logger.error(f"Telegram API 發送失敗: {e}")


def run_script(script_name):
    """執行 NAS 本地腳本"""
    script_path = os.path.join(BASE_PATH, script_name)
    if os.path.exists(script_path):
        logger.info(f"正在執行腳本: {script_name}")
        os.system(f"python3 {script_path} &")
    else:
        logger.error(f"腳本執行失敗: 找不到檔案 {script_name}")


# ================= 🔄 訊息監聽循環 =================
def handle_updates():
    offset = None
    logger.info("機器人監聽服務已啟動")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {'timeout': 30, 'offset': offset}
            response = requests.get(url, params=params, verify=False, timeout=35).json()

            if not response.get("result"):
                continue

            for update in response["result"]:
                offset = update["update_id"] + 1
                if "message" not in update: continue

                msg = update["message"]
                chat_id = str(msg["chat"]["id"])
                msg_text = msg.get("text", "")

                # 收到指令後的處理 (電報回覆訊息可含 Emoji)
                if msg_text == "/start":
                    send_with_keyboard(chat_id, "✅ 系統已啟動，請選擇功能：")
                elif "查股價" in msg_text:
                    run_script("stock_monitor_nas.py")
                    send_with_keyboard(chat_id, "📈 收到指令：正在抓取最新股價...")
                elif "掃描BT" in msg_text:
                    run_script("check_bt.py")
                    send_with_keyboard(chat_id, "🔍 收到指令：正在掃描大檔案...")

        except Exception as e:
            logger.error(f"主迴圈發生異常: {e}")
            time.sleep(5)


if __name__ == "__main__":
    if TOKEN:
        handle_updates()
    else:
        logger.critical("初始化中止：資料庫中找不到 tele_token 設定")