import psycopg2

conn = psycopg2.connect(
    dbname="parking",
    user="admin",
    password="admin",
    host="localhost",
    port=5432
)
cur = conn.cursor()

# GRID chuẩn
GRID_W = 10
GRID_H = 6

# Lấy danh sách slot theo thứ tự tên tăng dần
cur.execute("SELECT slotid FROM slots ORDER BY slotid")
slots = [r[0] for r in cur.fetchall()]

print("Found", len(slots), "slots")

for idx, slotid in enumerate(slots):
    x = idx % GRID_W
    y = idx // GRID_W

    cur.execute(
        "UPDATE slots SET x=%s, y=%s WHERE slotid=%s",
        (x, y, slotid)
    )

conn.commit()
conn.close()

print("✔ ALL SLOTS NOW FORM A PERFECT 10×6 SQUARE GRID!")
