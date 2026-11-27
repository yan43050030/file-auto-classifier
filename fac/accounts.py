# -*- coding: utf-8 -*-
"""银行流水目录里的「账户汇总」表和「流水整理版」。

分类完成后,对本次有新银行反馈的人员 / 企业:
- 读 <人员>/银行流水/ 下全部文件(历次导入累计;不含疑似空值、不含本工具生成的文件),
  用 Case Intel 同一套流水识别(fac/flowcore)认出交易流水和开户信息;
- 生成《账户汇总_<人员>.xlsx》:每个账户一行(银行、卡号、起止、笔数、收支、交易量、
  当前余额……),最后是账户数和合计余额;
  只在开户信息 / 人民银行账户信息里出现、没调到流水的账户也列上,余额取开户信息里的;
- 可选:每个流水文件生成一份整理版(列按 时间/金额/余额/对方… 排好、去掉空列),
  放在 银行流水/流水整理版/ 里,原文件不动。

生成的文件不写进归档记录,也不会被当成反馈材料再次导入。
"""

import hashlib
import os
import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from .util import long_path

SUMMARY_PREFIX = '账户汇总_'
TIDY_DIR = '流水整理版'
TIDY_SUFFIX = '_整理'
FLOW_EXTS = ('.xlsx', '.xlsm', '.xls', '.csv', '.txt', '.htm', '.html', '.et')
_MAX_BYTES = 200 * 1024 * 1024


def is_generated(rel_path):
    """归档库里本工具生成的文件(账户汇总表、流水整理版)。"""
    parts = re.split(r'[\\/]+', os.path.normpath(rel_path))
    return TIDY_DIR in parts[:-1] or parts[-1].startswith(SUMMARY_PREFIX)


def _available():
    try:
        from .flowcore import quick_tools  # noqa: F401
        return True
    except Exception:
        return False


def flow_files(flow_dir):
    """银行流水目录下要读的文件(递归;跳过生成文件和 Office 临时文件)。"""
    out = []
    for root, dirs, files in os.walk(long_path(flow_dir)):
        dirs[:] = sorted(d for d in dirs if d != TIDY_DIR and not d.startswith('.'))
        for f in sorted(files):
            if f.startswith(('~$', '.', SUMMARY_PREFIX)):
                continue
            if f.lower().endswith(FLOW_EXTS):
                out.append(os.path.join(root, f))
    return out


def _read(path):
    try:
        if os.path.getsize(long_path(path)) > _MAX_BYTES:
            return None
        with open(long_path(path), 'rb') as fp:
            return fp.read()
    except OSError:
        return None


# ---------- 读流水 + 跨文件去重 ----------

def _rec_key(r):
    return (r.get('own_account') or '', r.get('_fx') or '', r['tx_date'], r.get('tx_time') or '',
            str(r['amount']), str(r.get('balance_after')), r.get('counterpart_account') or '',
            r.get('counterpart') or '')


def _dedupe(parsed):
    """同一账户的流水分几次调取、时间段有重叠时,重叠部分只算一次。
    同一文件里完全相同的几笔照常保留(可能真有),后面的文件只去掉前面已经有过的。"""
    seen = Counter()
    dropped = {}
    for p in parsed:
        if not p.res:
            continue
        c = Counter()
        keep = []
        for r in p.res.records:
            if not r.get('own_account'):
                keep.append(r)
                continue
            k = _rec_key(r)
            c[k] += 1
            if c[k] > seen[k]:
                keep.append(r)
        n = len(p.res.records) - len(keep)
        if n:
            dropped[p.filename] = (n, len(p.res.records))
        for k, v in c.items():
            seen[k] = max(seen[k], v)
        p.res.records = keep
    return dropped


# ---------- 开户信息 ----------

def _cny(cur):
    c = (cur or '').strip().upper()
    return c in ('', '人民币', 'CNY', 'RMB', '156', '人民币元', '本币')


def _dec(v):
    try:
        return Decimal(str(v).replace(',', ''))
    except (InvalidOperation, ValueError):
        return None


def _open_info(parsed_open, SP):
    """开户记录按账号 / 卡号合并:{归一账号: 记录}。同一账户有几条时优先有余额、日期新的。"""
    by = {}
    for fname, recs in parsed_open:
        for r in recs:
            nums = [SP._norm_acct(r.get(k) or '') for k in ('account_no', 'card_no')]
            nums = [n for n in nums if n and len(n.strip('*')) >= 6]
            if not nums:
                continue
            r = dict(r, _file=fname)
            cur = next((by[n] for n in nums if n in by), None)
            if cur is not None:
                better = (bool(r.get('balance')), r.get('last_tx_date') or '') > \
                         (bool(cur.get('balance')), cur.get('last_tx_date') or '')
                if better:
                    for k, v in cur.items():
                        r.setdefault(k, v)
                    cur = r
                else:
                    for k, v in r.items():
                        if v and not cur.get(k):
                            cur[k] = v
                r = cur
            for n in nums:
                by[n] = r
    uniq, seen = [], set()
    for r in by.values():
        if id(r) not in seen:
            seen.add(id(r))
            uniq.append(r)
    return uniq


