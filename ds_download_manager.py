import requests
import json
import sqlite3
import os
import logging
import sys
import io
import urllib3
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


# ================= 📦 DS GET API 工具 =================
class SynologyDS:
    def __init__(self, url, user, password):
        self.base_url = url.rstrip('/')
        self.user = user
        self.password = password
        self.sid = None

    def login(self):
        """登入 DSM 並取得 Session ID (SID)"""
        url = f"{self.base_url}/webapi/auth.cgi?api=SYNO.API.Auth&version=3&method=login&account={self.user}&passwd={self.password}&session=DownloadStation&format=cookie"
        try:
            resp = requests.get(url, verify=False, timeout=10)
            data = resp.json()
            if data.get('success'):
                self.sid = data['data']['sid']
                logger.info("DS API 登入成功")
                return True
            else:
                logger.error(f"DS 登入失敗：{data.get('error')}")
                return False
        except Exception as e:
            logger.error(f"DS 連線異常: {e}")
            return False

    def add_task(self, magnet_url):
        """新增 BT 下載任務"""
        if not self.sid and not self.login(): return False

        url = f"{self.base_url}/webapi/DownloadStation/task.cgi"
        params = {
            'api': 'SYNO.DownloadStation.Task',
            'version': '1',
            'method': 'create',
            '_sid': self.sid,
            'uri': magnet_url
        }
        try:
            resp = requests.get(url, params=params, verify=False, timeout=15)
            return resp.json().get('success')
        except Exception as e:
            logger.error(f"新增下載任務異常: {e}")
            return False


# ================= 🚀 抓取與執行邏輯 =================
def get_config(key):
    conn = sqlite3.connect(DB_PATH)
    res = conn.execute("SELECT value FROM config WHERE key = ?", (key,)).fetchone()
    conn.close()
    return res[0] if res else None


def process_javd_download(target_url):
    """從 JAVD.me 頁面抓取磁力連結並送往 DS"""
    logger.info(f"正在分析網頁：{target_url}")

    try:
        # 1. 抓取網頁內容
        resp = requests.get(target_url, timeout=15, verify=False)
        resp.encoding = 'utf-8'
        soup = BeautifulSoup(resp.text, 'html.parser')

        # 2. 尋找磁力連結 (JAVD.me 的結構通常在 tab-page 的 downloads 區塊)
        magnets = []
        for a in soup.find_all('a', href=True):
            if a['href'].startswith('magnet:?xt=urn:btih:'):
                magnets.append(a['href'])

        if not magnets:
            logger.warning("該頁面未找到任何磁力連結")
            return "❌ 找不到下載連結。"

        # 3. 取得 DS 設定並派送任務
        dsm_url = get_config('dsm_url')
        dsm_user = get_config('dsm_user')
        dsm_pass = get_config('dsm_pass')

        if not all([dsm_url, dsm_user, dsm_pass]):
            return "❌ 缺少 DSM API 設定資料。"

        ds = SynologyDS(dsm_url, dsm_user, dsm_pass)
        success_count = 0
        for m in magnets[:2]:  # 範例僅抓取前兩個連結，避免重複下載
            if ds.add_task(m):
                success_count += 1

        return f"✅ 成功加入 {success_count} 個下載任務到 Download Station！"

    except Exception as e:
        logger.error(f"處理失敗: {e}")
        return f"❌ 執行發生錯誤: {e}"


if __name__ == "__main__":
    if len(sys.argv) > 1:
        result = process_javd_download(sys.argv[1])
        print(result)