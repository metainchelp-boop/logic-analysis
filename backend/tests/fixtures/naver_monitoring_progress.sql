-- Exact added table DDL from product 0a302856c6177c4f53145abaf9ed31b6a39654f3.
CREATE TABLE IF NOT EXISTS naver_auto_morning_progress (
        customer_id INTEGER PRIMARY KEY, possibility_id INTEGER NOT NULL, day TEXT NOT NULL,
        binding TEXT NOT NULL, campaign_fingerprint TEXT NOT NULL, generation INTEGER NOT NULL,
        status TEXT NOT NULL, next_try_at TEXT NOT NULL, payload_bytes INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS naver_auto_morning_chunk (
        customer_id INTEGER NOT NULL, kind TEXT NOT NULL, slot INTEGER NOT NULL,
        generation INTEGER NOT NULL, body TEXT, checksum TEXT, size INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (customer_id, kind, slot));