# ---------- 汇总 ----------

def _bank_of(text):
    from .flowcore.bankname import canonical_bank
    try:
        return canonical_bank(text or '') or ''
    except Exception:
        return ''


def summarize(paths, log=None, who_name=''):
    """读一组文件,返回汇总 dict:accounts(有流水的 + 仅开户信息的)、total、files。
    who_name:户名空着时补上的名字(文件都在此人文件夹里)。"""
    from .flowcore import quick_tools as QT
    from .flowcore import statement_parser as SP

    parsed, opened, file_rows, flow_paths = [], [], [], []
    seen_digest = {}
    for path in paths:
        name = os.path.basename(path)
        b = _read(path)
        if b is None:
            file_rows.append({'file': name, 'ok': False, 'error': '读取失败或文件过大'})
            continue
        h = hashlib.sha1(b).hexdigest()
        if h in seen_digest:
            file_rows.append({'file': name, 'ok': False,
                              'error': f'与 {seen_digest[h]} 内容相同,未重复计算'})
            continue
        seen_digest[h] = name
        p = QT.parse_all([(name, b)])[0]
        if p.res:
            parsed.append(p)
            flow_paths.append(path)
            recs = p.res.meta.get('opening_records') or []
            if recs:
                opened.append((name, recs))
            continue
        try:
            recs = SP.parse_opening_file(b, name)
        except Exception:
            recs = []
        if recs:
            opened.append((name, recs))
            file_rows.append({'file': name, 'ok': True, 'kind': '开户信息', 'rows': len(recs)})
        else:
            why = p.error or ''
            if not why or '没认出' in why or '表头' in why:
                why = '不是流水表格(回函、说明、扫描件,或表头认不出)'
            file_rows.append({'file': name, 'ok': False, 'error': why})

    dropped = _dedupe(parsed)
    r = QT.stats_from_parsed(parsed)
    for f in r['files']:
        f['kind'] = '交易流水'
        if dropped.get(f['file']):
            f['dup'], f['rows'] = dropped[f['file']]
    files = r['files'] + file_rows

    accts = r['accounts']
    for a in accts:
        if not a['bank']:           # 流水里没写银行:看文件名(含【单位】前缀)
            a['bank'] = next((b for b in (_bank_of(f) for f in a['files']) if b), '')
        a['bank'] = _bank_of(a['bank']) or a['bank']
        if not a['name'] and who_name:
            a['name'] = who_name
        a['status'] = '有流水'
        a['balance'] = a['closing']
        a['balance_date'] = a['last'] if a['closing'] else ''
        a['balance_from'] = '流水最后一笔' if a['closing'] else ''
        a['open_balance'] = a['open_balance_date'] = a['account_status'] = ''

    index = {}
    for i, a in enumerate(accts):
        for n in (a['account'], a['card']):
            if n:
                index.setdefault(SP._norm_acct(n), i)

    for o in _open_info(opened, SP):
        nums = [SP._norm_acct(o.get(k) or '') for k in ('account_no', 'card_no')]
        hit = next((index[n] for n in nums if n in index), None)
        if hit is not None:
            a = accts[hit]
            a['open_balance'] = o.get('balance') or ''
            a['open_balance_date'] = o.get('last_tx_date') or ''
            a['account_status'] = o.get('account_status') or ''
            if not a['name'] and o.get('open_name'):
                a['name'] = o['open_name']
            if not a['balance'] and o.get('balance'):       # 流水里没有余额列
                a['balance'] = o['balance']
                a['balance_date'] = o.get('last_tx_date') or ''
                a['balance_from'] = '开户信息'
            if o['_file'] not in a['files']:
                a['files'].append(o['_file'])
            continue
        acc, card = o.get('account_no') or '', o.get('card_no') or ''
        if acc and card and SP._norm_acct(acc) == SP._norm_acct(card):
            card = ''
        cur = o.get('currency') or ''
        accts.append({
            'status': '未调取流水', 'name': o.get('open_name') or who_name,
            'bank': _bank_of(o.get('bank_name')) or _bank_of(o['_file']) or o.get('bank_name') or '',
            'account': acc, 'card': card, 'currency': '人民币' if _cny(cur) else cur,
            'first': '', 'last': '', 'count': '', 'in_count': '', 'in': '', 'out_count': '', 'out': '',
            'volume': '', 'net': '', 'opening': '', 'closing': '', 'max_balance': '', 'max_balance_at': '',
            'min_balance': '', 'cash_in': '', 'cash_out': '', 'self_in': '', 'self_out': '',
            'in_ext': '', 'out_ext': '',
            'balance': o.get('balance') or '', 'balance_date': o.get('last_tx_date') or '',
            'balance_from': '开户信息' if o.get('balance') else '',
            'open_balance': o.get('balance') or '', 'open_balance_date': o.get('last_tx_date') or '',
            'account_status': o.get('account_status') or '', 'files': [o['_file']],
        })

    t = dict(r['total'])
    cny = [a for a in accts if _cny(a['currency'])]
    flow_bal = sum((_dec(a['balance']) for a in cny
                    if a['balance'] and a['balance_from'] == '流水最后一笔'), Decimal(0))
    open_bal = sum((_dec(a['balance']) for a in cny
                    if a['balance'] and a['balance_from'] == '开户信息'), Decimal(0))
    t.update({
        'accounts': len(cny),
        'with_flow': sum(1 for a in cny if a['status'] == '有流水'),
        'open_only': sum(1 for a in cny if a['status'] != '有流水'),
        'no_balance': sum(1 for a in cny if not a['balance']),
        'balance': f'{flow_bal + open_bal:.2f}', 'balance_flow': f'{flow_bal:.2f}',
        'balance_open': f'{open_bal:.2f}',
        'foreign': sum(1 for a in accts if not _cny(a['currency'])),
    })
    accts.sort(key=lambda a: (not _cny(a['currency']), a['status'] != '有流水',
                              a['bank'], a['account'] or a['card']))
    return {'accounts': accts, 'total': t, 'files': files, 'flow_paths': flow_paths}


