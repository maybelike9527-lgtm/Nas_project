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

try:
    if hasattr(urllib3, 'disable_warnings'):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    else:
        import requests.packages.urllib3 as urllib3_internal

        urllib3_internal.disable_warnings(urllib3_internal.exceptions.InsecureRequestWarning)
except Exception:
    pass

# 使用絕對路徑確保資料庫連線穩定
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")


# ================= 🛠️ 輔助工具 =================
def safe_float(value):
    """安全轉換浮點數，處理 '-' 或無法轉換的情況"""
    try:
        if value == '-' or value == '':
            return 0.0
        return float(value)
    except (ValueError, TypeError):
        return 0.0


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
    """獲取所有持股資料 (供報價功能使用)"""
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


# ================= 🛠️ 庫存管理邏輯 (供 Bot 調用) =================
def list_inventory(user_id):
    """查詢使用者的庫存清單"""
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT stock_code, shares, cost_price FROM stock_assets WHERE user_id = ?", (user_id,))
        rows = cursor.fetchall()
        conn.close()

        if not rows:
            return "📋 目前尚無庫存資料。"

        report = "📋 <b>您的持股庫存清單：</b>\n━━━━━━━━━━━━━━"
        for code, shares, cost in rows:
            report += f"\n代號：<code>{code}</code>\n持股：{shares} | 成本：{cost}\n"
        return report
    except Exception as e:
        logger.error(f"查看庫存失敗: {e}")
        return "❌ 讀取資料庫失敗。"


def add_inventory(user_id, text):
    """新增庫存：解析字串並寫入 DB"""
    try:
        # 預期格式：代號 股數 成本
        parts = text.split()
        if len(parts) != 3:
            return False, "❌ 格式錯誤，請重新輸入：\n<code>代號 股數 成本</code>"

        code, shares, cost = parts
        conn = sqlite3.connect(DB_PATH, timeout=10)
        conn.execute(
            "INSERT OR REPLACE INTO stock_assets (user_id, stock_code, shares, cost_price) VALUES (?, ?, ?, ?)",
            (user_id, code, int(shares), float(cost))
        )
        conn.commit()
        conn.close()
        logger.info(f"使用者 {user_id} 更新庫存: {code}")
        return True, f"✅ 已紀錄 <b>{code}</b>\n股數：{shares}\n成本：{cost}"
    except ValueError:
        return False, "❌ 數值格式錯誤，股數與成本請輸入數字。"
    except Exception as e:
        logger.error(f"新增庫存失敗: {e}")
        return False, f"❌ 執行錯誤: {e}"


def delete_inventory(user_id, stock_code):
    """刪除庫存"""
    try:
        stock_code = stock_code.strip()
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM stock_assets WHERE user_id = ? AND stock_code = ?", (user_id, stock_code))
        row_count = cursor.rowcount
        conn.commit()
        conn.close()

        if row_count > 0:
            logger.info(f"使用者 {user_id} 刪除庫存: {stock_code}")
            return True, f"✅ 已成功刪除 <b>{stock_code}</b>"
        else:
            return False, f"❓ 找不到代號 <b>{stock_code}</b> 的資料。"
    except Exception as e:
        logger.error(f"刪除失敗: {e}")
        return False, "❌ 執行刪除時發生錯誤。"


# ================= 🚀 核心監控與損益計算 (原有功能) =================
def fetch_stock_report():
    logger.info(f"啟動參數檢查 (sys.argv): {sys.argv}")
    is_manual = len(sys.argv) > 1 and sys.argv[1] == "manual"

    configs = get_db_config()
    token = configs.get('tele_token')
    chat_id = configs.get('tele_chat_id')
    assets_data = get_stock_assets()

    if not token or not chat_id:
        logger.critical("初始化中止：資料庫中找不到 Telegram 相關設定")
        return

    if not assets_data:
        if is_manual:
            logger.warning("資料庫中無持股資料")
        return

    # 假日檢查邏輯
    weekday = datetime.datetime.now().weekday()
    if weekday > 4:
        if is_manual:
            logger.info("今日為交易休息日，但偵測到手動查詢，將抓取最後收盤數據")
        else:
            logger.info("今日為交易休息日，排程任務跳過數據抓取")
            return

    codes = list(assets_data.keys())
    # 組合 API 請求
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

            # --- [修正核心] 價格解析邏輯 ---
            # 1. 嘗試取得成交價 (z)
            z_price = stock.get('z', '-')
            if z_price == '-':
                # 2. 若無成交價，嘗試取買進價 (b) 的第一檔 (格式如 "650.00_649.00_...")
                bid_prices = stock.get('b', '').split('_')
                z_price = bid_prices[0] if bid_prices and bid_prices[0] else '-'

            # 使用 safe_float 避免 '-' 造成崩潰
            current_p = safe_float(z_price)
            y_close = safe_float(stock.get('y', 0))

            # 3. 如果現價解析出來是 0 (代表沒成交也沒買價)，改用昨收價計算，避免損益顯示錯誤
            if current_p == 0 and y_close > 0:
                current_p = y_close

            # 計算損益
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