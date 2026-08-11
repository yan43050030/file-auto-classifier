# -*- coding: utf-8 -*-
"""「文件整理」模式:把下载目录/移动硬盘里积攒的杂乱文件按类型+时间整理好,
同时做一次文件体检(重复、旧版本、垃圾、大文件、空文件夹)。

与「按人归档」共用同一套回调契约(log / progress / confirm_cb / cancel_event /
done_cb),因此界面的预览、手动改分、进度、取消、日志全部原样复用。

默认是"移动"(整理硬盘用复制要双倍空间),每一步都写进撤销台账,可一键还原。
"""

import os
import shutil
import datetime
import traceback

from .util import long_path, unique_path, safe_rel_path
from .filetypes import categorize, detect_source, ext_of
from .filedate import best_date
from .rules import match_rules
from . import health
from .undo import Journal, default_journal_path
from .report import write_organize_report

# 体检专用文件夹(优先级高于常规布局)
BUCKET_JUNK = '可清理'
BUCKET_DUP = '重复文件'
BUCKET_OLD = '旧版本'
BUCKET_LARGE = '大文件'

LAYOUT_PRESETS = [
    ('{类别}', '只按类型(文档/图片/视频…)'),
    ('{类别}/{年}', '类型 → 年份(推荐:找特定类型的东西)'),
    ('{年}/{类别}', '年份 → 类型(推荐:回忆某年做过什么)'),
    ('{类别}/{年月}', '类型 → 年月(文件特别多时)'),
    ('{来源}/{类别}', '来源(微信/截图/相机…) → 类型'),
]


class Cancelled(Exception):
    pass


class OrganizeOptions:
    """一次文件整理任务的全部参数。"""

    def __init__(self, inputs, out_dir,
                 layout='{类别}/{年}',
                 op_mode='move',                # move | copy
                 preview=True,
                 rules=None,
                 find_dup=True, find_versions=True, find_junk=True,
                 separate_large=False, large_threshold=100 * 1024 * 1024,
                 clean_empty_dirs=True,
                 skip_hidden=True,
                 date_source='auto'):      # auto=拍摄/文件名日期优先 | mtime
        self.inputs = list(inputs)
        self.out_dir = out_dir
        self.layout = layout or '{类别}/{年}'
        self.op_mode = 'copy' if op_mode == 'copy' else 'move'
        self.preview = preview
        self.rules = list(rules or [])
        self.find_dup = find_dup
        self.find_versions = find_versions
        self.find_junk = find_junk
        self.separate_large = separate_large
        self.large_threshold = int(large_threshold or 0)
        self.clean_empty_dirs = clean_empty_dirs
        self.skip_hidden = skip_hidden
        self.date_source = date_source if date_source in ('auto', 'mtime') \
            else 'auto'


class OrganizeItem:
    """一个文件的整理计划。字段与「按人归档」的 PlanItem 对齐,
    以便复用界面的预览表格与手动改分。"""

    __slots__ = ('src', 'fname', 'unit', 'action', 'targets', 'via', 'size',
                 'date')

    def __init__(self, src, fname, unit, targets, via, size=0, date=0.0):
        self.src = src
        self.fname = fname
        self.unit = unit          # 来源:原目录名(或识别出的微信/截图等)
        self.action = 'place'
        self.targets = targets    # 相对目标路径列表,如 ['文档/2023']
        self.via = via            # 分类依据
        self.size = size
        self.date = date          # 判定出的文件日期(时间戳)

    def display_target(self):
        return '、'.join(self.targets)


# ---------- 布局模板 ----------

def render_layout(layout: str, fname: str, mtime: float, source=None) -> str:
    """把模板渲染成相对路径,如 '文档/2023'。"""
    try:
        dt = datetime.datetime.fromtimestamp(mtime)
    except (OSError, OverflowError, ValueError):
        dt = datetime.datetime.now()
    ext = ext_of(fname)
    values = {
        '{类别}': categorize(fname),
        '{年}': f'{dt.year}',
        '{年月}': f'{dt.year}-{dt.month:02d}',
        '{来源}': source or '其他来源',
        '{扩展名}': ext.upper() if ext else '无扩展名',
    }
    out = layout
    for k, v in values.items():
        out = out.replace(k, v)
    return safe_rel_path(out)


