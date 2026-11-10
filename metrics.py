"""Persistent, reset-aware accounting for Outline 1.9.2 Prometheus metrics."""
import json
from contextlib import contextmanager
import sqlite3
import time
import urllib.request
from prometheus_client.parser import text_string_to_metric_families


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=20)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS series (name TEXT PRIMARY KEY, epoch TEXT, value REAL);
        CREATE TABLE IF NOT EXISTS totals (key TEXT PRIMARY KEY, upload REAL DEFAULT 0,
          download REAL DEFAULT 0, seconds REAL DEFAULT 0, last_active REAL);
        CREATE TABLE IF NOT EXISTS daily (day TEXT, key TEXT, upload REAL DEFAULT 0,
          download REAL DEFAULT 0, PRIMARY KEY(day,key));
        CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS audit (at REAL, action TEXT, username TEXT);
        CREATE TABLE IF NOT EXISTS attempts (at REAL);
        CREATE TABLE IF NOT EXISTS email_jobs (request_id TEXT PRIMARY KEY,
          fingerprint TEXT, at REAL, status TEXT, message TEXT);
        ''')
        db.execute("INSERT OR IGNORE INTO metadata VALUES ('started', ?)", (str(time.time()),))


def record(path, text, now=None):
    now = time.time() if now is None else now
    samples = [s for f in text_string_to_metric_families(text) for s in f.samples]
    epoch = next((str(s.value) for s in samples if s.name == 'process_start_time_seconds'), None)
    if epoch is None:
        raise ValueError('Outline process_start_time_seconds metric is missing')
    selected = []
    for sample in samples:
        key = sample.labels.get('access_key')
        if not key:
            continue
        name = sample.name.removesuffix('_total')
        if name == 'shadowsocks_data_bytes':
            direction = sample.labels.get('dir')
            # Count only the client side; target-side counters would double-count.
            field = {'c>p': 'upload', 'c<p': 'download'}.get(direction)
            if not field:
                continue
        elif name == 'shadowsocks_tunnel_time_seconds':
            field = 'seconds'
        else:
            continue
        identity = json.dumps([sample.name, sorted(sample.labels.items())])
        selected.append((identity, key, field, sample.value))
    with connect(path) as db:
        initialized = db.execute("SELECT value FROM metadata WHERE key='last_ok'").fetchone()
        day = time.strftime('%Y-%m-%d', time.gmtime(now))
        for identity, key, field, value in selected:
            previous = db.execute('SELECT epoch,value FROM series WHERE name=?', (identity,)).fetchone()
            if previous:
                delta = value - previous['value'] if previous['epoch'] == epoch and value >= previous['value'] else value
            else:
                # Baseline the first scrape. New series after that are new traffic.
                delta = value if initialized else 0
            db.execute('INSERT OR REPLACE INTO series VALUES (?,?,?)', (identity, epoch, value))
            db.execute('INSERT OR IGNORE INTO totals(key) VALUES (?)', (key,))
            db.execute(f'UPDATE totals SET {field}={field}+? WHERE key=?', (delta, key))
            if delta > 0:
                db.execute('UPDATE totals SET last_active=? WHERE key=?', (now, key))
                if field in {'upload', 'download'}:
                    db.execute('INSERT OR IGNORE INTO daily(day,key) VALUES (?,?)', (day,key))
                    db.execute(f'UPDATE daily SET {field}={field}+? WHERE day=? AND key=?', (delta,day,key))
        db.execute("INSERT OR REPLACE INTO metadata VALUES ('last_ok',?)", (str(now),))
        db.execute("DELETE FROM metadata WHERE key='error'")


def scrape(path, url):
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            record(path, response.read(8_000_000).decode())
        return True
    except Exception:
        with connect(path) as db:
            db.execute("INSERT OR REPLACE INTO metadata VALUES ('error', 'Metrics unavailable')")
        return False
