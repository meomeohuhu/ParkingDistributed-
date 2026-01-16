# init_local_db.py — Tạo database local cho Gate Node (phân tán)
import sqlite3
import os

DB = "gate_local.db"

# Tạo file DB nếu chưa có
if not os.path.exists(DB):
    print("Creating local SQLite DB...")

conn = sqlite3.connect(DB)
cur = conn.cursor()

# ======================================================
# 1) BẢNG SLOT LOCAL (dùng khi Cloud offline)
# ======================================================
cur.execute("""
CREATE TABLE IF NOT EXISTS local_slots (
    slotid TEXT PRIMARY KEY,
    zone TEXT,
    x INTEGER,
    y INTEGER,
    occupied INTEGER,
    plate TEXT,
    version INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# ======================================================
# 2) BẢNG OFFLINE QUEUE (Gate → Cloud sync)
# ======================================================
cur.execute("""
CREATE TABLE IF NOT EXISTS local_event_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT,
    payload TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# ======================================================
# 3) BẢNG XE LOCAL (optional - giữ nguyên logic cũ)
# ======================================================
cur.execute("""
CREATE TABLE IF NOT EXISTS local_vehicles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    plate TEXT,
    slotid TEXT,
    time_in TIMESTAMP,
    time_out TIMESTAMP,
    img_in TEXT,
    img_out TEXT
);
""")

conn.commit()
conn.close()

print("LOCAL DB INSTALLED OK")
