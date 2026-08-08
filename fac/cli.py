# -*- coding: utf-8 -*-
"""命令行模式:无界面批处理,可配合 Windows 计划任务自动处理固定收件目录。

示例(按人归档):
    python 文件自动分类工具.py -i 收件目录 -o 结果目录 --roster 名单.xlsx
    python 文件自动分类工具.py -i a.zip b.rar -o out --kw 张三 --kw 李四,110101199001011234

示例(文件整理):
    python 文件自动分类工具.py --mode organize -i D:\\下载 -o D:\\整理结果
    python 文件自动分类工具.py --mode organize -i E:\\ -o E:\\整理 --layout "{年}/{类别}"
    python 文件自动分类工具.py --undo "D:\\整理结果\\整理台账_20240115_103000.jsonl"
"""

import argparse
import os
import sys
import threading

from . import VERSION, APP_NAME
from .roster import Roster
from .pipeline import JobOptions, run_job
from .organize import OrganizeOptions, run_organize, LAYOUT_PRESETS
from .rules import Rule
from .util import read_text_any_encoding


def build_parser():
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f'{APP_NAME} {VERSION} 命令行模式:'
                    f'解压压缩包并按人员归档。不带参数运行则打开图形界面。')
    p.add_argument('--mode', choices=['person', 'organize'], default='person',
                   help='person=按人归档(默认);organize=文件整理'
                        '(下载目录/移动硬盘按类型+时间整理)')
    p.add_argument('-i', '--input', nargs='+', metavar='路径',
                   help='压缩包/文件夹/文件(可多个)')
    p.add_argument('-o', '--out', metavar='目录', help='结果输出目录')
    p.add_argument('--undo', metavar='台账', dest='undo_journal',
                   help='撤销一次文件整理:传入结果目录里的「整理台账_*.jsonl」,'
                        '把文件全部还原回原位置')
    p.add_argument('--roster', metavar='文件',
                   help='人员名单文件(txt 每行一人,或 Excel)')
    p.add_argument('--kw', action='append', default=[], metavar='关键字',
                   help='追加一个人员/关键字(格式同名单行:姓名[,证号][,曾用名]),可重复')
    p.add_argument('--each', action='store_true',
                   help='命中多个关键字时复制到每个文件夹(默认只归第一个)')
    p.add_argument('--no-auto-id', action='store_true',
                   help='关闭"按文件名中的身份证号自动分类"')
    p.add_argument('--unit-mode', choices=['subfolder', 'prefix', 'none'],
                   default='subfolder',
                   help='来源单位标注方式:subfolder=人员文件夹下按单位建子文件夹(默认),'
                        'prefix=文件名加【单位】前缀,none=不标注')
    p.add_argument('--content-match', action='store_true',
                   help='文件名未命中时读取 Excel/Word/PDF/文本内容匹配')
    p.add_argument('--split-excel', action='store_true',
                   help='一个 Excel 含多人数据时按行拆分,每人一份')
    p.add_argument('--dedup', action='store_true',
                   help='同一人员文件夹内按内容去重(跨单位重复反馈只留一份)')
    p.add_argument('--pw-file', action='append', default=[], metavar='txt',
                   help='密码本 txt(可重复)')
    p.add_argument('--no-auto-pw-txt', action='store_true',
                   help='不自动把输入文件夹里的 txt 当密码本')
    p.add_argument('--delete-ok', action='store_true',
                   help='完成后删除已成功解压的原始压缩包(移入回收站)')
    p.add_argument('--no-smart', action='store_true',
                   help='关闭智能识别(自动发现高频人名 + 姓名↔证号推测)')
    p.add_argument('--smart-min-freq', type=int, default=10, metavar='N',
                   help='智能识别阈值:同一姓名至少出现在 N 个文件中(默认 10)')
    p.add_argument('--smart-exclude', action='append', default=[], metavar='词',
                   help='智能识别额外排除词(可重复;常见机构/地名/职务已内置排除)')
    g = p.add_argument_group('文件整理模式(--mode organize)')
    g.add_argument('--layout', default='{类别}/{年}', metavar='模板',
                   help='目录布局模板,可用 {类别}{年}{年月}{来源}{扩展名};'
                        '默认 "{类别}/{年}"')
    g.add_argument('--list-layouts', action='store_true',
                   help='列出内置布局模板后退出')
    g.add_argument('--copy', action='store_true',
                   help='复制而非移动(默认移动;整理硬盘用复制需双倍空间)')
    g.add_argument('--no-dup', action='store_true', help='不查重复文件')
    g.add_argument('--no-versions', action='store_true', help='不查旧版本/副本')
    g.add_argument('--no-junk', action='store_true', help='不查垃圾/临时文件')
    g.add_argument('--separate-large', action='store_true',
                   help='把大文件单独归入「大文件」文件夹')
    g.add_argument('--large-mb', type=int, default=100, metavar='MB',
                   help='大文件阈值(MB),默认 100')
    g.add_argument('--keep-empty-dirs', action='store_true',
                   help='整理后不清理空文件夹')
    g.add_argument('--rule', action='append', default=[], metavar='类型:值:目标',
                   help='自定义规则,如 contains:发票:财务票据 或 ext:psd:设计稿;'
                        '可重复,优先级高于类型布局')
    p.add_argument('-V', '--version', action='version',
                   version=f'{APP_NAME} {VERSION}')
    return p