COLS = [('status', '情况'), ('name', '户名'), ('bank', '银行'), ('account', '账号'), ('card', '卡号'),
        ('currency', '币种'), ('first', '起始日期'), ('last', '截止日期'), ('count', '笔数'),
        ('in', '收入金额'), ('out', '支出金额'), ('volume', '交易量(收+支)'), ('net', '净额(收-支)'),
        ('balance', '当前余额'), ('balance_date', '余额日期'), ('balance_from', '余额来源'),
        ('open_balance', '开户信息余额(对照)'), ('open_balance_date', '开户信息余额日期'),
        ('account_status', '账户状态'),
        ('opening', '期初余额'), ('max_balance', '最高余额'), ('max_balance_at', '最高余额时间'),
        ('min_balance', '最低余额'), ('cash_in', '存现金额'), ('cash_out', '取现金额'),
        ('in_ext', '剔除互转后收入'), ('out_ext', '剔除互转后支出')]
_MONEY = {'in', 'out', 'volume', 'net', 'balance', 'open_balance', 'opening', 'max_balance',
          'min_balance', 'cash_in', 'cash_out', 'in_ext', 'out_ext'}


def write_xlsx(r, path, who=''):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from .flowcore import quick_tools as QT

    wb = Workbook()
    ws = wb.active
    ws.title = '账户汇总'
    ws.append(['序号'] + [t for _, t in COLS] + ['来源文件'])
    for i, a in enumerate(r['accounts'], 1):
        ws.append([i] + [QT._cell(a.get(k, ''), k in _MONEY) for k, _ in COLS] + ['、'.join(a['files'])])
    t = r['total']
    pos = {k: j + 2 for j, (k, _) in enumerate(COLS)}
    row = [''] * (len(COLS) + 2)
    row[0] = '合计'
    row[pos['status'] - 1] = '人民币'
    row[pos['bank'] - 1] = f'{t["accounts"]} 个账户'
    row[pos['account'] - 1] = f'有流水 {t["with_flow"]} 个,仅开户信息 {t["open_only"]} 个'
    row[pos['count'] - 1] = t['count']
    for k in ('in', 'out', 'volume', 'net', 'cash_in', 'cash_out', 'in_ext', 'out_ext'):
        row[pos[k] - 1] = QT._cell(t[k], True)
    row[pos['balance'] - 1] = QT._cell(t['balance'], True)
    row[pos['balance_date'] - 1] = '合计余额'
    ws.append([])
    ws.append(row)
    total_row = ws.max_row
    ws.append([])
    notes = [
        f'合计余额 {Decimal(t["balance"]):,.2f} 元 = 有流水账户的最后一笔余额 {Decimal(t["balance_flow"]):,.2f}'
        f' + 仅有开户信息账户的余额 {Decimal(t["balance_open"]):,.2f}'
        + (f';另有 {t["no_balance"]} 个账户查不到余额,未计入' if t['no_balance'] else '') + '。',
        '当前余额:有流水的取流水最后一笔交易后的余额(余额日期即最后交易日);'
        '只在开户信息 / 人民银行账户信息里出现、没调到流水的账户,取开户信息里的账户余额。',
        '开户信息余额(对照):开户信息里写的余额,与流水对不上时请核实调取时间段。',
        '同一账户分几次调取、时间段重叠的,重叠部分只算一次;内容完全相同的文件只算一次。',
        '剔除互转:对方账号是本表另一个账户的收支不算;外币账户单列,不计入人民币合计。',
        '本表由「文件自动分类工具」按银行流水目录里的文件自动生成,每次导入新反馈后重新生成,请勿在此表上手改。',
    ]
    for n in notes:
        ws.append([n])
    money_cols = {pos[k] for k in _MONEY}
    QT._style(ws, header_row=1, money_cols=money_cols, text_cols={pos['account'], pos['card']},
              key_cols=pos['balance'])
    ws.column_dimensions['A'].width = 6           # 说明行写在 A 列,向右溢出显示即可
    bold = Font(bold=True)
    fill = PatternFill('solid', fgColor='FFF2CC')
    for c in ws[total_row]:
        c.font = bold
        c.fill = fill
    gray = Font(color='808080')
    for i, a in enumerate(r['accounts'], 2):
        if a['status'] != '有流水':
            for c in ws[i]:
                if c.column not in (pos['balance'],):
                    c.font = gray
    for rr in range(total_row + 2, ws.max_row + 1):
        ws.cell(rr, 1).font = gray
    ws.auto_filter.ref = f'A1:{ws.cell(1, ws.max_column).column_letter}{1 + len(r["accounts"])}'

    fs = wb.create_sheet('文件情况')
    fs.append(['文件', '类型', '结果', '说明'])
    for f in r['files']:
        if f['ok']:
            if f.get('kind') == '开户信息':
                fs.append([f['file'], '开户信息', f'{f["rows"]} 条', ''])
            else:
                sk = ';'.join(f'{k} {v} 行' for k, v in (f.get('skipped') or {}).items())
                note = [f.get('format') or '', sk and f'跳过 {sk}',
                        f.get('dup') and f'与其他文件重叠 {f["dup"]} 笔,未重复计算'] + (f.get('warnings') or [])
                fs.append([f['file'], '交易流水', f'{f["rows"]} 笔', ';'.join(x for x in note if x)])
        else:
            fs.append([f['file'], '', '未计入', f['error']])
    QT._style(fs, wrap_cols={4}, max_width=90)
    tmp = path + '.tmp'
    wb.save(long_path(tmp))
    os.replace(long_path(tmp), long_path(path))


