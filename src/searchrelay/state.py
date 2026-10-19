"""SQLite leases are shared across processes. Counters are conservative local estimates."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import ProviderConfig


class State:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None, check_same_thread=False)
        os.chmod(path, 0o600)
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS usage (pool TEXT, window TEXT, used INTEGER NOT NULL,
            PRIMARY KEY(pool, window));
        CREATE TABLE IF NOT EXISTS health (pool TEXT PRIMARY KEY, until REAL NOT NULL, reason TEXT);
        CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, provider TEXT, expires REAL, value TEXT);
        CREATE TABLE IF NOT EXISTS events (at REAL, provider TEXT, outcome TEXT);
        ''')
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('salt', ?)", (secrets.token_hex(32),))
        self.salt = bytes.fromhex(self.db.execute("SELECT value FROM meta WHERE key='salt'").fetchone()[0])

    def close(self):
        self.db.close()

    def identity(self, provider: str, credential: str = "keyless-ip") -> str:
        digest = hmac.new(self.salt, credential.encode(), hashlib.sha256).hexdigest()
        return provider + ":" + digest

    def status(self, pool: str, now: float | None = None) -> dict:
        now = time.time() if now is None else now
        date = datetime.fromtimestamp(now, timezone.utc)
        counts = dict(self.db.execute("SELECT window, used FROM usage WHERE pool=?", (pool,)))
        health = self.db.execute("SELECT until, reason FROM health WHERE pool=?", (pool,)).fetchone()
        return {"daily_used": counts.get(date.strftime("%Y-%m-%d"), 0),
                "monthly_used": counts.get(date.strftime("%Y-%m"), 0),
                "retry_at": health[0] if health and health[0] > now else None,
                "reason": health[1] if health and health[0] > now else None}

    def reserve(self, pool: str, cfg: ProviderConfig, now: float | None = None) -> tuple[bool, str]:
        now = time.time() if now is None else now
        date = datetime.fromtimestamp(now, timezone.utc)
        self.db.execute("BEGIN IMMEDIATE")
        try:
            status = self.status(pool, now)
            reason = status["reason"] if status["retry_at"] else None
            if not reason and status["daily_used"] >= cfg.daily_limit:
                reason = "local_daily_cap"
            if not reason and status["monthly_used"] >= cfg.monthly_limit:
                reason = "local_monthly_cap"
            if reason:
                self.db.execute("COMMIT")
                return False, reason
            for window in (date.strftime("%Y-%m-%d"), date.strftime("%Y-%m")):
                self.db.execute("INSERT INTO usage VALUES (?, ?, 1) ON CONFLICT(pool, window) "
                                "DO UPDATE SET used=used+1", (pool, window))
            self.db.execute("INSERT OR REPLACE INTO health VALUES (?, ?, 'rate_spacing')",
                            (pool, now + cfg.min_interval_seconds))
            self.db.execute("COMMIT")
            return True, "reserved"
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def cooldown(self, pool: str, seconds: float, reason: str):
        self.db.execute("INSERT INTO health VALUES (?, ?, ?) ON CONFLICT(pool) DO UPDATE SET "
                        "until=max(until, excluded.until), reason=excluded.reason",
                        (pool, time.time() + max(0, seconds), reason))

    def cache_key(self, request: dict, config: dict, pools: list[str]) -> str:
        raw = json.dumps([request, config, pools], sort_keys=True).encode()
        return hmac.new(self.salt, raw, hashlib.sha256).hexdigest()

    def cached(self, key: str):
        row = self.db.execute("SELECT provider, value FROM cache WHERE key=? AND expires>?",
                              (key, time.time())).fetchone()
        return (row[0], json.loads(row[1])) if row else None

    def put_cache(self, key: str, provider: str, response: dict, ttl: int):
        self.db.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                        (key, provider, time.time() + ttl, json.dumps(response)))

    def event(self, provider: str, outcome: str):
        self.db.execute("INSERT INTO events VALUES (?, ?, ?)", (time.time(), provider, outcome))

    def prune(self, days: int):
        self.db.execute("DELETE FROM events WHERE at<?", (time.time() - days * 86400,))
        self.db.execute("DELETE FROM cache WHERE expires<=?", (time.time(),))
        # Keep only the current calendar month and today's quota windows; never reset current caps.
        date = datetime.now(timezone.utc)
        self.db.execute("DELETE FROM usage WHERE window NOT IN (?, ?)",
                        (date.strftime("%Y-%m"), date.strftime("%Y-%m-%d")))
