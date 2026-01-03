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

# ================= 📝 LOGGING 系統設定 =================
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
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 使用絕對路徑確保 NAS 執行穩定
DB_PATH = "/volume1/docker/ma/account_book.db"


# ================= 📦 資料庫工具 =================
def get_stock_assets():
    """從資料庫獲取所有持股資料 (含成本與股數)"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        # 取得所有持股資訊
        cursor.execute("SELECT stock_code, shares, cost_price, user_id FROM stock_assets")
        rows = cursor.fetchall()
        conn.close()

        # 整理成字典：{ '2330': [{'shares': 1000, 'cost': 600, 'user': 'id'}] }
        assets = {}
        for code, shares, cost, user in rows:
            if code not in assets: assets[code] = []
            assets[code].append({'shares': shares, 'cost': cost, 'user': user})
        return assets
    except Exception as e:
        logger.error(f"資產清單讀取失敗: {e}")
        return {}


def get_config(key):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        res = cursor.fetchone()
        conn.close()
        return res[0] if res else None
    except:
        return None


# ================= 🚀 核心監控與損益計算 =================
def fetch_stock_report():
    # 檢查是否為手動查詢參數
    is_manual = len(sys.argv) > 1 and sys.argv[1] == "manual"

    token = get_config('tele_token')
    chat_id = get_config('tele_chat_id')
    assets_data = get_stock_assets()

    if not assets_data:
        logger.warning("資料庫中無持股資料")
        return

    # 假日檢查 (排程執行時在假日不報價)
    weekday = datetime.datetime.now().weekday()
    if weekday > 4:
        if is_manual:
            logger.info("今日為非交易日，手動查詢模式啟動")
        else:
            logger.info("今日為非交易日，排程跳過")
            return

    # 組合 API 請求
    codes = list(assets_data.keys())
    query_string = "|".join([f"tse_{c}.tw" for c in codes])
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query_string}&_={int(time.time() * 1000)}"

    try:
        res = requests.get(url, verify=False, timeout=20)
        data = res.json()

        msg = "📈 <b>台股庫存即時損益回報</b>\n━━━━━━━━━━━━━━━━"
        total_profit = 0

        for stock in data.get('msgArray', []):
            code = stock.get('c')
            name = stock.get('n')
            current_p = float(stock.get('z', stock.get('b', 0)))  # 現價
            y_close = float(stock.get('y', 0))  # 昨收

            # 針對該代號的所有持股紀錄計算損益
            for item in assets_data.get(code, []):
                shares = item['shares']
                cost = item['cost']

                # 計算單筆損益
                profit = (current_p - cost) * shares
                total_profit += profit

                # 漲跌箭頭
                diff = current_p - y_close
                arrow = "🔺" if diff > 0 else "🔻" if diff < 0 else "➖"
                profit_icon = "💰" if profit >= 0 else "💸"

                msg += f"\n<b>{code} {name}</b>"
                msg += f"\n現價：<code>{current_p}</code> ({arrow}{abs(diff):.2f})"
                msg += f"\n成本：{cost} | 持股：{shares}"
                msg += f"\n{profit_icon} 損益：<b>{profit:,.0f}</b>\n"

        msg += f"━━━━━━━━━━━━━━━━\n總計即時損益：<b>{total_profit:,.0f}</b>"

        # 發送 Telegram
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}, verify=False)
        logger.info("損益回報發送成功")

    except Exception as e:
        logger.error(f"抓取或計算失敗: {e}")


if __name__ == "__main__":
    fetch_stock_report()