import sqlite3
import os

# Senin DB dosyan gerçekten nerede?
# Eğer backend klasörünün içinde app.db varsa:
DB_PATH = os.path.join(os.path.dirname(__file__), "app.db")

if not os.path.exists(DB_PATH):
    print("⚠️ Veritabanı dosyası bulunamadı:", DB_PATH)
    exit(1)

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

# 1. tablo şemasını göster
print("\n=== Accounts Table Schema ===")
cursor.execute("PRAGMA table_info(accounts)")
for col in cursor.fetchall():
    print(col)

# 2. İlk 5 satırı göster
print("\n=== First 5 Rows ===")
cursor.execute("SELECT * FROM accounts LIMIT 5")
rows = cursor.fetchall()
for row in rows:
    print(row)

conn.close()
