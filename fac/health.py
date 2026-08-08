# -*- coding: utf-8 -*-
"""文件体检:重复文件、版本/副本族、垃圾文件、大文件、空文件夹。

针对"移动硬盘/下载目录攒了多年"的场景 —— 这些问题往往比"没分类"更占地方。
"""

import os
import hashlib

from .util import long_path
from .filetypes import junk_reason, strip_copy_markers, is_copy_like

_PARTIAL_BYTES = 64 * 1024      # 大文件先比前 64KB,不同就不必读全文
_PARTIAL_MIN = 1 << 20          # 超过 1MB 才走"先partial后全量"两段式


def _hash_file(path, limit=None):
    h = hashlib.sha1()
    remaining = limit
    with open(long_path(path), 'rb') as f:
        while True:
            n = 1 << 20 if remaining is None else min(1 << 20, remaining)
            if n <= 0:
                break
            b = f.read(n)
            if not b:
                break
            h.update(b)
            if remaining is not None:
                remaining -= len(b)
    return h.hexdigest()


def find_duplicates(files, log=None, cancel=None):
    """找出内容完全相同的文件组。

    files: [(path, size), …]
    返回 [[path, …], …],每组按"建议保留的排在第一个"排序。
    先按大小分组,只对可疑组做哈希;大文件再用前 64KB 预筛,避免全盘读取。
    """
    by_size = {}
    for path, size in files:
        if size > 0:
            by_size.setdefault(size, []).append(path)
    candidates = [(sz, paths) for sz, paths in by_size.items() if len(paths) > 1]
    if not candidates:
        return []

    groups = []
    for size, paths in candidates:
        if cancel is not None and cancel.is_set():
            break
        buckets = {}
        # 大文件先按前 64KB 分桶
        if size >= _PARTIAL_MIN:
            pre = {}
            for p in paths:
                try:
                    pre.setdefault(_hash_file(p, _PARTIAL_BYTES), []).append(p)
                except OSError:
                    continue
            sub_lists = [v for v in pre.values() if len(v) > 1]
        else:
            sub_lists = [paths]
        for sub in sub_lists:
            for p in sub:
                try:
                    buckets.setdefault(_hash_file(p), []).append(p)
                except OSError:
                    continue
        for _digest, same in buckets.items():
            if len(same) > 1:
                groups.append(_rank_keep_first(same))

    if log and groups:
        wasted = 0
        for g in groups:
            try:
                wasted += os.path.getsize(long_path(g[0])) * (len(g) - 1)
            except OSError:
                pass
        log(f'[体检] 发现 {len(groups)} 组重复文件,'
            f'重复占用约 {human_size(wasted)}')
    return groups


def _rank_keep_first(paths):
    """决定重复组里保留哪一个:名字不像副本的优先,其次改动时间早的(原件),
    再次路径短的(通常在更上层的正式目录)。"""
    def key(p):
        name = os.path.basename(p)
        try:
            mtime = os.path.getmtime(long_path(p))
        except OSError:
            mtime = float('inf')
        return (is_copy_like(name), mtime, len(p), p)
    return sorted(paths, key=key)


def find_version_families(files, log=None):
    """找出同一文件的多个版本/副本。

    files: [(path, size), …]
    返回 [(基名, [路径…]), …],每组按"最新的排第一"排序;
    只有明确带副本/版本标记(如 (1)、副本、v2、最终版)的文件才会成组,
    且要求同一目录 + 同一扩展名,避免误伤同名但不同内容的正式文件。
    """
    fams = {}
    for path, _size in files:
        d = os.path.dirname(path)
        fname = os.path.basename(path)
        stem, ext = os.path.splitext(fname)
        base, n = strip_copy_markers(stem)
        if not base:
            continue
        fams.setdefault((d, base, ext.lower()), []).append((path, n))

    out = []
    for (_d, base, _ext), items in fams.items():
        if len(items) < 2:
            continue
        # 组里必须至少有一个带副本标记的,否则只是碰巧同名前缀
        if not any(n > 0 for _p, n in items):
            continue
        paths = [p for p, _n in items]
        paths.sort(key=lambda p: (-_safe_mtime(p), len(p)))
        out.append((base, paths))

    if log and out:
        n_old = sum(len(g) - 1 for _b, g in out)
        log(f'[体检] 发现 {len(out)} 组版本/副本文件,较旧的共 {n_old} 个')
    return out


def _safe_mtime(p):
    try:
        return os.path.getmtime(long_path(p))
    except OSError:
        return 0.0


def find_junk(files, log=None):
    """找出垃圾/临时文件。files: [(path, size), …] → [(path, 原因), …]"""
    out = []
    for path, size in files:
        r = junk_reason(os.path.basename(path), size)
        if r:
            out.append((path, r))
    if log and out:
        total = 0
        for p, _r in out:
            try:
                total += os.path.getsize(long_path(p))
            except OSError:
                pass
        log(f'[体检] 发现 {len(out)} 个垃圾/临时文件,占用 {human_size(total)}')
    return out


def find_large(files, threshold, log=None):
    """找出超过阈值的大文件,按大小降序。"""
    out = sorted([(p, s) for p, s in files if s >= threshold],
                 key=lambda x: -x[1])
    if log and out:
        log(f'[体检] 发现 {len(out)} 个大文件(≥{human_size(threshold)})')
    return out


def find_empty_dirs(roots, log=None):
    """找出空文件夹(含只剩空子文件夹的),自底向上返回,可安全依次删除。"""
    empties, seen = [], set()
    for root in roots:
        if not os.path.isdir(root):
            continue
        for cur, dirs, files in os.walk(root, topdown=False):
            if os.path.abspath(cur) == os.path.abspath(root):
                continue
            if files:
                continue
            if all(os.path.join(cur, d) in seen for d in dirs):
                empties.append(cur)
                seen.add(cur)
    if log and empties:
        log(f'[体检] 发现 {len(empties)} 个空文件夹')
    return empties


def human_size(n) -> str:
    n = float(n or 0)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if n < 1024 or unit == 'TB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024
    return f'{n:.1f} TB'
