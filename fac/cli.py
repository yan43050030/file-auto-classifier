# -*- coding: utf-8 -*-
"""命令行模式:无界面批处理,可配合 Windows 计划任务自动处理固定收件目录。

示例:
    python 文件自动分类工具.py -i 收件目录 -o 结果目录 --roster 名单.xlsx
    python 文件自动分类工具.py -i a.zip b.rar -o out --kw 张三 --kw 李四,110101199001011234
"""

import argparse
import os
import sys
import threading

from . import VERSION, APP_NAME
from .roster import Roster
from .pipeline import JobOptions, run_job
from .util import read_text_any_encoding


def build_parser():
    p = argparse.ArgumentParser(
        prog=APP_NAME,
        description=f'{APP_NAME} {VERSION} 命令行模式:'
                    f'解压压缩包并按人员归档。不带参数运行则打开图形界面。')
    p.add_argument('-i', '--input', nargs='+', required=True,
                   metavar='路径', help='压缩包或含压缩包的文件夹(可多个)')
    p.add_argument('-o', '--out', required=True, metavar='目录',
                   help='分类结果输出目录')
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


def main(argv=None):
    args = build_parser().parse_args(argv)
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
        delete_ok=args.delete_ok)

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
