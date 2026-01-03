import sqlite3
import os

DB_NAME = "account_book.db"


def upgrade_database():
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), DB_NAME)
    conn = sqlite3.connect(db_path, timeout=20)
    cursor = conn.cursor()
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        print("日誌：SQLite WAL 模式已開啟")

        cursor.execute('CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT)')

        # 植入您的授權碼與預設設定
        settings = [
            ('tele_token', '8540551367:AAGXmoATXq3hranSkxUiEA6IPzMNvNrESog'),
            ('tele_chat_id', '6824247597'),
            ('cwa_api_key', 'CWA-728B43E3-05D6-4AA9-8A5E-69B52BCEDE77'),
            ('typhoon_mode', '0'),  # 0: 正常, 1: 颱風警戒模式
            ('forecast_location', '臺中市')
        ]
        cursor.executemany("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", settings)

        # 建立災害狀態紀錄表
        cursor.execute(
            'CREATE TABLE IF NOT EXISTS disaster_status (alert_type TEXT PRIMARY KEY, last_content TEXT, update_time TIMESTAMP)')

        conn.commit()
        print("日誌：資料庫設定值更新成功")
    except Exception as e:
        print(f"錯誤：{e}")
    finally:
        conn.close()


if __name__ == "__main__":
    upgrade_database()