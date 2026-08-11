# -*- coding: utf-8 -*-
"""整理历史索引:把每次整理的"原路径 → 新路径"记进一个 SQLite 库,
以后可以按文件名搜索"这个文件当初在哪、被整理到哪去了"。

索引只是查询用的副本 —— 真正的撤销依据始终是台账文件,
所以索引损坏或删除都不影响撤销。
"""

import os
import sqlite3
import datetime

DB_NAME = '整理历史.db'


def db_path(out_dir: str) -> str:
    return os.path.join(out_dir, DB_NAME)


def _connect(path):
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS moves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_at TEXT NOT NULL,
        journal TEXT,
        fname TEXT NOT NULL,
        src TEXT NOT NULL,
        dst TEXT NOT NULL,
        size INTEGER,
        category TEXT,
        via TEXT)""")
    conn.execute('CREATE INDEX IF NOT EXISTS idx_fname ON moves(fname)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_run ON moves(run_at)')
    return conn


def record_run(out_dir: str, journal: str, rows, log=None):
    """把一次整理的记录写入索引。rows: [(fname, src, dst, size, category, via)]

    索引写失败不影响整理结果,只记一条提示。"""
    if not rows:
        return 0
    try:
        conn = _connect(db_path(out_dir))
        stamp = datetime.datetime.now().isoformat(timespec='seconds')
        with conn:
            conn.executemany(
                'INSERT INTO moves(run_at, journal, fname, src, dst, size,'
                ' category, via) VALUES (?,?,?,?,?,?,?,?)',
                [(stamp, os.path.basename(journal or ''), *r) for r in rows])
        conn.close()
        return len(rows)
    except Exception as e:
        if log:
            log(f'  [提示] 写入整理历史失败(不影响整理结果): {e}')
        return 0


def search(out_dir: str, keyword: str, limit: int = 200):
    """按文件名/路径模糊搜索历次整理记录,最新的在前。"""
    path = db_path(out_dir)
    if not os.path.isfile(path) or not keyword.strip():
        return []
    like = f'%{keyword.strip()}%'
    try:
        conn = sqlite3.connect(path)
        cur = conn.execute(
            'SELECT run_at, fname, src, dst, category FROM moves'
            ' WHERE fname LIKE ? OR src LIKE ? OR dst LIKE ?'
            ' ORDER BY id DESC LIMIT ?', (like, like, like, limit))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def list_runs(out_dir: str, limit: int = 50):
    """列出历次整理:时间、台账名、文件数。"""
    path = db_path(out_dir)
    if not os.path.isfile(path):
        return []
    try:
        conn = sqlite3.connect(path)
        cur = conn.execute(
            'SELECT run_at, journal, COUNT(*) FROM moves'
            ' GROUP BY run_at, journal ORDER BY run_at DESC LIMIT ?', (limit,))
        rows = cur.fetchall()
        conn.close()
        return rows
    except Exception:
        return []
