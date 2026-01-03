import os
import sys
import requests
import urllib3
import io
import sqlite3
import logging

# ================= 📝 LOGGING 系統設定 (中文化) =================
# 設定格式：時間 - 層級 - 訊息 (嚴格禁止 Emoji)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
# 強制輸出使用 UTF-8 編碼，確保 NAS Log 顯示正常
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
# 關閉 SSL 安全警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 資料庫路徑
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")


# ================= 📦 資料庫工具 =================
def get_db_config():
    """從資料庫讀取系統設定值"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        # 開啟 WAL 模式確保並發存取穩定
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        configs = dict(cursor.fetchall())
        conn.close()
        return configs
    except Exception as e:
        logger.error(f"資料庫讀取失敗: {e}")
        return {}


# ================= 🚀 核心清理邏輯 =================
def format_size(bytes_size):
    """格式化檔案大小單位"""
    return f"{bytes_size / (1024 * 1024):.2f} MB"


def main():
    # 1. 取得設定
    configs = get_db_config()
    TELEGRAM_TOKEN = configs.get('tele_token')
    CHAT_ID = configs.get('tele_chat_id')

    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.critical("初始化中止：資料庫中找不到 Telegram 相關設定")
        return

    # 清理設定
    TARGET_FOLDER = '/volume1/淳/BT/'
    SIZE_LIMIT_MB = 100
    DRY_RUN = False  # False 代表直接刪除
    limit_bytes = SIZE_LIMIT_MB * 1024 * 1024

    if not os.path.exists(TARGET_FOLDER):
        logger.error(f"路徑錯誤：找不到目標資料夾 {TARGET_FOLDER}")
        return

    logger.info(f"開始掃描資料夾：{TARGET_FOLDER}")
    logger.info(f"清理門檻：小於 {SIZE_LIMIT_MB} MB")

    deleted_files = []
    total_freed_space = 0

    # 遞迴遍歷資料夾
    for root, dirs, files in os.walk(TARGET_FOLDER):
        for filename in files:
            # 排除 NAS 系統檔與暫存檔
            if filename.startswith('.') or '@eaDir' in root:
                continue

            full_path = os.path.join(root, filename)
            try:
                file_size = os.path.getsize(full_path)

                # 判斷大小是否小於門檻
                if file_size < limit_bytes:
                    file_info = f"<code>{filename}</code> ({format_size(file_size)})"
                    deleted_files.append(file_info)
                    total_freed_space += file_size

                    # 執行刪除
                    if not DRY_RUN:
                        os.remove(full_path)
                        logger.info(f"已刪除檔案: {filename}")
                    else:
                        logger.info(f"預計刪除(模擬): {filename}")

            except Exception as e:
                logger.error(f"處理檔案時發生錯誤 {filename}: {e}")

    # --- 發送 Telegram 報告 (訊息內含 Emoji) ---
    if deleted_files:
        action_text = "模擬清理" if DRY_RUN else "執行清理"
        msg = f"🧹 <b>空間自動清理報告</b>\n"
        msg += f"🛡️ <b>模式：{action_text}</b>\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"📂 清理數量：<b>{len(deleted_files)}</b> 個檔案\n"
        msg += f"💾 釋放空間：<b>{format_size(total_freed_space)}</b>\n"
        msg += f"📉 條件：小於 {SIZE_LIMIT_MB} MB"

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}

        try:
            resp = requests.post(url, data=payload, verify=False, timeout=15)
            if resp.status_code == 200:
                logger.info("Telegram 清理報告發送成功")
            else:
                logger.error(f"Telegram 發送失敗，狀態碼: {resp.status_code}")
        except Exception as e:
            logger.error(f"發送 Telegram 通知時發生異常: {e}")
    else:
        logger.info("掃描完畢：無符合清理條件的檔案")


if __name__ == "__main__":
    main()