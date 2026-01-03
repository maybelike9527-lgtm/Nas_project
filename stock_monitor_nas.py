import requests
import json
import datetime
import urllib3
import os
import sys
import time
import io
import sqlite3
import logging

# ================= 📝 LOGGING 系統設定 (中文化) =================
# 確保日誌純淨，無 Emoji
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
# 強制輸出使用 UTF-8，解決 NAS 終端機亂碼問題
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# 關閉 SSL 安全警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 資料庫路徑 (與 bot_listener.py 保持一致)
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")


# ================= 📦 資料庫工具 =================
def get_db_config():
    """從資料庫讀取系統設定值 (如 Token)"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        configs = dict(cursor.fetchall())
        conn.close()
        return configs
    except Exception as e:
        logger.error(f"資料庫設定讀取失敗: {e}")
        return {}


def get_target_stocks():
    """從 stock_assets 表獲取所有需要監控的股票代號"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        # 獲取資料庫中所有不重複的股票代號
        cursor.execute("SELECT DISTINCT stock_code FROM stock_assets")
        stocks = [row[0] for row in cursor.fetchall()]
        conn.close()
        return stocks
    except Exception as e:
        logger.error(f"持股清單讀取失敗: {e}")
        return []


# ================= 🚀 核心監控邏輯 =================
def fetch_stock_info():
    # 檢查是否有傳入 'manual' 參數
    is_manual = len(sys.argv) > 1 and sys.argv[1] == "manual"

    # 取得設定與清單
    configs = get_db_config()
    token = configs.get('tele_token')
    chat_id = configs.get('tele_chat_id')
    target_stocks = get_target_stocks()

    if not token or not chat_id:
        logger.critical("初始化中止：資料庫中找不到 Telegram 相關設定")
        return

    if not target_stocks:
        logger.warning("資料庫中無監控代號，請先透過『庫存管理』新增股票")
        return

    # 修改後的假日檢查邏輯
    weekday = datetime.datetime.now().weekday()
    if weekday > 4:
        if is_manual:
            # 如果是手動查詢，僅記錄日誌但繼續執行
            logger.info("今日為交易休息日，但偵測到手動查詢，將抓取最後收盤數據")
        else:
            # 如果是排程執行（無參數），則直接結束
            logger.info("今日為交易休息日，排程任務跳過數據抓取")
            return

    logger.info(f"開始抓取證交所資訊，監控數量：{len(target_stocks)}")

    # 3. 組合證交所即時資訊 API 請求
    # 使用 tse_代號.tw 格式抓取上市股票資訊
    query_list = [f"tse_{code}.tw" for code in target_stocks]
    query_string = "|".join(query_list)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query_string}&_={int(time.time() * 1000)}"

    try:
        res = requests.get(url, verify=False, timeout=20)
        data = res.json()

        msg_content = "📊 <b>台股實時行情回報</b>\n━━━━━━━━━━━━━━━━"
        found_count = 0

        for stock in data.get('msgArray', []):
            code = stock.get('c')  # 股票代號
            name = stock.get('n')  # 股票名稱
            price = stock.get('z', stock.get('b', '-'))  # 成交價，若無則取買價
            y_price = stock.get('y', '-')  # 昨日收盤價

            change_str = ""
            try:
                diff = float(price) - float(y_price)
                percent = (diff / float(y_price)) * 100
                if diff > 0:
                    change_str = f" 🔺 +{diff:.2f} (+{percent:.2f}%)"
                elif diff < 0:
                    change_str = f" 🔻 {diff:.2f} ({percent:.2f}%)"
                else:
                    change_str = " ➖ 持平"
            except:
                change_str = " (無變動資料)"

            msg_content += f"\n<b>{code} {name}</b>\n現價：<code>{price}</code>{change_str}\n"
            found_count += 1

        if found_count > 0:
            # 只有在此處發送給使用者的訊息允許 Emoji
            final_url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {'chat_id': chat_id, 'text': msg_content, 'parse_mode': 'HTML'}
            resp = requests.post(final_url, data=payload, verify=False, timeout=15)

            if resp.status_code == 200:
                logger.info("行情報告發送成功")
            else:
                logger.error(f"Telegram 發送失敗，狀態碼: {resp.status_code}")
        else:
            logger.warning("證交所回傳資料為空，可能目前非開盤時段")

    except Exception as e:
        logger.error(f"行情抓取過程中發生異常: {e}")


if __name__ == "__main__":
    fetch_stock_info()