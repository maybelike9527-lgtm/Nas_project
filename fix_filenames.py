import os
import requests
import urllib3
import sys
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
# 強制輸出使用 UTF-8，解決 NAS Log 亂碼
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
        # 開啟 WAL 模式確保穩定性
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        configs = dict(cursor.fetchall())
        conn.close()
        return configs
    except Exception as e:
        logger.error(f"資料庫讀取失敗: {e}")
        return {}


# ================= 🚀 核心邏輯 =================
def fix_filenames():
    # 1. 取得設定
    configs = get_db_config()
    TELEGRAM_TOKEN = configs.get('tele_token')
    CHAT_ID = configs.get('tele_chat_id')

    if not TELEGRAM_TOKEN or not CHAT_ID:
        logger.critical("初始化中止：資料庫中找不到 Telegram 相關設定")
        return

    ROOT = '/volume1/淳/BT/'
    DRY_RUN = False

    if not os.path.exists(ROOT):
        logger.error(f"目錄不存在：{ROOT}")
        return

    logger.info(f"開始掃描並修正檔名，根目錄：{ROOT}")

    renamed = 0
    skipped = 0
    failed = 0
    examples = []

    for dirpath, dirnames, filenames in os.walk(ROOT):
        # 排除 NAS 縮圖目錄
        if '@eaDir' in dirpath:
            continue

        for fname in filenames:
            # 判斷是否包含 @ 字元
            if '@' not in fname:
                continue

            # 邏輯：移除 @ 及其之前的字元
            new_name = fname.split('@', 1)[-1]

            # 如果分割後檔名沒變（例如 @ 在最後），則略過
            if not new_name or new_name == fname:
                continue

            src = os.path.join(dirpath, fname)
            dst = os.path.join(dirpath, new_name)

            if os.path.exists(dst):
                logger.warning(f"略過：目標檔案已存在 - {new_name}")
                skipped += 1
                continue

            try:
                if DRY_RUN:
                    logger.info(f"模擬更名：{fname} -> {new_name}")
                else:
                    os.rename(src, dst)
                    logger.info(f"執行更名：{fname} -> {new_name}")

                renamed += 1
                if len(examples) < 5:
                    examples.append(f"原：{fname}\n新：{new_name}")
            except Exception as e:
                failed += 1
                logger.error(f"更名失敗：{fname}，原因：{e}")

    # --- 發送 Telegram 報告 (訊息內含 Emoji) ---
    status_str = "測試模式" if DRY_RUN else "正式執行"
    msg = f"🔧 <b>檔名修正執行報告</b>\n"
    msg += f"🛡️ <b>模式：{status_str}</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"✨ 成功修正：{renamed} 個\n"
    msg += f"⏭️ 略過檔案：{skipped} 個\n"
    msg += f"❌ 失敗檔案：{failed} 個"

    if examples:
        msg += f"\n\n📝 <b>修正範例：</b>\n" + "\n".join(examples)

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': CHAT_ID, 'text': msg, 'parse_mode': 'HTML'}

    try:
        resp = requests.post(url, data=payload, verify=False, timeout=15)
        if resp.status_code == 200:
            logger.info("Telegram 執行報告發送成功")
        else:
            logger.error(f"Telegram 發送失敗，狀態碼: {resp.status_code}")
    except Exception as e:
        logger.error(f"發送 Telegram 通知時發生異常: {e}")


if __name__ == "__main__":
    fix_filenames()