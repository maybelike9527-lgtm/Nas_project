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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except Exception:
    pass

# 針對舊版環境的 urllib3 相容性處理
try:
    if hasattr(urllib3, 'disable_warnings'):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    else:
        import requests.packages.urllib3 as urllib3_internal

        urllib3_internal.disable_warnings(urllib3_internal.exceptions.InsecureRequestWarning)
except Exception:
    pass

# 使用絕對路徑確保執行穩定
DB_PATH = "account_book.db"


# ================= 📦 資料庫工具 =================
def get_db_config():
    """從資料庫讀取系統設定值"""
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


def get_stock_assets():
    """獲取所有持股資料"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT stock_code, shares, cost_price, user_id FROM stock_assets")
        rows = cursor.fetchall()
        conn.close()

        assets = {}
        for code, shares, cost, user in rows:
            if code not in assets: assets[code] = []
            assets[code].append({'shares': shares, 'cost': cost, 'user': user})
        return assets
    except Exception as e:
        logger.error(f"持股清單讀取失敗: {e}")
        return {}


# ================= 🚀 核心監控與損益計算 =================
def fetch_stock_report():
    # 1. 取得執行參數
    # [新增] 加上這行 Log，您可以在 nohup.out 或終端機看到實際收到的參數清單
    logger.info(f"啟動參數檢查 (sys.argv): {sys.argv}")

    # 判斷邏輯不變
    is_manual = len(sys.argv) > 1 and sys.argv[1] == "manual"
    # 2. 取得設定與清單
    configs = get_db_config()
    token = configs.get('tele_token')
    chat_id = configs.get('tele_chat_id')
    assets_data = get_stock_assets()

    if not token or not chat_id:
        logger.critical("初始化中止：資料庫中找不到 Telegram 相關設定")
        return

    if not assets_data:
        logger.warning("資料庫中無持股資料，請先透過『庫存管理』新增股票")
        return

    # 3. 恢復您要求的假日檢查邏輯
    weekday = datetime.datetime.now().weekday()

    if weekday > 4:
        if is_manual:
            # 如果是手動查詢，僅記錄日誌但繼續執行
            logger.info("今日為交易休息日，但偵測到手動查詢，將抓取最後收盤數據")
        else:
            # 如果是排程執行（無參數），則直接結束
            logger.info("今日為交易休息日，排程任務跳過數據抓取")
            return

    # 4. 組合證交所 API 請求並計算損益
    codes = list(assets_data.keys())
    query_string = "|".join([f"tse_{c}.tw" for c in codes])
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query_string}&_={int(time.time() * 1000)}"

    try:
        res = requests.get(url, verify=False, timeout=20)
        data = res.json()

        msg = "📈 <b>台股庫存即時損益回報</b>\n━━━━━━━━━━━━━━━━"
        total_profit = 0
        found_count = 0

        for stock in data.get('msgArray', []):
            code = stock.get('c')
            name = stock.get('n')
            current_p = float(stock.get('z', stock.get('b', 0)))
            y_close = float(stock.get('y', 0))

            for item in assets_data.get(code, []):
                shares = item['shares']
                cost = item['cost']
                profit = (current_p - cost) * shares
                total_profit += profit

                diff = current_p - y_close
                arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                profit_icon = "💰" if profit >= 0 else "💸"

                msg += f"\n<b>{code} {name}</b>"
                msg += f"\n現價：<code>{current_p}</code> ({arrow}{abs(diff):.2f})"
                msg += f"\n成本：{cost} | 持股：{shares}"
                msg += f"\n{profit_icon} 損益：<b>{profit:,.0f}</b>\n"
                found_count += 1

        if found_count > 0:
            msg += f"━━━━━━━━━━━━━━━━\n總計即時損益：<b>{total_profit:,.0f}</b>"
            api_url = f"https://api.telegram.org/bot{token}/sendMessage"
            requests.post(api_url, data={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}, verify=False,
                          timeout=15)
            logger.info("損益回報發送成功")
        else:
            logger.warning("證交所回傳無數據，可能非服務時段")

    except Exception as e:
        logger.error(f"行情抓取或損益計算異常: {e}")


if __name__ == "__main__":
    fetch_stock_report()