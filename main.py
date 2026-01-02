# 檔名：stock_monitor_nas.py
# 更新日期：2026-01-02 修正漲跌符號顏色 (紅上/綠下) 與五檔價過濾

import requests
import json
import datetime
import urllib3
import os
import sys
import time
import io

# 強制標準輸出使用 UTF-8
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except:
    pass

# ================= 設定區 =================
TELEGRAM_TOKEN = '8540551367:AAGXmoATXq3hranSkxUiEA6IPzMNvNrESog'
CHAT_ID = '6824247597'
STOCK_FILE = 'stock.txt'
# ========================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def send_telegram_message(message_text):
    """發送 Telegram 通知 (僅在此處使用特定符號)"""
    prefix = "📈 台股即時報價"
    final_text = f"<b>{prefix}</b>\n{message_text}"

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {
        'chat_id': CHAT_ID,
        'text': final_text,
        'parse_mode': 'HTML'
    }

    try:
        response = requests.post(url, data=data, verify=False, timeout=15)
        if response.status_code == 200:
            print("Telegram update sent successfully.")  
    except Exception as e:
        print(f"Telegram error: {e}")


def load_stocks_from_file():
    """從 stock.txt 讀取股票代號"""
    stock_list = []
    current_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(current_dir, STOCK_FILE)

    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            for line in f:
                code = line.strip()
                if code and not code.startswith('#'):
                    stock_list.append(code)
        return stock_list
    except Exception as e:
        print(f"File loading error: {e}")
        return []


def get_stock_price_direct():
    target_stocks = load_stocks_from_file()
    if not target_stocks:
        return

    # 週末不執行 (2026/01/02 為交易日)
    weekday = datetime.datetime.now().weekday()
    if weekday > 4:
        print("Market is closed.")
        return

    print("Fetching real-time data...")

    # 同時查詢上市(tse)與上櫃(otc)
    query_parts = [f"tse_{code}.tw" for code in target_stocks] + [f"otc_{code}.tw" for code in target_stocks]
    query_string = "|".join(query_parts)
    url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query_string}&json=1&delay=0&_={int(time.time() * 1000)}"

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://mis.twse.com.tw/'
    }

    try:
        res = requests.get(url, headers=headers, verify=False, timeout=20)
        data = res.json()

        if 'msgArray' not in data or not data['msgArray']:
            print("No valid price data received.")
            return

        msg_content = "--------------------"
        processed_codes = set()

        for stock in data['msgArray']:
            code = stock.get('c')
            if not code or code in processed_codes: continue

            name = stock.get('n', 'Unknown')
            yesterday_price = stock.get('y', '-')  # 昨收

            # --- 價格選取邏輯 ---
            # z 為成交價
            current_price = stock.get('z', '-')

            if current_price == '-' or not current_price:
                # 盤中若無成交，取揭示買價(b)的第一筆並過濾五檔字串
                b_string = stock.get('b', '-')
                if b_string != '-':
                    current_price = b_string.split('_')[0]
                else:
                    current_price = stock.get('o', '-')  # 開盤價

            # --- 漲跌幅計算與符號 ---
            change_str = ""
            try:
                if current_price != '-' and yesterday_price != '-':
                    p_now = float(current_price)
                    p_prev = float(yesterday_price)
                    diff = p_now - p_prev
                    percent = (diff / p_prev) * 100

                    if diff > 0:
                        mark = "🔺"  # 紅色三角向上
                        sign = "+"
                    elif diff < 0:
                        mark = "🔻"  # 綠色三角向下
                        sign = ""
                    else:
                        mark = "─"
                        sign = ""

                    change_str = f" {mark} {sign}{diff:.2f} ({sign}{percent:.2f}%)"
            except:
                pass

            msg_content += f"\n\n{name} ({code})\n現價: <b>{current_price}</b>{change_str}"
            processed_codes.add(code)

        send_telegram_message(msg_content)
        print("Data processing finished.")

    except Exception as e:
        print(f"System error: {e}")


if __name__ == "__main__":
    get_stock_price_direct()
