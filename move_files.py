import os
import shutil
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
# 關閉 SSL 安全警告 (加入相容性保護)
try:
    if hasattr(urllib3, 'disable_warnings'):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    else:
        # 針對部分舊版環境的替代方案
        import requests.packages.urllib3 as urllib3_internal
        urllib3_internal.disable_warnings(urllib3_internal.exceptions.InsecureRequestWarning)
except Exception:
    pass

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


# ================= 🚀 核心整理邏輯 =================
def move_files():
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

    logger.info(f"開始整理資料夾，根目錄：{ROOT}")

    moved = 0
    failed = 0
    examples = []

    # 第一階段：搬移檔案
    for dirpath, dirnames, filenames in os.walk(ROOT):
        # 排除根目錄本身與系統資料夾
        if os.path.abspath(dirpath) == os.path.abspath(ROOT) or '@eaDir' in dirpath:
            continue

        for fname in filenames:
            src = os.path.join(dirpath, fname)
            dst = os.path.join(ROOT, fname)

            # 處理同名衝突：若目的地已存在，則加上時間戳記或略過
            if os.path.exists(dst):
                logger.warning(f"略過：目的地已有同名檔案 - {fname}")
                continue

            try:
                if DRY_RUN:
                    logger.info(f"模擬搬移：{src} -> {dst}")
                else:
                    shutil.move(src, dst)
                    logger.info(f"執行搬移：{fname}")

                moved += 1
                if len(examples) < 5:
                    examples.append(f"📄 {fname}")
            except Exception as e:
                failed += 1
                logger.error(f"搬移失敗：{fname}，原因：{e}")

    # 第二階段：刪除空資料夾
    removed_dirs = 0
    for dirpath, dirnames, filenames in os.walk(ROOT, topdown=False):
        if os.path.abspath(dirpath) == os.path.abspath(ROOT) or '@eaDir' in dirpath:
            continue

        try:
            if not os.listdir(dirpath):
                if not DRY_RUN:
                    os.rmdir(dirpath)
                removed_dirs += 1
                logger.info(f"已清理空資料夾：{os.path.basename(dirpath)}")
        except Exception:
            pass

    # --- 發送 Telegram 報告 (訊息內含 Emoji) ---
    status_label = "測試模式" if DRY_RUN else "正式執行"
    msg = f"🚚 <b>檔案整理執行報告</b>\n"
    msg += f"🛡️ <b>模式：{status_label}</b>\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"📦 搬移檔案：{moved} 個\n"
    msg += f"🗑️ 清理空夾：{removed_dirs} 個\n"
    msg += f"❌ 失敗檔案：{failed} 個"

    if examples:
        msg += f"\n\n📝 <b>搬移清單範例：</b>\n" + "\n".join(examples)

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
    move_files()