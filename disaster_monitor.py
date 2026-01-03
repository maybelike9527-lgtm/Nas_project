import requests
import sqlite3
import os
import logging
import sys
import io
import urllib3
from datetime import datetime
from bs4 import BeautifulSoup

# ================= 📝 LOGGING 系統設定 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# ================= 🔤 環境初始化 =================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")
DGPA_URL = "https://www.dgpa.gov.tw/typh/daily/nds.html"
# 氣象署一般天氣預報 API (以台北市為例，您可於 DB config 調整地區)
CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"


# ================= 📦 資料庫工具 =================
def get_config(key):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.execute("PRAGMA journal_mode=WAL;")
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"資料庫讀取失敗 (鍵名: {key}): {e}")
        return None


def update_disaster_status(alert_type, content):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        conn.execute(
            "INSERT OR REPLACE INTO disaster_status (alert_type, last_content, update_time) VALUES (?, ?, ?)",
            (alert_type, content, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"更新災害狀態至資料庫失敗: {e}")


# ================= 🤖 Telegram 發送邏輯 =================
def send_alert(message):
    token = get_config('tele_token')
    chat_id = get_config('tele_chat_id')
    if not token or not chat_id:
        logger.error("發送中止：資料庫中缺少 Telegram 設定")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
    try:
        resp = requests.post(url, data=payload, timeout=15, verify=False)
        if resp.status_code == 200:
            logger.info("Telegram 警報推播成功")
        else:
            logger.error(f"Telegram 推播失敗，狀態碼: {resp.status_code}")
    except Exception as e:
        logger.error(f"Telegram 連線異常: {e}")


# ================= 🌤️ 氣象預報邏輯 =================
def monitor_weather_forecast():
    """每日 20:00 獲取明日高低溫預報"""
    now_hour = datetime.now().hour
    if now_hour != 20:
        logger.info("非 20:00 預報時段，跳過氣溫檢查")
        return

    api_key = get_config('cwa_api_key')
    if not api_key:
        logger.error("預報中止：資料庫中缺少 cwa_api_key")
        return

    logger.info("正在獲取明日氣溫預報數據...")
    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': '臺北市'}
        resp = requests.get(CWA_API_URL, params=params, timeout=20)
        data = resp.json()

        elements = data['records']['location'][0]['weatherElement']
        # 取得明日白天的預報 (通常在陣列的第二個時段)
        min_t = ""
        max_t = ""
        for el in elements:
            if el['elementName'] == 'MinT': min_t = el['time'][1]['parameter']['parameterName']
            if el['elementName'] == 'MaxT': max_t = el['time'][1]['parameter']['parameterName']

        msg = f"🌡️ <b>明日天氣預報 (臺北市)</b>\n━━━━━━━━━━━━━━━━\n最低溫度：{min_t}°C\n最高溫度：{max_t}°C\n\n🕒 預報發佈時間：20:00"
        send_alert(msg)
    except Exception as e:
        logger.error(f"氣象預報抓取失敗: {e}")


# ================= 🚀 停班課監控邏輯 =================
def monitor_dgpa():
    logger.info("開始請求人事行政總局官網數據...")
    try:
        resp = requests.get(DGPA_URL, timeout=20, verify=False)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')
        table = soup.find('table', {'summary': '今日天然災害停止上班上課情形'})

        current_status = "全國今日正常上班上課。"
        if table:
            results = []
            for row in table.find_all('tr')[1:]:
                cols = row.find_all('td')
                if len(cols) >= 2:
                    results.append(f"<b>{cols[0].get_text(strip=True)}</b>：{cols[1].get_text(strip=True)}")
            current_status = "\n".join(results) if results else current_status

        # 讀取上次狀態避免重覆發送
        conn = sqlite3.connect(DB_PATH)
        res = conn.execute("SELECT last_content FROM disaster_status WHERE alert_type='DGPA'").fetchone()
        conn.close()
        last_status = res[0] if res else ""

        if current_status != last_status:
            logger.info("偵測到停班課資訊更新")
            msg = f"📢 <b>天然災害停班停課通報</b>\n━━━━━━━━━━━━━━━━\n{current_status}"
            send_alert(msg)
            update_disaster_status('DGPA', current_status)
        else:
            logger.info("停班課資訊無異動")
    except Exception as e:
        logger.error(f"停班課監控執行失敗: {e}")


if __name__ == "__main__":
    logger.info("災害監控任務啟動")
    monitor_dgpa()
    monitor_weather_forecast()
    logger.info("監控任務執行完畢")