# -*- coding: utf-8 -*-
"""归档库:多个压缩包/多次反馈的同一人归到一个文件夹,按资料类型细分;
可反复导入新反馈,重复导入自动跳过,核对表累计。"""
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.idcard import check_digit
from fac.roster import Roster
from fac.pipeline import JobOptions, run_job
from fac.library import parse_folder, Library, LEDGER_NAME
from fac.doctype import detect_category

openpyxl = pytest.importorskip('openpyxl')
ID = '11010119900307851' + check_digit('11010119900307851')
FLOW_HEAD = ['交易日期', '交易金额', '借贷标志', '余额', '对方户名', '摘要']


def xlsx(path, rows):
    wb = openpyxl.Workbook(); ws = wb.active
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


def run(src_files, out, roster='', **kw):
    """src_files: {压缩包名: {包内文件名: 内容或本地路径}}"""
    src = out.parent / f'in_{len(list(out.parent.glob("in_*")))}'
    src.mkdir()
    for arc, files in src_files.items():
        with zipfile.ZipFile(src / arc, 'w') as z:
            for name, data in files.items():
                if isinstance(data, str) and os.path.isfile(data):
                    z.write(data, name)
                else:
                    z.writestr(name, data)
    logs, r = [], {}
    kw.setdefault('unit_mode', 'category')
    kw.setdefault('intelligent', False)
    run_job(JobOptions([str(src)], str(out), Roster.from_text(roster), **kw),
            log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None, done_cb=r.update)
    return logs, r


def files_under(d):
    return sorted(os.path.relpath(os.path.join(r, f), d)
                  for r, _d, fs in os.walk(d) for f in fs)


def test_parse_folder():
    assert parse_folder(f'张三_{ID}') == ('张三', ID)
    assert parse_folder(ID) == ('', ID)
    assert parse_folder('张三') == ('张三', '')
    assert parse_folder('王伟_1') == ('王伟_1', '')


def test_detect_category(tmp_path):
    flow = xlsx(tmp_path / '查询结果.xlsx',
                [['某某银行账户交易明细'], FLOW_HEAD, ['2024-01-02', 100, '贷', 5000, '李四', '转账']])
    assert detect_category(flow) == '银行流水'
    acct = xlsx(tmp_path / '账户信息.xlsx',
                [['姓名', '证件号', '账号', '开户日期', '余额'], ['张三', ID, '6222', '2020-01-01', 10]])
    assert detect_category(acct) == '银行流水'            # 银行账户信息也归银行
    house = xlsx(tmp_path / '不动产信息.xlsx',
                 [['权利人', '证件号', '坐落', '面积'], ['张三', ID, '某小区1号楼', 90]])
    assert detect_category(house) == '其他数据'
    t = tmp_path / '张三_对账单.pdf'; t.write_bytes(b'%PDF')
    assert detect_category(str(t)) == '银行流水'          # 文件名即可判断


def test_multiple_archives_one_folder_by_category(tmp_path):
    flow = xlsx(tmp_path / 'f.xlsx', [FLOW_HEAD, ['2024-01-02', 100, '贷', 5000, '李四', '转账']])
    out = tmp_path / 'out'
    run({'建设银行.zip': {'张三_查询结果.xlsx': flow, '张三_开户信息.txt': '开户行:朝阳支行,账号6222…' * 3},
         '工商银行.zip': {'张三_回函.txt': '经查,张三在我行无账户。'},
         '房产中心.zip': {'张三_房产信息.txt': '坐落:北京市朝阳区某某小区1号楼101,面积90平方米' * 2}},
        out, f'张三,{ID}', empty_detect=True)
    person = out / f'张三_{ID}'
    assert files_under(person) == sorted([
        os.path.join('银行流水', '【建设银行】张三_查询结果.xlsx'),
        os.path.join('银行流水', '【建设银行】张三_开户信息.txt'),
        os.path.join('其他数据', '【房产中心】张三_房产信息.txt'),
        os.path.join('疑似空值', '【工商银行】张三_回函.txt'),
    ])
    # 不再按压缩包在顶层或人员下建单位文件夹
    assert not (out / '建设银行').exists() and not (person / '建设银行').exists()


