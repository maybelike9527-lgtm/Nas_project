import sqlite3
import os

DB_NAME = "account_book.db"


def upgrade_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_NAME)
    conn = sqlite3.connect(db_path, timeout=20)
    cursor = conn.cursor()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")

        # 建立設定表
        cursor.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)')

        # 寫入您的 DSM 登入資訊與下載設定
        # 已新增 Gemini API Key
        settings = [
            ('tele_token', '8540551367:AAGXmoATXq3hranSkxUiEA6IPzMNvNrESog'),
            ('tele_chat_id', '6824247597'),
            ('cwa_api_key', 'CWA-728B43E3-05D6-4AA9-8A5E-69B52BCEDE77'),
            ('forecast_location', '臺中市'),
            ('download_path', '/volume1/淳/影片'),
            ('dsm_url', 'http://192.168.50.191:5000'),
            ('dsm_user', 'holiness'),
            ('dsm_pass', 'Sonygood7576'),
            ('gemini_api_key', 'AIzaSyAErxnCa8VSZ7ONIGyJ9T1Aww3Z7oxLUHU')
        ]

        # 使用 INSERT OR REPLACE 確保更新最新的設定
        cursor.executemany("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", settings)

        # 建立必要的系統表 (鎖定表與災害狀態表)
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS disaster_status (alert_type TEXT PRIMARY KEY, last_content TEXT, update_time TIMESTAMP)')
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS system_locks (lock_name TEXT PRIMARY KEY, is_locked INTEGER DEFAULT 0, user_id TEXT, lock_time TEXT)')
        cursor.execute("INSERT OR IGNORE INTO system_locks (lock_name, is_locked) VALUES ('accounting', 0)")

        conn.commit()
        print("✅ 資料庫升級成功：Gemini Key 與 DSM 資訊已更新。")
    except Exception as e:
        print(f"❌ 錯誤：{e}")
    finally:
        conn.close()


if __name__ == "__main__":
    upgrade_database()