# ---------- 收集文件 ----------

def collect_files(inputs, out_dir, skip_hidden=True, log=None):
    """遍历输入目录收集文件。返回 [(path, size, mtime), …]。

    整理结果目录本身会被跳过(除非它就是输入目录 —— 即"原地整理")。"""
    out_abs = os.path.abspath(out_dir)
    in_roots = {os.path.abspath(p) for p in inputs}
    in_place = out_abs in in_roots        # 原地整理:不能把输出目录整个跳过
    files, seen = [], set()

    def _hidden(name):
        return skip_hidden and (name.startswith('.') or name.startswith('~$'))

    for p in inputs:
        p_abs = os.path.abspath(p)
        if os.path.isfile(p_abs):
            _add(files, seen, p_abs)
            continue
        if not os.path.isdir(p_abs):
            if log:
                log(f'  [提示] 跳过无法识别的输入: {p}')
            continue
        for root, dirs, names in os.walk(p_abs):
            root_abs = os.path.abspath(root)
            if not in_place and (root_abs == out_abs or
                                 root_abs.startswith(out_abs + os.sep)):
                dirs[:] = []
                continue
            if skip_hidden:
                dirs[:] = [d for d in dirs if not d.startswith('.')]
            for n in names:
                if _hidden(n) and not n.startswith('~$'):
                    continue      # 隐藏文件跳过;~$ 临时文件留给体检环节处理
                _add(files, seen, os.path.join(root_abs, n))
    return files


def _add(files, seen, path):
    if path in seen:
        return
    # 工具自己产生的台账/报告/日志不参与整理
    base = os.path.basename(path)
    if base.startswith(('整理台账_', '整理报告', '分类日志_', '反馈核对表')):
        return
    try:
        st = os.stat(long_path(path))
    except OSError:
        return
    seen.add(path)
    files.append((path, st.st_size, st.st_mtime))


# ---------- 生成整理计划 ----------

def build_plan(files, opts, log=None, cancel=None, progress=None):
    """体检 + 分类,生成整理计划。返回 (plan, health_stats)。"""
    hs = {'dup_groups': 0, 'dup_extra': 0, 'dup_bytes': 0,
          'junk': 0, 'junk_bytes': 0, 'old_versions': 0,
          'large': 0, 'total_bytes': sum(s for _p, s, _m in files)}

    size_pairs = [(p, s) for p, s, _m in files]
    special = {}      # path -> (bucket相对路径, via)

    if opts.find_junk:
        for p, reason in health.find_junk(size_pairs, log=log):
            special[p] = (os.path.join(BUCKET_JUNK, reason), f'体检:{reason}')
            hs['junk'] += 1
        hs['junk_bytes'] = sum(s for p, s in size_pairs if p in special)

    if opts.find_dup:
        if progress:
            progress('health', 1, 3)
        groups = health.find_duplicates(size_pairs, log=log, cancel=cancel)
        hs['dup_groups'] = len(groups)
        for g in groups:
            keep = g[0]
            try:
                per = os.path.getsize(long_path(keep))
            except OSError:
                per = 0
            for dup in g[1:]:
                if dup in special:
                    continue
                special[dup] = (BUCKET_DUP,
                                f'体检:与「{os.path.basename(keep)}」重复')
                hs['dup_extra'] += 1
                hs['dup_bytes'] += per

    if opts.find_versions:
        if progress:
            progress('health', 2, 3)
        for _base, paths in health.find_version_families(size_pairs, log=log):
            # 已被判为重复/垃圾的成员先剔除:否则"正本"会因为副本的时间更新
            # 而被误判成旧版本,导致整个版本族都离开了正常分类目录
            rest = [p for p in paths if p not in special]
            if len(rest) < 2:
                continue
            newest = rest[0]
            for old in rest[1:]:
                special[old] = (BUCKET_OLD,
                                f'体检:旧版本(最新为「{os.path.basename(newest)}」)')
                hs['old_versions'] += 1

    if progress:
        progress('health', 3, 3)

    plan = []
    date_stats = {}
    for i, (path, size, mtime) in enumerate(files, 1):
        if cancel is not None and cancel.is_set():
            raise Cancelled
        if progress and i % 50 == 0:
            progress('classify', i, len(files))
        fname = os.path.basename(path)
        source = detect_source(fname)
        unit = source or os.path.basename(os.path.dirname(path)) or '根目录'
        # 真实日期:拍摄时间 → 文件名里的日期 → 修改时间
        fdate, dsrc = best_date(path, fname, mtime, opts.date_source)
        date_stats[dsrc] = date_stats.get(dsrc, 0) + 1

        sp = special.get(path)
        if sp:
            plan.append(OrganizeItem(path, fname, unit, [sp[0]], sp[1],
                                     size, fdate))
            continue

        if opts.separate_large and opts.large_threshold and \
                size >= opts.large_threshold:
            plan.append(OrganizeItem(
                path, fname, unit, [BUCKET_LARGE],
                f'体检:大文件({health.human_size(size)})', size, fdate))
            hs['large'] += 1
            continue

        if opts.rules:
            r = match_rules(path, opts.rules)
            if r is not None:
                plan.append(OrganizeItem(path, fname, unit, [r.folder()],
                                         f'规则:{r.value}', size, fdate))
                continue

        rel = render_layout(opts.layout, fname, fdate, source)
        plan.append(OrganizeItem(path, fname, unit, [rel],
                                 f'类型:{categorize(fname)}', size, fdate))
    if progress:
        progress('classify', len(files), len(files))

    if log and date_stats:
        parts = [f'{k} {v} 个' for k, v in sorted(date_stats.items(),
                                                  key=lambda x: -x[1])]
        log('[日期] 归类依据: ' + '、'.join(parts))

    if opts.separate_large and not opts.find_dup:
        hs['large'] = sum(1 for it in plan if it.targets == [BUCKET_LARGE])
    return plan, hs


