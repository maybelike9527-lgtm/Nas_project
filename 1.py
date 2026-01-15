import sqlite3
import os
import requests
import json

DB_NAME = "account_book.db"


def check_available_models():
    print("🔍 正在查詢您的 API Key 可用的 Gemini 模型清單...\n")

    # 1. 取得 Key
    current_dir = os.path.dirname(os.path.abspath(__file__))
    db_path = os.path.join(current_dir, DB_NAME)

    if not os.path.exists(db_path):
        print("❌ 找不到資料庫")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM config WHERE key='gemini_api_key'")
        row = cursor.fetchone()
        if not row:
            print("❌ 資料庫沒 Key")
            return
        key = row[0]
    finally:
        conn.close()

    # 2. 查詢模型列表
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={key}"

    try:
        response = requests.get(url, timeout=10)

        if response.status_code == 200:
            data = response.json()
            print("✅ Google 回傳了以下可用模型：")
            print("=" * 40)

            # 過濾出 generateContent 支援的模型
            valid_models = []
            for m in data.get('models', []):
                if 'generateContent' in m['supportedGenerationMethods']:
                    print(f"🔹 {m['name']}")
                    valid_models.append(m['name'])

            print("=" * 40)

            # 自動推薦
            print("\n💡 建議修改：")
            if 'models/gemini-1.5-flash-001' in valid_models:
                print("請將程式碼中的 'gemini-1.5-flash' 改為 'gemini-1.5-flash-001'")
            elif 'models/gemini-pro' in valid_models:
                print("請將程式碼中的 'gemini-1.5-flash' 改為 'gemini-pro'")
            else:
                print("請從上面清單挑一個名字，填入 ds_manager.py 的第 30 行。")

        else:
            print(f"❌ 查詢失敗: {response.text}")

    except Exception as e:
        print(f"❌ 連線錯誤: {e}")


if __name__ == "__main__":
    check_available_models()