def test_incremental_import_merges_and_report_accumulates(tmp_path):
    out = tmp_path / 'out'
    run({'建设银行.zip': {'张三_开户信息.txt': '开户行:朝阳支行,账号6222…' * 3}},
        out, f'张三,{ID}')
    # 过几天,工商银行的反馈来了 —— 直接导入到同一个结果目录
    _logs, r = run({'工商银行.zip': {'张三_账户情况.txt': '开户行:海淀支行,账号9555…' * 3}},
                   out, f'张三,{ID}')
    person = out / f'张三_{ID}'
    assert sorted(os.listdir(person / '银行流水')) == [
        '【工商银行】张三_账户情况.txt', '【建设银行】张三_开户信息.txt']
    wb = openpyxl.load_workbook(out / '反馈核对表.xlsx')
    rows = [[c.value for c in row] for row in wb.active.iter_rows()]
    head = rows[0]
    me = next(x for x in rows if x[0] == f'张三_{ID}')
    assert me[head.index('建设银行')] == 1 and me[head.index('工商银行')] == 1
    assert not list(out.glob('反馈核对表(*'))          # 覆盖更新,不另存一堆


def test_reimport_same_archive_is_skipped(tmp_path):
    out = tmp_path / 'out'
    batch = {'建设银行.zip': {'张三_开户信息.txt': '开户行:朝阳支行,账号6222…' * 3}}
    run(batch, out, f'张三,{ID}')
    _logs, r = run(batch, out, f'张三,{ID}')          # 不小心又导入一次
    assert r['reimport_skipped'] == 1
    assert os.listdir(out / f'张三_{ID}' / '银行流水') == ['【建设银行】张三_开户信息.txt']
    wb = openpyxl.load_workbook(out / '反馈核对表.xlsx')
    rows = [[c.value for c in row] for row in wb.active.iter_rows()]
    me = next(x for x in rows if x[0] == f'张三_{ID}')
    assert me[rows[0].index('建设银行')] == 1           # 不重复计数


def test_same_bank_new_content_is_kept(tmp_path):
    out = tmp_path / 'out'
    run({'建设银行.zip': {'张三_流水.txt': '2024年1月 交易若干' * 3}}, out, '张三')
    run({'建设银行.zip': {'张三_流水.txt': '2024年2月 补充交易' * 3}}, out, '张三')
    assert len(os.listdir(out / '张三' / '银行流水')) == 2   # 内容不同 → 都保留


def test_name_only_folder_upgraded_when_id_arrives(tmp_path):
    out = tmp_path / 'out'
    run({'建设银行.zip': {'张三_开户信息.txt': '开户行:朝阳支行,账号6222…' * 3}}, out, '张三')
    assert (out / '张三').is_dir()
    run({'工商银行.zip': {f'{ID}_账户.txt': '开户行:海淀支行,账号9555…' * 3}},
        out, f'张三,{ID}')
    assert not (out / '张三').exists()                       # 升级改名,没有分家
    person = out / f'张三_{ID}'
    assert len(os.listdir(person / '银行流水')) == 2
    ledger = (out / LEDGER_NAME).read_text(encoding='utf-8')
    assert '"rename"' in ledger
    wb = openpyxl.load_workbook(out / '反馈核对表.xlsx')
    names = [r[0].value for r in wb.active.iter_rows()]
    assert f'张三_{ID}' in names and '张三' not in names    # 核对表也跟着合并


def test_id_only_folder_upgraded_when_name_known(tmp_path):
    out = tmp_path / 'out'
    run({'公安.zip': {f'{ID}_户籍.txt': '户籍地址:北京市朝阳区某某街道' * 3}}, out, '')
    assert (out / ID).is_dir()
    run({'银行.zip': {'张三_开户信息.txt': '开户行:朝阳支行,账号6222…' * 3}},
        out, f'张三,{ID}')
    assert not (out / ID).exists()
    assert len(files_under(out / f'张三_{ID}')) == 2


