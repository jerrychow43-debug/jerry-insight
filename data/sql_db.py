# Jerry-Insight-Pro/data/sql_db.py
import sqlite3

def save_audit_log(item, decision):
    conn = sqlite3.connect('./data/jerry_pro.db') # 存到 data 文件夹下
    cursor = conn.cursor()
    cursor.execute('CREATE TABLE IF NOT EXISTS history (item TEXT, dec TEXT)')
    cursor.execute('INSERT INTO history VALUES (?, ?)', (item, decision))
    conn.commit()
    conn.close()