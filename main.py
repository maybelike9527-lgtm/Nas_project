# 檔名：stock_monitor_nas.py
# 更新日期：2026-01-02 優化版本
import requests
import json
import datetime
import urllib3
import os
import sys
import time
import io
import logging

# 設定 Logging，方便在 NAS 背景執行時查看日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)

# 強制標準輸出使用 UTF-8
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
except:
    pass

# ================= 設定區 =================
# 建議將 Token 放在環境變數中，若無則使用預設值
TELEGRAM_TOKEN = os.getenv('TG_TOKEN', '8540551367:AAGXmoATXq3hranSkxUiEA6IPzMNvNrESog')
CHAT_ID = os.getenv('TG_CHAT_ID', '6824247597')
STOCK_FILE = 'stock.txt'
# ========================================

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

class StockMonitor:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': 'https://mis.twse.com.tw/'
        })

    def send_telegram_message(self, message_text):
        """發送 Telegram 通知"""
        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        final_text = f"<b>📈 台股即時報價</b>\n<code>更新時間: {now_str}</code>\n{message_text}"

        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = {'chat_id': CHAT_ID, 'text': final_text, 'parse_mode': 'HTML'}

        try:
            resp = self.session.post(url, data=data, verify=False, timeout=15)
            resp.raise_for_status()
            logging.info("Telegram update sent successfully.")
        except Exception as e:
            logging.error(f"Telegram error: {e}")

    def load_stocks(self):
        """從檔案讀取股票代號"""
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, STOCK_FILE)
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return [line.strip() for line in f if line.strip() and not line.startswith('#')]
        except Exception as e:
            logging.error(f"File loading error: {e}")
            return []

    def fetch_data(self):
        target_stocks = self.load_stocks()
        if not target_stocks: return

        # 簡單判斷開盤日 (週一至週五)
        if datetime.datetime.now().weekday() > 4:
            logging.info("Market is closed (Weekend).")
            return

        # 構造查詢字串 (同時查上市與上櫃)
        query = "|".join([f"tse_{s}.tw|otc_{s}.tw" for s in target_stocks])
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch={query}&json=1&_={int(time.time() * 1000)}"

        try:
            res = self.session.get(url, verify=False, timeout=20)
            res.raise_for_status()
            data = res.json()

            if 'msgArray' not in data or not data['msgArray']:
                logging.warning("No valid price data received. (Might be a holiday)")
                return

            msg_items = []
            processed = set()

            for s in data['msgArray']:
                code = s.get('c')
                if not code or code in processed: continue
                
                name = s.get('n', '未知')
                y_price = float(s.get('y', 0)) # 昨收
                
                # 價格取值邏輯：成交 > 買一 > 開盤
                price_raw = s.get('z', s.get('b', s.get('o', '-')))
                if price_raw == '-' or not price_raw: continue
                
                # 處理五檔價格字串 (例如 "100.5_100.6_...")
                curr_price = float(price_raw.split('_')[0]) if '_' in str(price_raw) else float(price_raw)
                
                # 計算漲跌
                diff = curr_price - y_price
                percent = (diff / y_price * 100) if y_price > 0 else 0
                
                mark = "🔺" if diff > 0 else "🔻" if diff < 0 else "─"
                sign = "+" if diff > 0 else ""
                
                item = f"\n• <b>{name}</b> ({code})\n  價格: <code>{curr_price:7.2f}</code> {mark} {sign}{diff:.2f} ({sign}{percent:.2f}%)"
                msg_items.append(item)
                processed.add(code)

            if msg_items:
                self.send_telegram_message("".join(msg_items))

        except Exception as e:
            logging.error(f"System error: {e}")

if __name__ == "__main__":
    monitor = StockMonitor()
    monitor.fetch_data()