# ---------- 执行 ----------

def run_organize(opts: OrganizeOptions, log, progress,
                 confirm_cb=None, cancel_event=None, done_cb=None):
    """执行一次文件整理(应在后台线程调用)。"""
    summary = {'files': 0, 'moved': 0, 'copied': 0, 'failed': 0,
               'cancelled': False, 'reports': [], 'journal': '',
               'stats': {}, 'health': {}, 'empty_dirs': 0}
    os.makedirs(opts.out_dir, exist_ok=True)
    log_path = os.path.join(
        opts.out_dir, f'分类日志_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt')
    log_fp = None
    try:
        log_fp = open(log_path, 'a', encoding='utf-8')
    except Exception:
        pass

    def tee(msg):
        if log_fp:
            try:
                log_fp.write(msg + '\n')
                log_fp.flush()
            except Exception:
                pass
        log(msg)

    def ck():
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled

    journal = None
    try:
        # ---- 1. 扫描 ----
        tee('开始扫描文件...')
        progress('scan', 0, 1)
        files = collect_files(opts.inputs, opts.out_dir,
                              skip_hidden=opts.skip_hidden, log=tee)
        progress('scan', 1, 1)
        if not files:
            tee('未找到任何文件。请检查所选路径。')
            return
        tee(f'共发现 {len(files)} 个文件,'
            f'合计 {health.human_size(sum(s for _p, s, _m in files))}。')
        ck()

        # ---- 2. 体检 + 生成计划 ----
        tee('开始文件体检与分类...')
        plan, hs = build_plan(files, opts, log=tee, cancel=cancel_event,
                              progress=progress)
        summary['health'] = hs
        ck()

        # ---- 3. 预览确认(可手动改分) ----
        if opts.preview and confirm_cb is not None:
            tee(f'已生成整理计划(共 {len(plan)} 个文件),等待确认...')
            if not confirm_cb(plan):
                tee('已取消:未移动任何文件,原目录未改动。')
                summary['cancelled'] = True
                return

        # ---- 4. 执行(边做边写撤销台账) ----
        move = (opts.op_mode == 'move')
        tee(f'开始整理({"移动" if move else "复制"}),'
            f'全过程记入台账,可随时撤销...')
        journal = Journal(default_journal_path(opts.out_dir)).open(
            {'op_mode': opts.op_mode, 'out_dir': os.path.abspath(opts.out_dir),
             'inputs': [os.path.abspath(p) for p in opts.inputs],
             'layout': opts.layout})
        summary['journal'] = journal.path
        stats = summary['stats']

        for i, item in enumerate(plan, 1):
            ck()
            progress('place', i, len(plan))
            rel = safe_rel_path(item.targets[0]) if item.targets else '未分类'
            folder = os.path.join(opts.out_dir, rel)
            try:
                os.makedirs(long_path(folder), exist_ok=True)
                # 先判断是否已在目标位置:否则 unique_path 会因为"目标名被
                # 文件自己占着"而加序号,重复整理同一目录时不断产生 (1)(2)
                if os.path.abspath(item.src) == \
                        os.path.abspath(os.path.join(folder, item.fname)):
                    stats[rel] = stats.get(rel, 0) + 1
                    summary['files'] += 1
                    continue          # 已经在正确位置,无需搬动
                dst = unique_path(folder, item.fname)
                if move:
                    shutil.move(long_path(item.src), long_path(dst))
                    journal.record('move', item.src, dst)
                    summary['moved'] += 1
                else:
                    shutil.copy2(long_path(item.src), long_path(dst))
                    journal.record('copy', item.src, dst)
                    summary['copied'] += 1
                stats[rel] = stats.get(rel, 0) + 1
                summary['files'] += 1
            except Exception as e:
                summary['failed'] += 1
                tee(f'  [错误] 整理失败 {item.fname}: {e}')

        # ---- 5. 清理空文件夹 ----
        if opts.clean_empty_dirs and move:
            roots = [p for p in opts.inputs if os.path.isdir(p)]
            empties = health.find_empty_dirs(roots, log=tee)
            for d in empties:
                try:
                    os.rmdir(long_path(d))
                    journal.record('rmdir', d, '')
                    summary['empty_dirs'] += 1
                except OSError:
                    pass
            if summary['empty_dirs']:
                tee(f'已清理 {summary["empty_dirs"]} 个空文件夹。')

        # ---- 6. 汇总 + 整理报告 ----
        tee(f'\n整理完成!共处理 {summary["files"]} 个文件'
            f'({"移动" if move else "复制"} {summary["moved"] or summary["copied"]} 个)。')
        if hs['dup_extra']:
            tee(f'重复文件 {hs["dup_extra"]} 个已归入「{BUCKET_DUP}」,'
                f'确认后删除可省出 {health.human_size(hs["dup_bytes"])}。')
        if hs['junk']:
            tee(f'垃圾/临时文件 {hs["junk"]} 个已归入「{BUCKET_JUNK}」,'
                f'占用 {health.human_size(hs["junk_bytes"])}。')
        if hs['old_versions']:
            tee(f'旧版本文件 {hs["old_versions"]} 个已归入「{BUCKET_OLD}」。')
        if summary['failed']:
            tee(f'有 {summary["failed"]} 个文件整理失败(见上方日志)。')
        tee('各目标文件夹文件数:')
        for k in sorted(stats):
            tee(f'  {k} : {stats[k]} 个')

        reports = write_organize_report(opts.out_dir, plan, hs, tee)
        summary['reports'] = reports
        for r in reports:
            tee(f'已生成整理报告: {os.path.basename(r)}')
        tee(f'撤销台账: {os.path.basename(journal.path)}'
            f'(如需还原,在界面点「撤销上次整理」或用 --undo 指定该文件)')

    except Cancelled:
        summary['cancelled'] = True
        tee('\n已取消。已整理的文件保留在结果目录,'
            '如需全部还原请使用撤销台账。')
    except Exception:
        tee('运行出错:\n' + traceback.format_exc())
    finally:
        if journal:
            journal.close()
        if log_fp:
            try:
                log_fp.close()
            except Exception:
                pass
        if done_cb:
            done_cb(summary)
