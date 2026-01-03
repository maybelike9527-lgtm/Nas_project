import os
import time
import requests
import sqlite3
import sys
import io
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
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# 資料庫路徑使用絕對路徑確保穩定
DB_PATH = "/volume1/docker/ma/account_book.db"


def get_config():
    """從資料庫讀取 Telegram 設定"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        res = dict(cursor.fetchall())
        conn.close()
        return res
    except Exception as e:
        logger.error(f"資料庫讀取失敗: {e}")
        return {}


# ================= 🚀 核心結算邏輯 =================
def scan_bt_daily():
    conf = get_config()
    token = conf.get('tele_token')
    chat_id = conf.get('tele_chat_id')
    path = '/volume1/淳/BT/'

    if not os.path.exists(path):
        logger.error(f"路徑錯誤：找不到資料夾 {path}")
        return

    # 設定時間區間：昨日 17:00 到 今日 17:00
    now = datetime.now()
    # 如果現在時間還沒到 17:00，則以昨天的 17:00 為結束點；若已過 17:00，則以今天的 17:00 為結束點
    if now.hour < 17:
        end_time_dt = now.replace(hour=17, minute=0, second=0, microsecond=0) - timedelta(days=0)
    else:
        end_time_dt = now.replace(hour=17, minute=0, second=0, microsecond=0)

    start_time_dt = end_time_dt - timedelta(days=1)

    start_ts = start_time_dt.timestamp()
    end_ts = end_time_dt.timestamp()

    logger.info(
        f"開始掃描詳細檔名：從 {start_time_dt.strftime('%Y-%m-%d %H:%M')} 到 {end_time_dt.strftime('%Y-%m-%d %H:%M')}")

    file_list = []

    for root, _, files in os.walk(path):
        # 排除 NAS 系統縮圖資料夾
        if '@eaDir' in root: continue
        for f in files:
            # 排除隱藏檔
            if f.startswith('.'): continue

            f_path = os.path.join(root, f)
            try:
                # 取得檔案最後修改時間
                mtime = os.path.getmtime(f_path)
                # 檢查時間戳是否落在 17:00 ~ 17:00 區間
                if start_ts <= mtime <= end_ts:
                    size_bytes = os.path.getsize(f_path)
                    size_mb = size_bytes / (1024 * 1024)
                    # 門檻：僅列出大於 100MB 的檔案
                    if size_mb > 100:
                        size_str = f"{size_mb / 1024:.2f} GB" if size_mb >= 1024 else f"{size_mb:.0f} MB"
                        # 格式化詳細檔名與大小
                        file_list.append(f"📄 <code>{f}</code> ({size_str})")
            except Exception:
                continue

    # 準備 Telegram 訊息
    if file_list:
        msg = f"📂 <b>BT 下載詳細清單</b>\n"
        msg += f"📅 區間：{start_time_dt.strftime('%m/%d %H:%M')} ➔ {end_time_dt.strftime('%m/%d %H:%M')}\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += "\n".join(file_list)
    else:
        msg = f"📋 <b>BT 下載結算報告</b>\n在此時段內無新增大於 100MB 的檔案。"

    # 發送通知
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}
        try:
            requests.post(url, data=payload, verify=False, timeout=15)
            logger.info("詳細檔名報告發送成功")
        except Exception as e:
            logger.error(f"Telegram 發送異常: {e}")


if __name__ == "__main__":
    scan_bt_daily()