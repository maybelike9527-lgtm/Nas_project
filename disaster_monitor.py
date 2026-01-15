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
user_site_pkg = os.path.expanduser("~/.local/lib/python3.8/site-packages")
if user_site_pkg not in sys.path:
    sys.path.append(user_site_pkg)

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
CWA_API_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-C0032-001"


def get_config(key):
    """從資料庫讀取設定值"""
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
    """透過 Telegram 發送訊息"""
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


# ================= 📍 地理位置處理邏輯 =================
def get_township_from_location(payload_str):
    """解析座標 JSON 並轉譯為行政區名稱"""
    if not GEOPY_AVAILABLE:
        send_alert("❌ <b>環境錯誤</b>：無法載入 geopy 套件。")
        return None

    try:
        data = json.loads(payload_str)
        # 解析原始訊息中的 location 欄位
        if "location" in data:
            lat = data["location"]["latitude"]
            lon = data["location"]["longitude"]

            geolocator = Nominatim(user_agent="nas_weather_bot")
            location = geolocator.reverse(f"{lat}, {lon}", language='zh-TW')
            address = location.raw.get('address', {})

            # 提取行政區 (鄉鎮市區)
            township = address.get('suburb') or address.get('town') or address.get('city_district') or address.get(
                'village')
            if township:
                return township
        return None
    except Exception as e:
        logger.error(f"位置解析失敗: {e}")
        return None


# ================= 🌤️ 氣象查詢主邏輯 =================
def monitor_weather_forecast(input_param=None):
    api_key = get_config('cwa_api_key')
    # 預設位置
    location = get_config('forecast_location') or "臺中市"

    # 優先檢查路徑：是否有座標存檔 JSON
    json_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'current_location.json')

    if input_param:
        # 如果執行時帶有參數（可能是 JSON 或地名）
        detected_town = get_township_from_location(input_param)
        if detected_town:
            location = detected_town
        else:
            try:
                json.loads(input_param)
            except ValueError:
                location = input_param
    elif os.path.exists(json_file_path):
        # 如果沒帶參數但存在存檔，則讀取存檔
        try:
            with open(json_file_path, 'r', encoding='utf-8') as f:
                saved_payload = f.read()
            detected_town = get_township_from_location(saved_payload)
            if detected_town:
                location = detected_town
                logger.info(f"讀取座標存檔進行查詢：{location}")
        except Exception as e:
            logger.error(f"讀取存檔失敗: {e}")

    # 1. 時間邏輯：20:00~23:59 查詢明日，其餘查詢今日
    now = datetime.now()
    if 20 <= now.hour <= 23:
        target_label = "明日"
        time_index = 1
    else:
        target_label = "今日"
        time_index = 0

    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': location}
        resp = requests.get(CWA_API_URL, params=params, timeout=20, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('location'):
            send_alert(f"❓ 無法取得「{location}」的氣象資料。")
            return

        elements = data['records']['location'][0]['weatherElement']

        # 2. 獲取天氣狀況 (Wx)、降雨率 (PoP) 及溫度
        weather_info = {
            'Wx': '',  # 天氣狀況
            'PoP': '',  # 降雨率
            'MinT': '',  # 最低溫
            'MaxT': ''  # 最高溫
        }

        for el in elements:
            e_name = el['elementName']
            if e_name in weather_info:
                weather_info[e_name] = el['time'][time_index]['parameter']['parameterName']

        # 組合 Telegram 報告訊息
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