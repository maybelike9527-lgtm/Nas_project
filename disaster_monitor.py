import requests
import sqlite3
import os
import logging
import sys
import io
import urllib3
from datetime import datetime
from geopy.geocoders import Nominatim

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
    """透過 Telegram Bot 發送警報訊息"""
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


# ================= 📍 地理位置轉譯工具 =================
def reverse_geocoding(lat, lon):
    """將經緯度座標轉為台灣行政區名稱"""
    try:
        geolocator = Nominatim(user_agent="nas_weather_bot")
        location = geolocator.reverse(f"{lat}, {lon}", language='zh-TW')
        address = location.raw.get('address', {})
        # 優先抓取行政區
        township = address.get('suburb') or address.get('town') or address.get('city_district') or address.get(
            'village')
        return township
    except Exception as e:
        logger.error(f"座標轉譯失敗: {e}")
        return None


# ================= 🌤️ 氣象預報核心邏輯 =================
def monitor_weather_forecast(input_param=None):
    api_key = get_config('cwa_api_key')

    # 預設位置
    location = get_config('forecast_location') or "臺中市"

    # 判斷輸入參數
    if input_param:
        if "," in input_param:  # 收到的是座標 "lat,lon"
            try:
                lat, lon = input_param.split(",")
                logger.info(f"執行座標逆向轉譯: {lat}, {lon}")
                # [除錯測試] 顯示解析過程
                send_alert(f"⚙️ 正在轉譯座標：<code>{lat}, {lon}</code>")

                detected_town = reverse_geocoding(lat, lon)
                if detected_town:
                    location = detected_town
                else:
                    send_alert("❌ 無法從座標辨識行政區，使用預設地區。")
            except Exception as e:
                logger.error(f"座標解析錯誤: {e}")
        else:  # 收到的是純地區名稱
            location = input_param

    # --- 氣象查詢邏輯 (維持您之前的修正：20:00 後查明天) ---
    now = datetime.now()
    time_index = 1 if now.hour >= 20 else 0
    target_label = "明日" if now.hour >= 20 else "今日"

    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': location}
        resp = requests.get(CWA_API_URL, params=params, timeout=20, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('location'):
            send_alert(f"❓ 找不到「{location}」的預報，請確認該地區名稱是否正確。")
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
        logger.error(f"預報執行異常: {e}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        monitor_weather_forecast(sys.argv[1])
    else:
        monitor_weather_forecast()