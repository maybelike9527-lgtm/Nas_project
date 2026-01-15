import sqlite3
import os
import json
import requests
import logging
import time
import urllib3
from datetime import datetime

# ================= 設定區 =================
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# DS120j 記憶體保護限制：同時只允許幾個任務下載？
MAX_ACTIVE_DOWNLOADS = 3

# 死種判定：0MB 的任務如果超過幾小時沒動靜就刪除？
DEAD_MAGNET_TIMEOUT_HOURS = 3

SAFE_SIZE_THRESHOLD = 104857600
DB_NAME = "account_book.db"
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(CURRENT_DIR, 'ds_pilot.log')

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger()


class SynologyAIPilot:
    def __init__(self):
        self.config = self._load_config()
        self.sid = None
        self.base_url = self.config.get('dsm_url', 'http://192.168.50.191:5000')
        self.gemini_key = self.config.get('gemini_api_key')

    def _load_config(self):
        db_path = os.path.join(CURRENT_DIR, DB_NAME)
        if not os.path.exists(db_path):
            logger.error("❌ 找不到資料庫")
            return {}
        conn = sqlite3.connect(db_path)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM config")
            return {key: value for key, value in cursor.fetchall()}
        finally:
            conn.close()

    def login(self):
        api_path = "/webapi/auth.cgi"
        params = {
            'api': 'SYNO.API.Auth', 'version': '3', 'method': 'login',
            'account': self.config.get('dsm_user'),
            'passwd': self.config.get('dsm_pass'),
            'session': 'DownloadStation', 'format': 'cookie'
        }
        try:
            resp = requests.get(f"{self.base_url}{api_path}", params=params, timeout=30, verify=False)
            if resp.json().get('success'):
                self.sid = resp.json()['data']['sid']
                return True
            logger.error(f"登入失敗: {resp.text}")
            return False
        except Exception as e:
            logger.error(f"連線錯誤: {e}")
            return False

    def get_tasks(self):
        if not self.sid: return []
        try:
            resp = requests.get(
                f"{self.base_url}/webapi/DownloadStation/task.cgi",
                params={'api': 'SYNO.DownloadStation.Task', 'version': '1', 'method': 'list',
                        'additional': 'detail,transfer', '_sid': self.sid},
                timeout=30,
                verify=False
            )
            return resp.json()['data']['tasks'] if resp.json().get('success') else []
        except Exception as e:
            logger.error(f"獲取任務錯誤: {e}")
            return []

    def execute_action(self, task_id, action, reason):
        api_path = "/webapi/DownloadStation/task.cgi"
        method = action
        params = {}

        if action == "delete":
            params = {'force_complete': 'false'}

        # 組合參數
        final_params = {
            'api': 'SYNO.DownloadStation.Task', 'version': '1',
            'method': method, 'id': task_id, '_sid': self.sid
        }
        final_params.update(params)

        try:
            resp = requests.get(f"{self.base_url}{api_path}", params=final_params, timeout=10, verify=False)
            if resp.json().get('success'):
                logger.info(f"✨ 執行 [{action.upper()}]: {reason}")
            else:
                logger.warning(f"⚠️ 失敗 [{action}]: {resp.text}")
        except:
            pass

    def ask_gemini_for_decision(self, tasks):
        if not self.gemini_key or not tasks: return None

        # 1. 整理數據，加入「存在時間」計算
        current_ts = time.time()
        task_summary = []

        for t in tasks:
            size_mb = int(t['size']) / 1048576
            downloaded = float(t['additional']['transfer']['size_downloaded'])
            speed = t['additional']['transfer']['speed_download']

            # 計算加入多久了 (小時)
            create_time = t['additional']['detail']['create_time']
            age_hours = round((current_ts - create_time) / 3600, 1)

            # 計算進度
            progress = (downloaded / int(t['size']) * 100) if int(t['size']) > 0 else 0

            task_summary.append({
                "id": t['id'],
                "name": t['title'],
                "size_mb": round(size_mb, 1),
                "status": t['status'],  # waiting, downloading, paused, error
                "speed_kb": round(speed / 1024, 1),
                "progress_pct": round(progress, 1),
                "age_hours": age_hours  # 這很重要，讓 AI 知道它卡多久了
            })

        # 2. 進階版 Prompt：交通指揮官模式
        prompt = f"""
        你現在是 Synology DS120j (低記憶體) 的下載調度員。
        你的目標是：最大化下載效率，並清除無效任務。

        【環境限制】：
        1. **同時下載上限**：只能有 **{MAX_ACTIVE_DOWNLOADS}** 個任務處於 "downloading" 或 "waiting" 狀態。其他的必須 "pause"。
        2. **死種判定**：如果檔案大小為 0MB (或進度 0%) 且存在時間超過 {DEAD_MAGNET_TIMEOUT_HOURS} 小時，代表是死種，必須 "delete"。

        【決策邏輯】：
        1. **DELETE**: 針對死種 (0MB + age > {DEAD_MAGNET_TIMEOUT_HOURS}h) 或廣告檔。
        2. **RESUME**: 從剩下的任務中，選出 **最有希望完成的前 {MAX_ACTIVE_DOWNLOADS} 名** (依據速度、進度、或是否快完成了)。
        3. **PAUSE**: 所有沒被選上 RESUME 的任務，通通設為 PAUSE，以釋放資源。
        4. **KEEP**: 如果任務已經是理想狀態 (例如該暫停的已經暫停了)，就回傳 keep。

        【目前任務列表】：
        {json.dumps(task_summary, ensure_ascii=False)}

        請回傳 JSON 格式 (不要 Markdown)：
        [
            {{"id": "task_1", "action": "delete", "reason": "死種：卡在0MB超過3小時"}},
            {{"id": "task_2", "action": "resume", "reason": "速度快，優先下載"}},
            {{"id": "task_3", "action": "pause", "reason": "資源禮讓給高優先級任務"}}
        ]
        """

        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={self.gemini_key}"

        for attempt in range(2):  # 簡單重試
            try:
                response = requests.post(
                    url, headers={'Content-Type': 'application/json'},
                    json={"contents": [{"parts": [{"text": prompt}]}]}, timeout=60
                )
                if response.status_code == 200:
                    text = response.json()['candidates'][0]['content']['parts'][0]['text']
                    text = text.replace("```json", "").replace("```", "").strip()
                    return json.loads(text)
                time.sleep(5)
            except:
                continue
        return None

    def run(self):
        logger.info(">>> AI 調度員啟動 (流量管制模式) <<<")
        if not self.login(): return

        tasks = self.get_tasks()
        if not tasks:
            logger.info("💤 無任務。")
            return

        task_map = {t['id']: t for t in tasks}
        decisions = self.ask_gemini_for_decision(tasks)

        if decisions:
            logger.info("🤖 AI 決策執行中...")
            for decision in decisions:
                task_id = decision['id']
                action = decision.get('action')
                reason = decision.get('reason')

                original_task = task_map.get(task_id)
                if not original_task: continue

                # === 安全檢查 ===
                original_size = int(original_task['size'])
                current_status = original_task['status']

                # 1. 刪除保護 (大檔不刪)
                if action == 'delete':
                    if original_size > SAFE_SIZE_THRESHOLD:
                        logger.warning(f"⛔ [攔截刪除] 保留大檔: {original_task['title']}")
                        continue
                    else:
                        self.execute_action(task_id, action, reason)

                # 2. 狀態優化 (如果已經是 pause 就不用再發送 pause 指令，節省 API 呼叫)
                elif action == 'pause':
                    if current_status == 'paused':
                        logger.info(f"維持暫停: {original_task['title']}")
                    else:
                        self.execute_action(task_id, action, reason)

                # 3. 狀態優化 (如果已經是 downloading 就不用再 resume)
                elif action == 'resume':
                    if current_status in ['downloading', 'seeding', 'extracting']:
                        logger.info(f"維持下載: {original_task['title']}")
                    else:
                        self.execute_action(task_id, action, reason)

                else:
                    logger.info(f"AI 建議維持: {original_task['title']}")

            logger.info("✅ 調度完成。")
        else:
            logger.warning("❌ 無法取得 AI 決策。")


if __name__ == "__main__":
    SynologyAIPilot().run()