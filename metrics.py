"""Persist device traffic deltas from sing-box's open and recently closed flows."""
from contextlib import contextmanager
from datetime import datetime, timezone
import sqlite3
import threading
import time

import grpc

from usage_pb2 import Request, Snapshot
import wg_accounts


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript("""
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS audit(at REAL, action TEXT, username TEXT);
        CREATE TABLE IF NOT EXISTS attempts(at REAL);
        CREATE TABLE IF NOT EXISTS wg_flow(id TEXT PRIMARY KEY, up INTEGER, down INTEGER);
        CREATE TABLE IF NOT EXISTS wg_usage(tag TEXT PRIMARY KEY, up INTEGER, down INTEGER, seen REAL);
        CREATE TABLE IF NOT EXISTS wg_day(day TEXT, tag TEXT, up INTEGER, down INTEGER, PRIMARY KEY(day,tag));
        CREATE TABLE IF NOT EXISTS wg_sample(singleton INTEGER PRIMARY KEY, at REAL);
        """)


def record(db_path, snapshot, now):
    current = {}
    for event in snapshot.events:
        flow = event.connection
        if flow.inbound == 'wg' and flow.outbound.startswith('device-'):
            current[flow.id] = flow
    with connect(db_path) as db:
        db.execute('BEGIN IMMEDIATE')
        previous = {r['id']: r for r in db.execute('SELECT * FROM wg_flow')}
        for key, flow in current.items():
            old = previous.pop(key, None)
            up = max(0, flow.upload - (old['up'] if old else 0))
            down = max(0, flow.download - (old['down'] if old else 0))
            if up or down:
                observed = min(now, flow.closed_at / 1000) if flow.closed_at else now
                day = datetime.fromtimestamp(observed, timezone.utc).date().isoformat()
                db.execute("""INSERT INTO wg_usage VALUES (?,?,?,?) ON CONFLICT(tag)
                    DO UPDATE SET up=up+excluded.up, down=down+excluded.down, seen=max(seen,excluded.seen)""",
                    (flow.outbound, up, down, observed))
                db.execute("""INSERT INTO wg_day VALUES (?,?,?,?) ON CONFLICT(day,tag)
                    DO UPDATE SET up=up+excluded.up, down=down+excluded.down""", (day, flow.outbound, up, down))
            if up or down or old is None:
                db.execute('INSERT OR REPLACE INTO wg_flow VALUES (?,?,?)', (key, flow.upload, flow.download))
        db.executemany('DELETE FROM wg_flow WHERE id=?', [(key,) for key in previous])
        db.execute('INSERT OR REPLACE INTO wg_sample VALUES (1,?)', (now,))


_sample_lock = threading.Lock()


def sample(path):
    with _sample_lock:
        _sample(path)


def _sample(path):
    data = wg_accounts.read()
    with grpc.insecure_channel('127.0.0.1:18971') as channel:
        rpc = channel.unary_stream('/daemon.StartedService/SubscribeConnections',
                request_serializer=Request.SerializeToString, response_deserializer=Snapshot.FromString)
        stream = rpc(Request(interval=2_000_000_000), timeout=2,
                     metadata=(('authorization', 'Bearer ' + wg_accounts.stats_secret(data)),))
        try:
            snapshot = next(stream)
        finally:
            stream.cancel()
    record(path, snapshot, time.time())


def start(path):
    def collect():
        while True:
            try:
                sample(path)
            except (grpc.RpcError, OSError, ValueError, StopIteration, sqlite3.Error):
                pass  # The API exposes the age of the last successful sample.
            time.sleep(2)
    threading.Thread(target=collect, name='device-usage', daemon=True).start()


def summary(path, devices):
    with connect(path) as db:
        totals = {r['tag']:r for r in db.execute('SELECT * FROM wg_usage')}
        today = {r['tag']:r for r in db.execute("SELECT * FROM wg_day WHERE day=date('now')")}
        days = [dict(r) for r in db.execute("""SELECT day,sum(up) up,sum(down) down FROM wg_day
                      WHERE day>=date('now','-6 days') GROUP BY day ORDER BY day""")]
        stamp = db.execute('SELECT at FROM wg_sample').fetchone()
    rows = []
    for name, device in sorted(devices.items()):
        tag = wg_accounts.traffic_tag(device)
        row = totals.get(tag)
        daily = today.get(tag)
        rows.append(dict(name=name, up=row['up'] if row else 0, down=row['down'] if row else 0,
                         seen=row['seen'] if row else None, today=daily['up']+daily['down'] if daily else 0))
    return dict(rows=rows, days=days, sampled=stamp['at'] if stamp else None,
                up=sum(r['up'] for r in totals.values()), down=sum(r['down'] for r in totals.values()))
