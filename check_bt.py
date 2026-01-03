import os
import datetime
import time
import requests
import json
import sqlite3
import sys
import io
import logging

# ================= 📝 LOGGING 系統設定 (中文化) =================
# 設定格式：時間 - 層級 - 訊息 (完全不含 Emoji)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
# 強制輸出使用 UTF-8 編碼，確保 NAS Log 顯示正常
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 資料庫路徑
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")


# ================= 📦 資料庫工具 =================
def get_config():
    """從資料庫讀取設定值"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        # 開啟 WAL 模式確保讀取時不影響其他腳本寫入
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        res = dict(cursor.fetchall())
        conn.close()
        return res
    except Exception as e:
        logger.error(f"資料庫讀取失敗: {e}")
        return {}


# ================= 🚀 核心邏輯 =================
def scan_bt():
    conf = get_config()
    token = conf.get('tele_token')
    chat_id = conf.get('tele_chat_id')

    if not token or not chat_id:
        logger.critical("初始化中止：資料庫中找不到 Telegram 設定")
        return

    path = '/volume1/淳/BT/'
    report_data = []
    new_items = []

    if not os.path.exists(path):
        logger.error(f"路徑錯誤：找不到資料夾 {path}")
        return

    logger.info("開始掃描 BT 資料夾內容...")
    one_hour_ago = time.time() - 3600

    try:
        for root, _, files in os.walk(path):
            for f in files:
                # 排除系統檔
                if f.startswith('.') or '@eaDir' in root:
                    continue

                f_path = os.path.join(root, f)
                try:
                    size_bytes = os.path.getsize(f_path)
                    size_mb = size_bytes / (1024 * 1024)

                    # 僅紀錄大於 100MB 的檔案
                    if size_mb > 100:
                        mtime = os.path.getmtime(f_path)
                        relative_path = os.path.relpath(f_path, path)

                        # 紀錄所有大檔案資訊供 AI 判斷
                        report_data.append({
                            "name": f,
                            "size_mb": round(size_mb, 2),
                            "path": relative_path
                        })

                        # 如果是最近一小時新增的，才列入 Telegram 通知
                        if mtime > one_hour_ago:
                            new_items.append(f"<b>[{round(size_mb / 1024, 2)} GB]</b> 📄 {f}")
                except Exception:
                    continue

        # 1. 產生 JSON 報表供 AI 判斷 (每小時執行)
        if report_data:
            report_file = os.path.join(os.path.dirname(__file__), "bt_status.json")
            with open(report_file, "w", encoding="utf-8") as j:
                json.dump(report_data, j, ensure_ascii=False, indent=4)
            logger.info(f"AI 狀態報表已更新: {report_file}")

        # 2. 發送 Telegram 通知 (訊息內可含 Emoji)
        if new_items:
            msg = f"📂 <b>BT 每小時下載進報</b>\n━━━━━━━━━━━━━━━━\n" + "\n".join(new_items)
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}

            resp = requests.post(url, data=payload, verify=False, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram 下載進報通知發送成功")
            else:
                logger.error(f"Telegram 通知發送失敗，狀態碼: {resp.status_code}")
        else:
            logger.info("掃描完成：過去一小時無新增大檔案")

    except Exception as e:
        logger.error(f"掃描過程中發生異常: {e}")


if __name__ == "__main__":
    scan_bt()