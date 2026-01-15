import requests
import sqlite3
import os
import logging
import sys
import io
import urllib3
import json
from datetime import datetime

# ================= 🔧 環境路徑修正 =================
# 確保 NAS 能找到使用者目錄下的 geopy 套件
nas_local_path = "/volume1/homes/holiness/.local/lib/python3.8/site-packages"
if os.path.exists(nas_local_path) and nas_local_path not in sys.path:
    sys.path.append(nas_local_path)

try:
    from geopy.geocoders import Nominatim

    GEOPY_AVAILABLE = True
except ImportError:
    GEOPY_AVAILABLE = False

# ================= 📝 LOGGING 系統設定 =================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "account_book.db")
# 使用縣市級 API
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
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'}
    try:
        requests.post(url, data=payload, timeout=15, verify=False)
    except Exception as e:
        logger.error(f"Telegram 發送異常: {e}")


# ================= 📍 地理位置處理邏輯 (升級為縣市級) =================
def get_city_from_location(payload_str):
    """解析座標並轉譯為縣市級名稱 (例如：臺中市)"""
    if not GEOPY_AVAILABLE:
        send_alert("❌ <b>環境錯誤</b>：無法載入 geopy 套件。")
        return None

    try:
        data = json.loads(payload_str)
        if "location" in data:
            lat = data["location"]["latitude"]
            lon = data["location"]["longitude"]

            geolocator = Nominatim(user_agent="nas_weather_bot")
            location = geolocator.reverse(f"{lat}, {lon}", language='zh-TW')
            address = location.raw.get('address', {})

            # --- 關鍵修正：優先抓取縣市 (city) 欄位 ---
            # 在台灣地圖資料中，通常存在於 'city' 或 'state' 欄位
            city = address.get('city') or address.get('state') or address.get('county')

            # 確保名稱符合氣象局格式 (如：臺中市)
            if city:
                city = city.replace("台", "臺")  # 統一使用繁體正體字以符合 API 規範
                return city
        return None
    except Exception as e:
        logger.error(f"位置解析失敗: {e}")
        return None


# ================= 🌤️ 氣象查詢主邏輯 =================
def monitor_weather_forecast(input_param=None):
    api_key = get_config('cwa_api_key')
    location = get_config('forecast_location') or "臺中市"

    # 檢查是否有存檔
    json_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'current_location.json')

    if input_param:
        detected_city = get_city_from_location(input_param)
        if detected_city:
            location = detected_city
    elif os.path.exists(json_file_path):
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                saved_payload = f.read()
            detected_city = get_city_from_location(saved_payload)
            if detected_city:
                location = detected_city
        except Exception as e:
            logger.error(f"讀取存檔失敗: {e}")

    # 時間邏輯：20:00 後查詢明日預報
    now = datetime.now()
    time_index = 1 if now.hour >= 20 else 0
    target_label = "明日" if now.hour >= 20 else "今日"

    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': location}
        resp = requests.get(CWA_API_URL, params=params, timeout=20, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('location'):
            send_alert(f"❓ 找不到「{location}」的縣市預報，請確認地名。")
            return

        elements = data['records']['location'][0]['weatherElement']
        weather_info = {'Wx': '', 'PoP': '', 'MinT': '', 'MaxT': ''}

        for el in elements:
            e_name = el['elementName']
            if e_name in weather_info:
                weather_info[e_name] = el['time'][time_index]['parameter']['parameterName']

        msg = f"🌤️ <b>{target_label}天氣預報 ({location})</b>\n"
        msg += f"━━━━━━━━━━━━━━━━\n"
        msg += f"📝 天氣狀況：<b>{weather_info['Wx']}</b>\n"
        msg += f"🌡️ 氣溫範圍：<b>{weather_info['MinT']}°C ~ {weather_info['MaxT']}°C</b>\n"
        msg += f"☔ 降雨機率：<b>{weather_info['PoP']}%</b>\n\n"
        msg += f"🕒 報告時間：{now.strftime('%H:%M')}"

        send_alert(msg)
    except Exception as e:
        logger.error(f"氣象抓取異常: {e}")


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    monitor_weather_forecast(arg)