def test_library_does_not_merge_ambiguous_names(tmp_path):
    out = tmp_path / 'out'
    (out / f'王伟_{ID}').mkdir(parents=True)
    other = '32010219851212001' + check_digit('32010219851212001')
    (out / f'王伟_{other}').mkdir()
    lib = Library(str(out))
    assert lib.resolve('王伟') == '王伟'          # 两个王伟,只有名字时不乱并
    assert lib.resolve(f'王伟_{other}') == f'王伟_{other}'


# 用户给出的常见调取清单
NON_BANK_SOURCES = [
    '人社厅个人基本信息', '省卫生和健康委员会全员人口基本信息', '国土自然资源厅信息',
    '人社厅社保信息', '不动产信息', '出生医学证明', '保险信息',
    '公安部出入境记录信息', '公安部出入境证件信息', '公安部旅馆住宿人员信息',
    '公安部人口和户籍信息', '铁路总公司票面信息', '铁路总公司同行人信息',
    '税务缴纳信息', '增值税专用发票信息', '自然资源部信息',
]
BANK_SOURCES = ['人民银行账户信息', '征信中心征信', '中国工商银行', '中国农业银行股份有限公司',
                '建行', '招商银行信用卡中心', '某某农村商业银行', '支付宝']


def test_source_list_classification(tmp_path):
    from fac.doctype import is_bank_related
    t = tmp_path / 'a.txt'; t.write_text('x', encoding='utf-8')
    for src in NON_BANK_SOURCES:
        # 文件名或来源单位是这些 → 都不是银行(即使表头带"个人账户/银行账号")
        assert not is_bank_related(str(t), f'张三_{src}.xlsx', ''), src
        assert not is_bank_related(str(t), '张三.xlsx', src), src
    for src in BANK_SOURCES:
        assert is_bank_related(str(t), f'张三_{src}.xlsx', ''), src
        assert is_bank_related(str(t), '张三.xlsx', src), src
    # 社保表里有银行账号列,但来源是社保 → 仍是其他数据
    sb = xlsx(tmp_path / '社保.xlsx', [['姓名', '个人账户', '发放银行账号'], ['张三', '1', '6222']])
    assert not is_bank_related(sb, '张三_人社厅社保信息.xlsx', '人社厅')


def test_bank_files_go_to_bank_folder_and_pboc_never_empty(tmp_path):
    flow = xlsx(tmp_path / 'f.xlsx', [['日期', '金额', '对方'], ['2024-01-02', 100, '李四']])
    pboc = xlsx(tmp_path / 'p.xlsx', [['姓名', '证件号码', '开户银行', '账号', '账户状态']])
    out = tmp_path / 'out'
    run({'第一批反馈.zip': {
            '张三_工商银行.xlsx': flow,                 # 表头不标准,但文件名有银行
            '张三_农业银行交易.xlsx': flow,
            '张三_人民银行账户信息.xlsx': pboc,        # 只有表头也不能算疑似空值
            '张三_公安部出入境记录信息.txt': '无出入境记录',
            '张三_铁路总公司票面信息.txt': '车次G1 北京南-上海虹桥 2024-01-02' * 2}},
        out, f'张三,{ID}', empty_detect=True)
    person = out / f'张三_{ID}'
    assert sorted(os.listdir(person / '银行流水')) == [
        '【第一批反馈】张三_人民银行账户信息.xlsx', '【第一批反馈】张三_农业银行交易.xlsx',
        '【第一批反馈】张三_工商银行.xlsx']
    assert sorted(os.listdir(person / '其他数据')) == [
        '【第一批反馈】张三_公安部出入境记录信息.txt', '【第一批反馈】张三_铁路总公司票面信息.txt']
    assert not (person / '疑似空值').exists()