def _load_roster(args):
    persons = []
    if args.roster:
        path = args.roster
        if not os.path.isfile(path):
            print(f'错误:名单文件不存在: {path}', file=sys.stderr)
            sys.exit(2)
        if path.lower().endswith(('.xlsx', '.xlsm')):
            persons.extend(Roster.from_excel(path).persons)
        else:
            text = read_text_any_encoding(path) or ''
            persons.extend(Roster.from_text(text).persons)
    if args.kw:
        persons.extend(Roster.from_text('\n'.join(args.kw)).persons)
    return Roster(persons)


def _ask_password_tty(name, attempt):
    if not sys.stdin.isatty():
        return None      # 非交互环境:跳过加密包(会进"解压失败")
    import getpass
    tip = '密码错误,请重新输入' if attempt > 1 else '需要解压密码'
    try:
        pwd = getpass.getpass(f'{tip} [{name}](直接回车跳过): ')
    except (EOFError, KeyboardInterrupt):
        return None
    return pwd or None


def _parse_rules(specs):
    """解析 --rule 类型:值:目标"""
    rules = []
    for spec in specs:
        parts = spec.split(':', 2)
        if len(parts) != 3 or not all(x.strip() for x in parts):
            print(f'错误:规则格式应为 类型:值:目标,收到 {spec!r}', file=sys.stderr)
            sys.exit(2)
        rules.append(Rule(parts[0].strip(), parts[1].strip(), parts[2].strip()))
    return rules


def _run_organize(args):
    opts = OrganizeOptions(
        inputs=args.input, out_dir=args.out,
        layout=args.layout,
        op_mode='copy' if args.copy else 'move',
        preview=False,                       # 命令行是无人值守场景,不弹预览
        rules=_parse_rules(args.rule),
        find_dup=not args.no_dup,
        find_versions=not args.no_versions,
        find_junk=not args.no_junk,
        separate_large=args.separate_large,
        large_threshold=max(0, args.large_mb) * 1024 * 1024,
        clean_empty_dirs=not args.keep_empty_dirs)
    result = {}
    run_organize(opts, log=print, progress=lambda *a: None,
                 cancel_event=threading.Event(), done_cb=result.update)
    if result.get('cancelled'):
        sys.exit(130)
    sys.exit(1 if result.get('failed') else 0)


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.list_layouts:
        print('内置目录布局模板(--layout):')
        for tpl, desc in LAYOUT_PRESETS:
            print(f'  {tpl:<16} {desc}')
        print('\n可用占位符: {类别} {年} {年月} {来源} {扩展名}')
        sys.exit(0)

    if args.undo_journal:
        from .undo import undo
        if not os.path.isfile(args.undo_journal):
            print(f'错误:台账文件不存在: {args.undo_journal}', file=sys.stderr)
            sys.exit(2)
        stats = undo(args.undo_journal, log=print,
                     cancel=threading.Event())
        sys.exit(1 if stats.get('failed') else 0)

    if not args.input or not args.out:
        print('错误:需要 -i 输入 与 -o 输出目录'
              '(或用 --undo 撤销、--list-layouts 查看布局)。', file=sys.stderr)
        sys.exit(2)

    if args.mode == 'organize':
        _run_organize(args)
        return

    roster = _load_roster(args)
    if len(roster) == 0 and args.no_auto_id:
        print('错误:没有名单/关键字,又关闭了身份证号识别,无法分类。',
              file=sys.stderr)
        sys.exit(2)

    opts = JobOptions(
        inputs=args.input, out_dir=args.out, roster=roster,
        copy_to_each=args.each, auto_id=not args.no_auto_id,
        unit_mode=args.unit_mode,
        content_match=args.content_match, split_excel=args.split_excel,
        dedup=args.dedup,
        auto_pw_txt=not args.no_auto_pw_txt, pw_files=args.pw_file,
        delete_ok=args.delete_ok,
        intelligent=not args.no_smart,
        intelligent_min_freq=args.smart_min_freq,
        intelligent_exclude=args.smart_exclude)

    result = {}

    def done(summary):
        result.update(summary)

    run_job(opts,
            log=print,
            progress=lambda phase, cur, total: None,
            ask_password=_ask_password_tty,
            cancel_event=threading.Event(),
            done_cb=done)

    if result.get('cancelled'):
        sys.exit(130)
    sys.exit(1 if result.get('failed') else 0)


if __name__ == '__main__':
    main()
