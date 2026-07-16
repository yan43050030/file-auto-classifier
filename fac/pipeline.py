# -*- coding: utf-8 -*-
"""主流程调度:收集压缩包 → 解压(嵌套/密码)→ 匹配人员 → (可选预览确认)
→ 归档(来源单位标注/去重/Excel 拆分)→ 反馈核对表 → 可选删除原包。

全程在后台线程运行,通过回调与界面交互;支持取消。
"""

import os
import shutil
import tempfile
import datetime
import traceback

from .util import unique_path, safe_folder_name, long_path, delete_to_trash, sha1_of
from .password import PasswordManager, load_password_candidates
from .idcard import find_ids
from .rules import Rule, match_rules
from .intelligent import detect_names, build_name_id_map, IntelligentMatcher
from . import extract as ex
from .report import write_matrix_report

_RULE_CN = {
    'ext': '扩展名', 'size_gt': '文件大于', 'size_lt': '文件小于',
    'date_before': '修改时间早于', 'date_after': '修改时间晚于',
    'contains': '包含文字', 'regex': '正则匹配',
}


class Cancelled(Exception):
    pass


class JobOptions:
    """一次分类任务的全部参数。"""

    def __init__(self, inputs, out_dir, roster,
                 copy_to_each=False, auto_id=True,
                 unit_mode='subfolder',          # subfolder | prefix | none
                 preview=False,
                 content_match=False, split_excel=False, dedup=False,
                 auto_pw_txt=True, pw_files=None, delete_ok=False,
                 rules=None, intelligent=True,
                 intelligent_min_freq=10, intelligent_exclude=None):
        self.inputs = list(inputs)
        self.out_dir = out_dir
        self.roster = roster
        self.copy_to_each = copy_to_each
        self.auto_id = auto_id
        self.unit_mode = unit_mode
        self.preview = preview
        self.content_match = content_match
        self.split_excel = split_excel
        self.dedup = dedup
        self.auto_pw_txt = auto_pw_txt
        self.pw_files = list(pw_files or [])
        self.delete_ok = delete_ok
        self.rules = list(rules or [])    # 高级分类规则列表
        self.intelligent = intelligent
        self.intelligent_min_freq = max(2, int(intelligent_min_freq or 10))
        self.intelligent_exclude = list(intelligent_exclude or [])


class PlanItem:
    __slots__ = ('src', 'fname', 'unit', 'action', 'targets', 'persons', 'via')

    def __init__(self, src, fname, unit, action, targets, persons=None, via=''):
        self.src = src            # 临时目录里的文件路径
        self.fname = fname        # 原始文件名
        self.unit = unit          # 来源单位(顶层压缩包名)
        self.action = action      # 'place' | 'split'
        self.targets = targets    # 目标文件夹名列表
        self.persons = persons or []
        self.via = via            # 命中方式: 文件名/内容/身份证号/未分类

    def display_target(self):
        if self.action == 'split':
            return '拆分 → ' + '、'.join(t for t in self.targets)
        return '、'.join(self.targets)


def _collect_inputs(inputs, auto_pw_txt, log):
    """收集压缩包、非压缩包文件、候选密码本 txt。
    返回 (archives, loose_files, txt_paths)。
    loose_files 是 (文件路径, 来源单位) 列表,归类时跟解压出来的文件一视同仁。"""
    archives, loose_files, txt_paths, txt_dirs = [], [], [], set()
    for p in inputs:
        if os.path.isdir(p):
            folder_name = os.path.basename(os.path.abspath(p))
            has_direct = False
            for root, _, files in os.walk(p):
                for f in files:
                    kind = ex.archive_kind(f)
                    if kind == 'volume-later':
                        continue
                    fp = os.path.join(root, f)
                    if kind:
                        archives.append(fp)
                    else:
                        # 非压缩包的直接文件也要分类(但排除 txt 密码本)
                        if auto_pw_txt and f.lower().endswith('.txt'):
                            txt_paths.append(fp)
                        else:
                            loose_files.append((fp, folder_name))
                            has_direct = True
        elif os.path.isfile(p) and ex.is_archive(os.path.basename(p)):
            if ex.archive_kind(os.path.basename(p)) == 'volume-later':
                log(f'  [提示] {os.path.basename(p)} 是分卷的后续卷,'
                    f'将由首卷自动带出,已跳过。')
                continue
            archives.append(p)
            if auto_pw_txt:
                txt_dirs.add(os.path.dirname(p))
        elif os.path.isfile(p):
            # 单独选中的非压缩包文件也直接分类
            unit = os.path.basename(os.path.dirname(p))
            loose_files.append((p, unit))
        else:
            log(f'  [提示] 跳过无法识别的输入: {p}')
    for d in txt_dirs:
        try:
            for f in os.listdir(d):
                if f.lower().endswith('.txt'):
                    txt_paths.append(os.path.join(d, f))
        except Exception:
            pass
    seen = set()
    archives = [x for x in archives if not (x in seen or seen.add(x))]
    seen = set()
    txt_paths = [x for x in txt_paths if not (x in seen or seen.add(x))]
    return archives, loose_files, txt_paths


