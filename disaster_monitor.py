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


# ================= 🌤️ 氣象預報核心邏輯 =================
def monitor_weather_forecast(override_location=None):
    """獲取氣象預報資訊 (支援時段判斷與外部參數傳入)"""
    api_key = get_config('cwa_api_key')
    # 優先序：外部參數 > 資料庫設定 > 預設值
    location = override_location or get_config('forecast_location') or "臺中市"

    if not api_key:
        logger.error("缺少 API Key")
        return

    # 1. 判斷查詢時段：20:00 後查明天 (API 索引值 1)，其餘查今天 (索引值 0)
    now = datetime.now()
    if now.hour >= 20:
        target_label = "明日"
        time_index = 1
    else:
        target_label = "今日"
        time_index = 0

    logger.info(f"正在獲取 {target_label} 氣溫預報數據 ({location})...")

    try:
        params = {'Authorization': api_key, 'format': 'JSON', 'locationName': location}
        resp = requests.get(CWA_API_URL, params=params, timeout=20, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('location'):
            logger.error(f"找不到地區資料：{location}")
            # 若為外部查詢失敗，回報給使用者
            if override_location:
                send_alert(f"❌ 找不到地區「{location}」的預報資料。")
            return

        elements = data['records']['location'][0]['weatherElement']

        # 初始化氣象資料字典
        weather_info = {
            'Wx': '',   # 天氣現象
            'PoP': '',  # 降雨機率
            'MinT': '', # 最低溫
            'MaxT': ''  # 最高溫
        }

        # 遍歷氣象要素並提取對應時段資料
        for el in elements:
            e_name = el['elementName']
            if e_name in weather_info:
                weather_info[e_name] = el['time'][time_index]['parameter']['parameterName']

        # 2. 組合 Telegram 訊息格式
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
    # 3. 處理外部參數傳入 (支援 bot_listener 呼叫隨身氣象台)
    if len(sys.argv) > 1:
        # sys.argv[1] 為 bot_listener 傳來的行政區名稱
        monitor_weather_forecast(sys.argv[1])
    else:
        # 預設執行 (讀取資料庫設定)
        monitor_weather_forecast()