def test_invoice_with_bank_account_column_is_not_bank(tmp_path):
    from fac.doctype import is_bank_related, is_pboc
    inv = xlsx(tmp_path / 'i.xlsx', [['发票代码', '开票日期', '金额', '税额', '购方开户行及账号'],
                                     ['011001', '2024-01-02', 1000, 130, '工商银行 6222…']])
    assert not is_bank_related(inv, '张三_增值税专用发票信息.xlsx', '')
    assert not is_bank_related(inv, '张三.xlsx', '国家税务总局某某市税务局')
    assert is_pboc('张三_征信中心征信.pdf', '')


def test_user_scenario_batches_marks_and_full_reimport(tmp_path):
    """5 人分 3 批反馈 + 用户在结果上做标记 + 忘了导过哪些、全部重新导入。"""
    import shutil
    people = ['张三', '李四', '王五', '赵六', '钱七']
    ids = {}
    for i, n in enumerate(people, 1):
        b = f'11010119900301{i}12'
        ids[n] = b + check_digit(b)
    roster = '\n'.join(f'{n},{ids[n]}' for n in people)
    out = tmp_path / 'out'
    flow = lambda n, amt: xlsx(tmp_path / f'{n}{amt}.xlsx',
                               [FLOW_HEAD] + [['2024-01-02', amt + k, '贷', 9, '某', 'x'] for k in range(5)])
    b1 = {'第1批_工商银行.zip': {f'{n}_流水.xlsx': flow(n, 100) for n in people},
          '第1批_公安户籍.zip': {f'{n}_人口和户籍信息.txt': f'{n} 户籍地址某街道' * 3 for n in people}}
    run(b1, out, roster)
    P = lambda n: out / f'{n}_{ids[n]}'
    # 标记:文件名前/后加备注、改文件内容、挪到自建文件夹、给人员文件夹改名
    f = next((P('张三') / '银行流水').iterdir()); f.rename(f.with_name('有100万元待查_' + f.name))
    f = next((P('李四') / '银行流水').iterdir())
    g = f.with_name(f.stem + '_已核' + f.suffix); f.rename(g)
    wb = openpyxl.load_workbook(g); wb.active['G1'] = '备注:3月5日50万需调单'; wb.save(g)
    (P('王五') / '重点').mkdir(); f = next((P('王五') / '银行流水').iterdir())
    shutil.move(str(f), str(P('王五') / '重点' / f.name))
    P('赵六').rename(out / f'赵六_{ids["赵六"]}_重点人员')
    snapshot = {p: p.stat().st_mtime for p in out.rglob('*') if p.is_file()
                and p.suffix in ('.xlsx', '.txt') and '核对表' not in p.name and '日志' not in p.name}
    # 第二、三批
    _l, r2 = run({'第2批_建设银行.zip': {f'{n}_交易明细.xlsx': flow(n, 500) for n in people[:3]},
                  '第3批_铁路.zip': {f'{n}_铁路总公司票面信息.txt': f'{n} G1次' * 3 for n in people[3:]}},
                 out, roster)
    assert r2['reimport_skipped'] == 0
    # 全部重新导入,外加一个重复下载的「(1)」压缩包
    _l, r3 = run({**b1,
                  '第1批_工商银行 (1).zip': b1['第1批_工商银行.zip'],
                  '第2批_建设银行.zip': {f'{n}_交易明细.xlsx': flow(n, 500) for n in people[:3]}},
                 out, roster)
    assert r3['reimport_skipped'] == r3['files'] == 18      # 全部识别为已导入
    folders = sorted(p.name for p in out.iterdir() if p.is_dir())
    assert len(folders) == 5 and f'赵六_{ids["赵六"]}_重点人员' in folders   # 没有分家
    assert sorted(p.name for p in (out / f'赵六_{ids["赵六"]}_重点人员').rglob('*.txt')) == \
        ['【第1批_公安户籍】赵六_人口和户籍信息.txt', '【第3批_铁路】赵六_铁路总公司票面信息.txt']
    for p, t in snapshot.items():                            # 标记过的文件一个没动
        assert p.exists() and p.stat().st_mtime == t, p
    assert len(list(out.rglob('*.xlsx'))) == 5 + 3 + 1       # 流水 8 个 + 核对表 1 个
