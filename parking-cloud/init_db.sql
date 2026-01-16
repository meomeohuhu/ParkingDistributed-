CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Users (bảo vệ / admin)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password VARCHAR(100) NOT NULL,
    gateid VARCHAR(20),
    role VARCHAR(10) DEFAULT 'guard'  -- 'guard' hoặc 'admin'
);

-- Gates (cổng động)
CREATE TABLE IF NOT EXISTS gates (
    id SERIAL PRIMARY KEY,
    gateid VARCHAR(20) UNIQUE NOT NULL,
    ip_address VARCHAR(50),
    location VARCHAR(100),
    zone VARCHAR(1),             -- 'N', 'S', 'E', 'W'
    x INT DEFAULT 0,
    y INT DEFAULT 0,
    active BOOLEAN DEFAULT TRUE,
    waiting BOOLEAN DEFAULT FALSE,
    last_sync TIMESTAMP
);


-- Slots (chỗ đậu) — gắn với gate; ON DELETE CASCADE để xóa slot khi xóa gate
CREATE TABLE IF NOT EXISTS slots (
    id SERIAL PRIMARY KEY,
    slotid VARCHAR(20) UNIQUE NOT NULL,
    occupied BOOLEAN DEFAULT FALSE,
    plate VARCHAR(20),
    zone VARCHAR(1),
    x INT DEFAULT 0,
    y INT DEFAULT 0,
    version INT DEFAULT 0
);


-- Vehicles (lịch sử)
CREATE TABLE IF NOT EXISTS vehicles (
    id SERIAL PRIMARY KEY,
    event_id UUID DEFAULT uuid_generate_v4(),
    plate VARCHAR(20) NOT NULL,
    slotid VARCHAR(20),
    gateid VARCHAR(20),
    source_gate VARCHAR(20),
    time_in TIMESTAMP,
    time_out TIMESTAMP,
    synced BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);


-- Branches (nếu cần multi-site sau này)
CREATE TABLE IF NOT EXISTS branches (
    id SERIAL PRIMARY KEY,
    branch_code VARCHAR(10) UNIQUE,
    name VARCHAR(100),
    ip_address VARCHAR(50),
    api_url TEXT,
    token TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);


-- seed cơ bản
INSERT INTO users (username, password, gateid) VALUES
('bv1','123','G_N'),
('bv2','123','G_S'),
('bv3','123','G_E'),
('bv4','123','G_W')
ON CONFLICT (username) DO NOTHING;

INSERT INTO gates (gateid, location, zone, x, y) VALUES
('G_N', 'Cổng Bắc', 'N', 0, 10),
('G_S', 'Cổng Nam', 'S', 0, -10),
('G_E', 'Cổng Đông', 'E', 10, 0),
('G_W', 'Cổng Tây', 'W', -10, 0)
ON CONFLICT (gateid) DO NOTHING;

INSERT INTO slots (slotid, zone, x, y)
SELECT 'N' || LPAD(i::text, 2, '0'), 'N', (i-8), 7
FROM generate_series(1, 15) i;

INSERT INTO slots (slotid, zone, x, y)
SELECT 'S' || LPAD(i::text, 2, '0'), 'S', (i-8), -7
FROM generate_series(1, 15) i;

INSERT INTO slots (slotid, zone, x, y)
SELECT 'E' || LPAD(i::text, 2, '0'), 'E', 7, (i-8)
FROM generate_series(1, 15) i;

INSERT INTO slots (slotid, zone, x, y)
SELECT 'W' || LPAD(i::text, 2, '0'), 'W', -7, (i-8)
FROM generate_series(1, 15) i;

@app.get("/transactions")
def list_transactions():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT trans_id, plate, slotid, gateid,
               time_in, time_out, duration_minutes,
               fee, img_in, img_out
        FROM transactions
        ORDER BY time_in DESC
    """)
    rows = cur.fetchall()
    conn.close()
    return {"transactions": rows}

CREATE TABLE IF NOT EXISTS processed_events (
    event_id TEXT PRIMARY KEY,
    gateid VARCHAR(20),
    event_type VARCHAR(30),
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS payments (
    payment_id UUID PRIMARY KEY,
    plate VARCHAR(20) NOT NULL,
    gateid VARCHAR(20),
    amount INT NOT NULL,
    method VARCHAR(20) NOT NULL,  -- cash | online_manual
    status VARCHAR(20) NOT NULL,  -- PENDING | PAID | FAILED
    transfer_content TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    paid_at TIMESTAMP
);

-- gắn payment vào transactions (optional nhưng nên có)
ALTER TABLE transactions
ADD COLUMN IF NOT EXISTS payment_id UUID;