def build(person_dir, summary=True, tidy=False, flow_sub='银行流水', log=print):
    """为一个人员 / 企业文件夹生成(覆盖)账户汇总表,并按需生成流水整理版。
    返回 (汇总表路径或 None, 汇总 dict 或 None, 新生成的整理版个数)。"""
    flow_dir = os.path.join(person_dir, flow_sub)
    paths = flow_files(flow_dir)
    if not paths:
        return None, None, 0
    from .library import parse_folder
    who_name = parse_folder(os.path.basename(os.path.normpath(person_dir)))[0]
    r = summarize(paths, log, who_name)
    out = None
    if summary and r['accounts']:
        who = who_name or os.path.basename(os.path.normpath(person_dir))
        out = os.path.join(flow_dir, f'{SUMMARY_PREFIX}{who}.xlsx')
        write_xlsx(r, out, who)
    n = 0
    if tidy:
        for fp in r['flow_paths']:
            if tidy_file(fp, flow_dir) == 'new':
                n += 1
    return out, r, n


def tidy_file(path, flow_dir):
    """给一个流水文件生成整理版,放在 流水整理版/ 里(同名已存在且比原文件新就跳过)。
    返回 'new' / 'kept'(已是最新);认不出流水表返回 None。"""
    from .flowcore import quick_tools as QT
    rel = os.path.relpath(os.path.dirname(path), flow_dir)
    dst_dir = os.path.join(flow_dir, TIDY_DIR, '' if rel == '.' else rel)
    stem = os.path.splitext(os.path.basename(path))[0]
    dst = os.path.join(dst_dir, f'{stem}{TIDY_SUFFIX}.xlsx')
    try:
        if os.path.getmtime(long_path(dst)) >= os.path.getmtime(long_path(path)):
            return 'kept'
    except OSError:
        pass
    b = _read(path)
    if b is None:
        return None
    try:
        data, _info = QT.tidy([(os.path.basename(path), b)])
    except Exception:
        return None
    os.makedirs(long_path(dst_dir), exist_ok=True)
    with open(long_path(dst), 'wb') as fp:
        fp.write(data)
    return 'new'
