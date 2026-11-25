# -*- coding: utf-8 -*-
"""一键清理:把体检挑出来的「可清理 / 重复文件 / 旧版本」删到回收站。

安全边界:
- 只删**整理台账里记录过、由本工具放进这些文件夹**的文件 ——
  用户自己放进同名文件夹的东西、原地整理时碰巧叫「旧版本」的原有目录,一律不碰;
- 每删一个都补记进当初那次整理的台账(op=trash),
  之后撤销时会明确提示"该文件在回收站",而不是含糊地报"找不到"。
"""

import os

from .util import long_path, delete_to_trash
from .undo import Journal, read_journal, find_journals

BUCKETS = ('可清理', '重复文件', '旧版本')


def _bucket_of(path, out_abs, buckets):
    """path 位于 out_dir/某桶/ 之下则返回桶名,否则 None。"""
    try:
        rel = os.path.relpath(os.path.abspath(path), out_abs)
    except ValueError:            # Windows 下跨盘符
        return None
    if rel.startswith('..'):
        return None
    head = rel.split(os.sep, 1)[0]
    return head if head in buckets else None


def collect_candidates(out_dir, buckets, journal_paths=None):
    """按台账找出可清理的文件。

    journal_paths 为空时用输出目录下的全部整理台账。
    返回 [{'bucket','path','src','size','journal'}, …];
    已撤销/已清理/已被挪走的文件(磁盘上不存在)自动排除。"""
    out_abs = os.path.abspath(out_dir)
    buckets = set(buckets)
    if journal_paths is None:
        journal_paths = list(reversed(find_journals(out_dir)))   # 旧→新
    placed = {}                       # dst -> (src, journal)
    for jp in journal_paths:
        try:
            _meta, ops = read_journal(jp)
        except OSError:
            continue
        for rec in ops:
            op, dst = rec.get('op'), rec.get('dst')
            if op in ('move', 'copy') and dst:
                placed[dst] = (rec.get('src') or '', jp)
            elif op == 'trash':
                placed.pop(dst, None)
    out = []
    for dst, (src, jp) in placed.items():
        b = _bucket_of(dst, out_abs, buckets)
        if not b:
            continue
        try:
            size = os.path.getsize(long_path(dst))
        except OSError:
            continue                  # 已撤销/已手动处理
        out.append({'bucket': b, 'path': dst, 'src': src, 'size': size,
                    'journal': jp})
    out.sort(key=lambda c: (c['bucket'], c['path']))
    return out


def purge(out_dir, buckets, log, cancel=None, journal_paths=None,
          writers=None):
    """把候选文件删到回收站并补记台账。返回 (删除数, 腾出字节数)。

    writers: {台账路径: 已打开的 Journal},整理过程中直接复用正在写的台账。"""
    cands = collect_candidates(out_dir, buckets, journal_paths)
    writers = dict(writers or {})
    opened = []
    n, freed = 0, 0
    out_abs = os.path.abspath(out_dir)
    try:
        for c in cands:
            if cancel is not None and cancel.is_set():
                log('  清理已中断。')
                break
            try:
                way = delete_to_trash(c['path'])
            except Exception as e:
                log(f'  [提示] 删除失败 {os.path.basename(c["path"])}: {e}')
                continue
            n += 1
            freed += c['size']
            if n <= 20:
                log(f'  已删除({way}): {os.path.basename(c["path"])}')
            jw = writers.get(c['journal'])
            if jw is None:
                try:
                    jw = Journal(c['journal']).open_append()
                    writers[c['journal']] = jw
                    opened.append(jw)
                except OSError:
                    jw = None
            if jw is not None:
                jw.record('trash', c['src'], c['path'])
        if n > 20:
            log(f'  …共删除 {n} 个文件(仅列出前 20 个)')
    finally:
        for jw in opened:
            jw.close()
    # 删空的桶目录顺手移除(只删空的,用户自己的东西仍在就保留)
    for b in buckets:
        base = os.path.join(out_abs, b)
        if not os.path.isdir(base):
            continue
        for root, _dirs, _files in os.walk(base, topdown=False):
            try:
                os.rmdir(long_path(root))
            except OSError:
                pass
    return n, freed


def summarize(cands):
    """[(桶名, 个数, 字节数), …],按 BUCKETS 顺序。"""
    agg = {}
    for c in cands:
        n, s = agg.get(c['bucket'], (0, 0))
        agg[c['bucket']] = (n + 1, s + c['size'])
    return [(b, *agg[b]) for b in BUCKETS if b in agg]
