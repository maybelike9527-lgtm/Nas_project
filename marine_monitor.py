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

# 1. 自動氣象站 (O-A0001-001) -> 包含 梧棲、臺中電廠
API_AUTO = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"
# 2. 海氣象資料浮標 (O-A0018-001) -> 包含 臺中浮標 (C4F01)
API_BUOY = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0018-001"

# 監控優先順序：(名稱, API類型)
PRIORITY_STATIONS = [
    ("梧棲", "AUTO"),
    ("臺中", "BUOY"),
    ("臺中電廠", "AUTO")
]


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
            logger.info("Telegram 風力報告推播成功")
        else:
            logger.error(f"Telegram 推播失敗，狀態碼: {resp.status_code}")
    except Exception as e:
        logger.error(f"Telegram 連線異常: {e}")


# ================= 🌬️ 風力強度換算 =================
def to_scale(speed):
    try:
        s = float(speed)
        if s < 0: return "?"
        if s < 0.3: return "0"
        if s < 1.6: return "1"
        if s < 3.4: return "2"
        if s < 5.5: return "3"
        if s < 8.0: return "4"
        if s < 10.8: return "5"
        if s < 13.9: return "6"
        if s < 17.2: return "7"
        if s < 20.8: return "8"
        if s < 24.5: return "9"
        if s < 28.5: return "10"
        if s < 32.7: return "11"
        return "12+"
    except:
        return "?"


# ================= 🔍 核心監測邏輯 =================
def fetch_wind_data(api_key, station_name, source_type):
    """嘗試從指定 API 獲取該測站的風力資料"""
    url = API_AUTO if source_type == "AUTO" else API_BUOY
    try:
        params = {
            'Authorization': api_key,
            'format': 'JSON',
            'StationName': station_name
        }
        resp = requests.get(url, params=params, timeout=15, verify=False)
        data = resp.json()

        if not data.get('records') or not data['records'].get('Station'):
            return None

        # 取得第一筆符合的測站資料
        st = data['records']['Station'][0]
        obs_time = st['ObsTime']['DateTime']

        w_speed = -99
        w_dir = -99
        g_speed = -99

        # 依據不同 API 解析欄位
        if source_type == "AUTO":
            we = st['WeatherElement']
            w_speed = we.get('WindSpeed', -99)
            w_dir = we.get('WindDirection', -99)
            g_speed = we.get('GustInfo', {}).get('PeakGustSpeed', -99)
        else:
            we = st['WeatherElement']
            w_speed = we.get('WindSpeed', -99)
            w_dir = we.get('WindDirection', -99)
            g_speed = we.get('GustSpeed', -99)

        # 邏輯修正：只要平均風速有效 (>=0)，就算有效資料，不強制檢查陣風
        if float(w_speed) < 0:
            # 如果連平均風速都是 -99，才視為無效，嘗試下一個測站
            logger.warning(f"測站 {station_name} 平均風速無效 ({w_speed})，嘗試下一個...")
            return None

        return {
            'name': station_name,
            'type': '資料浮標' if source_type == "BUOY" else '氣象站',
            'time': obs_time,
            'speed': w_speed,
            'dir': w_dir,
            'gust': g_speed
        }

    except Exception as e:
        logger.error(f"查詢 {station_name} 失敗: {e}")
        return None


def monitor_port_wind():
    api_key = get_config('cwa_api_key')
    if not api_key:
        logger.error("缺少 API Key")
        return

    valid_data = None

    # 依序嘗試清單中的測站
    for name, s_type in PRIORITY_STATIONS:
        logger.info(f"嘗試獲取：{name} ({s_type})...")
        valid_data = fetch_wind_data(api_key, name, s_type)
        if valid_data:
            break

    if not valid_data:
        logger.error("所有備援測站皆無有效風力數據 (-99)")
        send_alert("⚠️ <b>台中港區風力資料異常</b>\n氣象署所有測站目前皆回傳無效數據 (-99)，請稍後再試。")
        return

    # 格式化輸出
    dt_obj = datetime.strptime(valid_data['time'], "%Y-%m-%dT%H:%M:%S+08:00")
    time_str = dt_obj.strftime("%m/%d %H:%M")

    scale_avg = to_scale(valid_data['speed'])

    # 陣風顯示邏輯修正
    if float(valid_data['gust']) >= 0:
        scale_gust = to_scale(valid_data['gust'])
        gust_str = f"<b>{valid_data['gust']} m/s ({scale_gust}級)</b>"
    else:
        gust_str = "無最大陣風資料"

    msg = f"⚓ <b>台中港區風力回報</b>\n"
    msg += f"📍 來源：{valid_data['name']} ({valid_data['type']})\n"
    msg += f"━━━━━━━━━━━━━━━━\n"
    msg += f"🌬️ 平均風速：<b>{valid_data['speed']} m/s ({scale_avg}級)</b>\n"
    msg += f"💨 最大陣風：{gust_str}\n"
    msg += f"🧭 風向：{valid_data['dir']}°\n"
    msg += f"\n🕒 觀測時間：{time_str}"

    send_alert(msg)


if __name__ == "__main__":
    monitor_port_wind()