def run_job(opts: JobOptions, log, progress, ask_password,
            confirm_cb=None, cancel_event=None, done_cb=None):
    """执行一次分类任务(应在后台线程调用)。

    log(msg)                       日志(pipeline 会同时写入日志文件)
    progress(phase, cur, total)    进度: phase = extract / classify / place
    ask_password(name, attempt)    请求密码,取消返回 None
    confirm_cb(plan_items) -> bool 预览确认(opts.preview 时调用)
    cancel_event                   threading.Event,置位即取消
    done_cb(summary)               完成回调
    """
    summary = {'stats': {}, 'matrix': {}, 'files': 0, 'failed': 0,
               'dedup_skipped': 0, 'cancelled': False, 'reports': []}
    stats, matrix = summary['stats'], summary['matrix']

    os.makedirs(opts.out_dir, exist_ok=True)
    log_path = os.path.join(
        opts.out_dir,
        f'分类日志_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt')
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

    seen_hashes = {}     # (folder, sha1) -> 已放入的文件名

    def place(src, fname, unit, folder, move):
        """把 src 放入 out/folder,按 unit_mode 标注来源。返回是否实际放入。"""
        base = os.path.join(opts.out_dir, folder)
        name = fname
        if unit:
            if opts.unit_mode == 'subfolder':
                base = os.path.join(base, safe_folder_name(unit))
            elif opts.unit_mode == 'prefix':
                name = f'【{unit}】{fname}'
        if opts.dedup:
            try:
                key = (folder, sha1_of(src))
                if key in seen_hashes:
                    summary['dedup_skipped'] += 1
                    tee(f'  [去重] {fname} 与 {seen_hashes[key]} 内容相同,跳过')
                    return False
                seen_hashes[key] = fname
            except Exception:
                pass
        os.makedirs(long_path(base), exist_ok=True)
        dst = unique_path(base, name)
        if move:
            shutil.move(long_path(src), long_path(dst))
        else:
            shutil.copy2(long_path(src), long_path(dst))
        matrix[(folder, unit or '')] = matrix.get((folder, unit or ''), 0) + 1
        stats[folder] = stats.get(folder, 0) + 1
        return True

    tmp = None
    try:
        # ---- 1. 收集输入(压缩包 + 非压缩包直接文件)与密码本 ----
        archives, loose_files, txt_paths = _collect_inputs(
            opts.inputs, opts.auto_pw_txt, tee)
        txt_paths = list(opts.pw_files) + \
            [t for t in txt_paths if t not in opts.pw_files]
        if not archives and not loose_files:
            tee('未找到任何压缩包或文件。请检查所选路径。')
            return
        if loose_files:
            tee(f'发现 {len(loose_files)} 个非压缩包文件,将直接分类(不经过解压)。')
        if not archives:
            tee('未找到压缩包,将仅对直接文件分类。')

        seeds = load_password_candidates(txt_paths, tee) if txt_paths else []
        if seeds:
            tee(f'已从 {len(txt_paths)} 个 txt 读取 {len(seeds)} 个候选密码,'
                f'遇到加密包将自动尝试。')
        pm = PasswordManager(ask_password, seeds=seeds)

        # ---- 2. 解压(临时目录放在输出盘,之后用"移动"归档,少写一遍盘) ----
        tmp = tempfile.mkdtemp(prefix='.分类tmp_', dir=opts.out_dir)
        failed_dir = os.path.join(opts.out_dir, '解压失败')
        skipped_pw_dir = os.path.join(opts.out_dir, '暂未解压')

        def stash(arc_path, folder):
            os.makedirs(folder, exist_ok=True)
            dst = unique_path(folder, os.path.basename(arc_path))
            try:
                shutil.copy2(long_path(arc_path), long_path(dst))
            except Exception as e:
                tee(f'  [提示] 复制失败包出错 {os.path.basename(arc_path)}: {e}')

        tee(f'共发现 {len(archives)} 个压缩包,开始解压(支持多级嵌套)...')
        success_archives = []
        extracted = []            # (解压目录, 来源单位)
        for i, arc in enumerate(archives, 1):
            ck()
            tee(f'[{i}/{len(archives)}] 解压: {os.path.basename(arc)}')
            progress('extract', i - 1, len(archives))
            sub = os.path.join(tmp, f'arc_{i}')
            os.makedirs(sub, exist_ok=True)
            failures = []
            skip_pws = []
            result = ex.extract_all_recursive(
                arc, sub, tee, pm, failures, skip_pws, cancel=cancel_event)
            ck()
            if result == 'ok' and not failures and not skip_pws:
                success_archives.append(arc)
            for fa in failures:
                stash(fa, failed_dir)
                summary['failed'] += 1
            for sp in skip_pws:
                stash(sp, skipped_pw_dir)
                summary['skipped_pw'] = summary.get('skipped_pw', 0) + 1
            if result == 'ok' or result == 'skip_pw':
                extracted.append((sub, ex.unit_name(arc)))
        progress('extract', len(archives), len(archives))

        # ---- 3. 匹配人员,生成归档计划 ----
        tee('解压完成,开始匹配人员...')
        all_files = []
        for sub, unit in extracted:
            for root, _, files in os.walk(sub):
                for f in files:
                    if ex.is_archive(f):
                        continue   # 只分类最终解压出的文件
                    all_files.append((os.path.join(root, f), f, unit))
        # 非压缩包的直接文件也加入分类
        for fp, unit in loose_files:
            all_files.append((fp, os.path.basename(fp), unit))

        # 内容匹配对"名单 + 智能识别 + 证号兜底"都有用,不再要求名单非空
        use_content = opts.content_match
        use_split = opts.split_excel
        if use_content or use_split:
            from .content_match import extract_text, HAS_XLSX
            if use_split and not HAS_XLSX:
                tee('  [提示] 未安装 openpyxl,Excel 拆分功能不可用,已忽略。')
                use_split = False

        rules = [r for r in (opts.rules or []) if r.enabled]
        if rules:
            tee(f'已启用 {len(rules)} 条高级分类规则。')

        # ---- 3.5 智能识别 ----
        imatch = None
        if opts.intelligent:
            detected = detect_names(all_files,
                                    min_freq=opts.intelligent_min_freq,
                                    exclude=opts.intelligent_exclude,
                                    log=tee)
            # 已知姓名 = 名单中的姓名/曾用名 + 智能发现的高频候选姓名
            known_names = set()
            for p in opts.roster.persons:
                known_names.add(p.name)
                for a in p.aliases:
                    known_names.add(a)
            for d in detected:
                known_names.add(d['name'])
            n2i, i2n = build_name_id_map(all_files, known_names, log=tee)
            detected_only = {d['name'] for d in detected}
            imatch = IntelligentMatcher(opts.roster, n2i, i2n, detected_only)

        plan = []
        for i, (fp, fname, unit) in enumerate(all_files, 1):
            ck()
            progress('classify', i, len(all_files))

            # 每个文件的内容文本只提取一次,各级匹配复用
            _text_cache = []

            def get_text():
                if not _text_cache:
                    _text_cache.append(extract_text(fp) if use_content else '')
                return _text_cache[0]

            persons = opts.roster.match(fname)
            via = '文件名'
            if not persons and use_content and len(opts.roster) > 0:
                text = get_text()
                if text:
                    persons = opts.roster.match(text)
                    via = '内容'
            if persons:
                is_xlsx = fname.lower().endswith(('.xlsx', '.xlsm'))
                if use_split and is_xlsx and len(persons) >= 2:
                    plan.append(PlanItem(fp, fname, unit, 'split',
                                         [p.folder for p in persons],
                                         persons, via))
                    continue
                if len(persons) > 1 and not opts.copy_to_each:
                    persons = persons[:1]
                plan.append(PlanItem(fp, fname, unit, 'place',
                                     [p.folder for p in persons],
                                     persons, via))
                continue
            # 智能识别:name↔ID 映射(先按文件名,再按内容兜底)
            if imatch is not None:
                m = imatch.match(fname)
                if m is None and use_content:
                    m = imatch.match_content(get_text())
                if m:
                    folder, sm_via = m
                    plan.append(PlanItem(fp, fname, unit, 'place',
                                         [folder], via=sm_via))
                    continue
            # 高级分类规则(名单/智能识别未命中 → 按文件类型/大小/时间/自定义字符/正则)
            if rules:
                r = match_rules(fp, rules)
                if r is not None:
                    plan.append(PlanItem(fp, fname, unit, 'place',
                                         [r.folder()], via=f'规则:{_RULE_CN.get(r.rule_type, r.rule_type)}'))
                    continue
            if opts.auto_id:
                ids = find_ids(fname)
                if ids:
                    plan.append(PlanItem(fp, fname, unit, 'place',
                                         [safe_folder_name(ids[0])],
                                         via='身份证号'))
                    continue
                # 文件名没有证号 → 内容里找(如"回执001.pdf"正文含证号)
                if use_content:
                    ids = find_ids(get_text())
                    if ids:
                        plan.append(PlanItem(fp, fname, unit, 'place',
                                             [safe_folder_name(ids[0])],
                                             via='内容证号'))
                        continue
            plan.append(PlanItem(fp, fname, unit, 'place', ['未分类'],
                                 via='未分类'))

        # ---- 4. 预览确认(试运行) ----
        if opts.preview and confirm_cb is not None:
            tee(f'已生成归档计划(共 {len(plan)} 个文件),等待确认...')
            if not confirm_cb(plan):
                tee('已取消:未执行任何归档,输出目录未改动。')
                summary['cancelled'] = True
                return

        # ---- 5. 执行归档 ----
        tee('开始归档文件...')
        for i, item in enumerate(plan, 1):
            ck()
            progress('place', i, len(plan))
            try:
                if item.action == 'split':
                    _do_split(item, opts, place, tee, tmp)
                else:
                    for j, t in enumerate(item.targets):
                        last = (j == len(item.targets) - 1)
                        place(item.src, item.fname, item.unit, t, move=last)
                summary['files'] += 1
            except Exception as e:
                tee(f'  [错误] 归档失败 {item.fname}: {e}')

        # ---- 6. 汇总 + 反馈核对表 ----
        tee(f'\n分类完成!共处理 {summary["files"]} 个文件。')
        if summary.get('skipped_pw'):
            tee(f'有 {summary["skipped_pw"]} 个加密压缩包因未提供密码,'
                f'已放入「暂未解压」文件夹(可稍后单独处理)。')
        if summary['failed']:
            tee(f'有 {summary["failed"]} 个压缩包解压失败,'
                f'已放入「解压失败」文件夹。')
        if summary['dedup_skipped']:
            tee(f'按内容去重跳过 {summary["dedup_skipped"]} 个重复文件。')
        tee('各文件夹文件数:')
        for k in sorted(stats):
            tee(f'  {k} : {stats[k]} 个')

        reports = write_matrix_report(opts.out_dir, matrix, tee)
        summary['reports'] = reports
        for r in reports:
            tee(f'已生成反馈核对表: {os.path.basename(r)}')

        # ---- 7. 可选:删除已成功解压的原始压缩包 ----
        if opts.delete_ok and success_archives:
            tee(f'\n开始删除 {len(success_archives)} 个已成功解压的压缩包...')
            for arc in success_archives:
                try:
                    way = delete_to_trash(arc)
                    tee(f'  已删除({way}): {os.path.basename(arc)}')
                except Exception as e:
                    tee(f'  [提示] 删除失败 {os.path.basename(arc)}: {e}')

    except Cancelled:
        summary['cancelled'] = True
        tee('\n已取消。已归档的文件保留在输出目录,未处理的部分未改动。')
    except Exception:
        tee('运行出错:\n' + traceback.format_exc())
    finally:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        if log_fp:
            try:
                log_fp.close()
            except Exception:
                pass
        if done_cb:
            done_cb(summary)


def _do_split(item: PlanItem, opts: JobOptions, place, tee, tmp):
    """执行 Excel 按人拆分;失败时退回按普通文件归档。"""
    from .excel_split import split_workbook
    split_dir = os.path.join(tmp, '_split')
    os.makedirs(split_dir, exist_ok=True)
    try:
        results, unmatched = split_workbook(item.src, opts.roster, split_dir)
    except Exception as e:
        tee(f'  [提示] 拆分失败,按整表归档 {item.fname}: {e}')
        targets = item.targets if opts.copy_to_each else item.targets[:1]
        for j, t in enumerate(targets):
            place(item.src, item.fname, item.unit, t, move=(j == len(targets) - 1))
        return
    if not results:
        place(item.src, item.fname, item.unit, '未分类', move=True)
        return
    for p, new_path in results.items():
        place(new_path, os.path.basename(new_path), item.unit, p.folder,
              move=True)
    if unmatched:
        tee(f'  [提示] {item.fname} 有 {unmatched} 行未匹配到人员,'
            f'请在「原始反馈」中的原表复核')
    # 原表保留一份备查
    place(item.src, item.fname, item.unit, '原始反馈', move=True)
    tee(f'  [拆分] {item.fname} → {len(results)} 人')
