# -*- coding: utf-8 -*-
"""操作台账与撤销。

「文件整理」默认是"移动"(否则整理硬盘要双倍空间),移动是破坏性的,
所以每一步都记进台账文件,任何时候都能一键还原到整理前的状态。

台账为 JSON Lines:一行一条记录,边做边写边 flush ——
即使中途崩溃/断电,已完成的部分依然可以完整撤销。
"""

import os
import json
import shutil
import datetime

from .util import long_path, unique_path

JOURNAL_PREFIX = '整理台账_'
JOURNAL_EXT = '.jsonl'


class Journal:
    """整理操作台账(写入端)。"""

    def __init__(self, path):
        self.path = path
        self._fp = None
        self.count = 0

    def open(self, meta=None):
        os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
        self._fp = open(self.path, 'a', encoding='utf-8')
        self._write({'type': 'meta',
                     'time': datetime.datetime.now().isoformat(timespec='seconds'),
                     **(meta or {})})
        return self

    def open_append(self):
        """续写已有台账(不再写 meta,以免覆盖原整理时间)。
        用于事后「一键清理」把删到回收站的文件补记进当初那次整理的台账。"""
        self._fp = open(self.path, 'a', encoding='utf-8')
        return self

    def _write(self, rec):
        if not self._fp:
            return
        try:
            self._fp.write(json.dumps(rec, ensure_ascii=False) + '\n')
            self._fp.flush()
        except Exception:
            pass

    def record(self, op, src, dst):
        """op: move | copy | copy_tree | mkdir | rmdir | trash"""
        self._write({'type': 'op', 'op': op, 'src': src, 'dst': dst})
        self.count += 1

    def close(self):
        if self._fp:
            try:
                self._fp.close()
            except Exception:
                pass
            self._fp = None

    def __enter__(self):
        return self.open()

    def __exit__(self, *exc):
        self.close()
        return False


def default_journal_path(out_dir: str) -> str:
    stamp = f'{datetime.datetime.now():%Y%m%d_%H%M%S}'
    return os.path.join(out_dir, f'{JOURNAL_PREFIX}{stamp}{JOURNAL_EXT}')


def read_journal(path):
    """读取台账,返回 (meta, [操作记录…])。"""
    meta, ops = {}, []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get('type') == 'meta':
                meta.update({k: v for k, v in rec.items() if k != 'type'})
            elif rec.get('type') == 'op':
                ops.append(rec)
    return meta, ops


def undo(path, log=print, cancel=None):
    """按台账把文件还原回原位置。倒序执行,返回统计字典。

    - move: 把 dst 移回 src(src 已被占用时自动加序号,绝不覆盖;
            整个项目目录也走这条)
    - copy: 删除 dst(原件本就没动)
    - copy_tree: 删除复制出来的整个目录
    - rmdir: 重建被删掉的空文件夹
    - mkdir: 删掉整理时新建、撤销后已空的文件夹(不留一堆空的分类目录)
    - trash: 该文件已被「一键清理」删到回收站 —— 无法自动还原,
             列出原位置提示从回收站找回,不再算作"找不到"
    """
    meta, ops = read_journal(path)
    stats = {'restored': 0, 'removed': 0, 'missing': 0,
             'failed': 0, 'cancelled': False, 'trashed': 0,
             'dirs_removed': 0}
    trashed = set()
    log(f'读取台账: {os.path.basename(path)}(共 {len(ops)} 条操作)')
    if meta.get('time'):
        log(f'  整理时间: {meta["time"]}   模式: {meta.get("op_mode", "?")}')

    for rec in reversed(ops):
        if cancel is not None and cancel.is_set():
            stats['cancelled'] = True
            log('撤销已中断,已还原的部分保持不变。')
            break
        op, src, dst = rec.get('op'), rec.get('src'), rec.get('dst')
        try:
            if op == 'trash':
                trashed.add(dst)
                stats['trashed'] += 1
                if stats['trashed'] <= 20:
                    log(f'  [回收站] {os.path.basename(dst)} 已被清理到回收站,'
                        f'如需找回请从回收站还原(原位置: {src or dst})')
                continue
            if op in ('move', 'copy') and dst in trashed:
                continue          # 已在回收站,上面已提示,不算"找不到"
            if op == 'mkdir':
                try:
                    os.rmdir(long_path(src))      # 只删空的,有东西就留着
                    stats['dirs_removed'] += 1
                except OSError:
                    pass
                continue
            if op == 'move':
                if not os.path.exists(long_path(dst)):
                    stats['missing'] += 1
                    continue
                target = src
                if os.path.exists(long_path(target)):
                    target = unique_path(os.path.dirname(src),
                                         os.path.basename(src))
                os.makedirs(long_path(os.path.dirname(target)), exist_ok=True)
                shutil.move(long_path(dst), long_path(target))
                stats['restored'] += 1
            elif op == 'copy':
                if os.path.exists(long_path(dst)):
                    os.remove(long_path(dst))
                    stats['removed'] += 1
                else:
                    stats['missing'] += 1
            elif op == 'copy_tree':
                if os.path.isdir(long_path(dst)):
                    shutil.rmtree(long_path(dst), ignore_errors=True)
                    stats['removed'] += 1
                else:
                    stats['missing'] += 1
            elif op == 'rmdir':
                os.makedirs(long_path(src), exist_ok=True)
                stats['restored'] += 1
        except Exception as e:
            stats['failed'] += 1
            log(f'  [失败] 还原 {os.path.basename(dst or src or "")}: {e}')

    tail = (f'另有 {stats["trashed"]} 个已清理到回收站,需从回收站手动还原。'
            if stats['trashed'] else '')
    log(f'撤销完成:还原 {stats["restored"]} 个,删除副本 {stats["removed"]} 个,'
        f'找不到 {stats["missing"]} 个,失败 {stats["failed"]} 个;'
        f'清掉整理时新建的空文件夹 {stats["dirs_removed"]} 个。{tail}')
    return stats


def find_journals(out_dir: str):
    """列出目录下的台账文件,最新的在前。"""
    try:
        names = [n for n in os.listdir(out_dir)
                 if n.startswith(JOURNAL_PREFIX) and n.endswith(JOURNAL_EXT)]
    except OSError:
        return []
    return [os.path.join(out_dir, n) for n in sorted(names, reverse=True)]
