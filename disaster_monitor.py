import requests
import sqlite3
import os
import logging
import sys
import io
import urllib3
from datetime import datetime

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
CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"


def get_config(key):
    try:
        conn = sqlite3.connect(DB_PATH, timeout=20)
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else None
    except Exception as e:
        logger.error(f"資料庫讀取失敗: {e}")
        return None


def send_alert(message):
    token = get_config('tele_token')
    chat_id = get_config('tele_chat_id')
    if not token or not chat_id: return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
    requests.post(url, data=payload, timeout=15, verify=False)


# ================= 🌤️ 氣象預報邏輯 (修正版) =================
def monitor_weather_forecast():
    api_key = get_config('cwa_api_key')
    location = get_config('forecast_location') or "臺中市"

    if not api_key:
        logger.error("缺少 API Key")
        return

    # 判斷查詢時段：20:00 後查明天，其餘查今天
    now = datetime.now()
    if now.hour >= 20:
        target_label = "明日"
        time_index = 1  # 氣象署 API 第二個時段通常為明天白天
    else:
        target_label = "今日"
        time_index = 0  # 第一個時段為當前/今日

    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': location}
        resp = requests.get(CWA_API_URL, params=params, timeout=20, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('location'):
            logger.error(f"找不到地區資料：{location}")
            return

        elements = data['records']['location'][0]['weatherElement']

        weather_info = {
            'Wx': '',  # 天氣現象
            'PoP': '',  # 降雨機率
            'MinT': '',  # 最低溫
            'MaxT': ''  # 最高溫
        }

        for el in elements:
            e_name = el['elementName']
            if e_name in weather_info:
                # 取得對應時段的資料
                weather_info[e_name] = el['time'][time_index]['parameter']['parameterName']

        msg = f"🌤️ <b>{target_label}天氣預報 ({location})</b>\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"📝 天氣狀況：<b>{weather_info['Wx']}</b>\n"
        msg += f"🌡️ 氣溫範圍：<b>{weather_info['MinT']}°C ~ {weather_info['MaxT']}°C</b>\n"
        msg += f"☔ 降雨機率：<b>{weather_info['PoP']}%</b>\n\n"
        msg += f"🕒 報告時間：{now.strftime('%H:%M')}"

        send_alert(msg)
        logger.info(f"{target_label}預報發送成功")

    except Exception as e:
        logger.error(f"預報抓取失敗: {e}")


if __name__ == "__main__":
    monitor_weather_forecast()