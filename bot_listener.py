import requests
import urllib3
import os
import time
import sys
import io
import json
import sqlite3
import logging
from datetime import datetime, timedelta

# ================= 📝 LOGGING 系統設定 (中文化) =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")
BASE_PATH = os.path.dirname(os.path.abspath(__file__))

# ================= 📦 資料庫與鎖定工具 =================
def get_config(key):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"資料庫查詢失敗 (鍵名: {key}): {e}")
        return None

def check_system_lock(lock_name):
    """檢查併發鎖定 (含 5 分鐘逾時自動解鎖)"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT is_locked, user_id, lock_time FROM system_locks WHERE lock_name = ?", (lock_name,))
        result = cursor.fetchone()
        conn.close()
        if result and result[0] == 1:
            lock_time = datetime.strptime(result[2], '%Y-%m-%d %H:%M:%S')
            if datetime.now() - lock_time > timedelta(minutes=5):
                logger.warning(f"偵測到鎖定逾時 ({lock_name})，執行自動解鎖")
                set_system_lock(lock_name, None, 0)
                return (0, None, None)
            return result
        return (0, None, None)
    except Exception as e:
        logger.error(f"檢查鎖定狀態失敗: {e}")
        return (0, None, None)

def set_system_lock(lock_name, user_id, lock_status):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        lock_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S') if lock_status == 1 else None
        conn.execute("UPDATE system_locks SET is_locked = ?, user_id = ?, lock_time = ? WHERE lock_name = ?",
                     (lock_status, user_id, lock_time, lock_name))
        conn.commit()
        conn.close()
        logger.info(f"鎖定更新成功: {lock_name}={lock_status} (使用者={user_id})")
    except Exception as e:
        logger.error(f"更新鎖定失敗: {e}")

# ================= 🤖 Telegram 發送邏輯 =================
TOKEN = get_config('tele_token')

def send_with_keyboard(chat_id, text, custom_keyboard=None):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    default_keyboard = {
        "keyboard": [
            ["查股價", "掃描BT"],
            ["整理檔案", "清理空間"],
            ["庫存管理", "全部執行"]
        ],
        "resize_keyboard": True
    }
    keyboard = custom_keyboard if custom_keyboard else default_keyboard
    data = {'chat_id': chat_id, 'text': text, 'reply_markup': json.dumps(keyboard), 'parse_mode': 'HTML'}
    requests.post(url, data=data, verify=False, timeout=10)

# ================= 🔄 訊息監聽循環 =================
def handle_updates():
    offset = None
    user_state = {}
    logger.info("機器人監聽服務已啟動")

    while True:
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
            params = {'timeout': 30, 'offset': offset}
            response = requests.get(url, params=params, verify=False, timeout=35).json()

            if not response.get("result"): continue

            for update in response["result"]:
                offset = update["update_id"] + 1
                if "message" not in update or "text" not in update["message"]: continue

                msg = update["message"]
                chat_id = str(msg["chat"]["id"])
                msg_text = msg.get("text", "").strip()

                # --- 庫存管理併發鎖定邏輯 ---
                if msg_text == "庫存管理":
                    is_locked, locker_id, _ = check_system_lock('accounting')
                    if is_locked == 1 and str(locker_id) != chat_id:
                        logger.info(f"使用者 {chat_id} 嘗試進入，但目前由 {locker_id} 使用中")
                        send_with_keyboard(chat_id, "⚠️ <b>有人正在管理中請稍等</b>\n請待前一位使用者完成後再試。")
                        continue
                    
                    set_system_lock('accounting', chat_id, 1)
                    manage_kb = {"keyboard": [["新增庫存", "刪除庫存"], ["查看庫存", "回主選單"]], "resize_keyboard": True}
                    send_with_keyboard(chat_id, "📊 <b>庫存與成本管理</b>\n請選擇操作：", manage_kb)

                elif msg_text == "回主選單":
                    set_system_lock('accounting', None, 0)
                    send_with_keyboard(chat_id, "🏠 已解除鎖定，回到主選單。")

                elif msg_text == "新增庫存":
                    send_with_keyboard(chat_id, "📝 請輸入：<code>股票代號 股數 成本</code>\n例如：<code>2330 1000 650.5</code>", {"keyboard": [["回主選單"]]})
                    user_state[chat_id] = "WAIT_STOCK_ADD"

                # --- 處理輸入邏輯 (以新增為例) ---
                elif chat_id in user_state and user_state[chat_id] == "WAIT_STOCK_ADD":
                    try:
                        code, shares, cost = msg_text.split()
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("INSERT OR REPLACE INTO stock_assets (user_id, stock_code, shares, cost_price) VALUES (?, ?, ?, ?)",
                                     (chat_id, code, int(shares), float(cost)))
                        conn.commit()
                        conn.close()
                        logger.info(f"使用者 {chat_id} 更新庫存: {code}")
                        send_with_keyboard(chat_id, f"✅ 已紀錄 <b>{code}</b>\n股數：{shares}\n成本：{cost}")
                    except:
                        send_with_keyboard(chat_id, "❌ 格式錯誤，請重新輸入。")

                # --- 其他原本的功能 ---
                elif "查股價" in msg_text:
                    os.system(f"python3 {os.path.join(BASE_PATH, 'stock_monitor_nas.py')} &")
                    send_with_keyboard(chat_id, "📈 正在抓取行情...")

        except Exception as e:
            logger.error(f"監聽異常: {e}")
            time.sleep(5)

if __name__ == "__main__":
    if TOKEN: handle_updates()
    else: logger.critical("初始化中止：找不到 tele_token")
