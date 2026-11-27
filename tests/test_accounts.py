# -*- coding: utf-8 -*-
"""银行流水目录的账户汇总表 / 流水整理版。"""
import os
import sys
import zipfile
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

pytest.importorskip('pandas')

from flow_samples import CCB_ROWS, ccb_xlsx, icbc_csv, opening_xlsx  # noqa: E402
from fac import accounts as A  # noqa: E402
from fac.idcard import check_digit  # noqa: E402
from fac.library import Library  # noqa: E402
from fac.pipeline import JobOptions, run_job  # noqa: E402
from fac.roster import Roster  # noqa: E402

ID = '11010119900307851' + check_digit('11010119900307851')


def _person(tmp_path):
    d = tmp_path / f'张三_{ID}' / '银行流水'
    d.mkdir(parents=True)
    (d / '【建行】交易流水_张三.xlsx').write_bytes(ccb_xlsx())
    (d / '【建行】交易流水_张三_第二批.xlsx').write_bytes(ccb_xlsx(CCB_ROWS[2:]))   # 与第一批重叠
    (d / '【工行】张三_工商银行.csv').write_bytes(icbc_csv())
    (d / '【农行】开户信息_张三.xlsx').write_bytes(opening_xlsx())
    (d / '【某行】回函.txt').write_text('经查,未发现该客户在我行开户。', encoding='utf-8')
    return d.parent


def test_vendored_flowcore_imports():
    from fac.flowcore import quick_tools, statement_parser  # noqa: F401
    assert A._available()


def test_summary_accounts_and_total(tmp_path):
    out, r, n = A.build(str(_person(tmp_path)), tidy=True)
    assert out and os.path.basename(out) == '账户汇总_张三.xlsx'
    by = {a['account']: a for a in r['accounts']}
    ccb = by['2301000000000000001']
    assert ccb['bank'] == '建设银行' and ccb['count'] == 4          # 第二批的重叠部分不重复计
    assert ccb['balance'] == '3499.90' and ccb['balance_from'] == '流水最后一笔'
    assert ccb['open_balance'] == '3499.90'                           # 开户信息余额作对照
    icbc = by['6222000000000000002']
    assert icbc['bank'] == '工商银行' and icbc['name'] == '张三'       # 银行看文件名,户名看文件夹
    abc = by['6228480000000000003']
    assert abc['status'] == '未调取流水' and abc['bank'] == '农业银行'
    assert abc['balance'] == '12345.67' and abc['balance_from'] == '开户信息'
    t = r['total']
    assert t['accounts'] == 4 and t['with_flow'] == 2 and t['open_only'] == 2
    assert Decimal(t['balance']) == Decimal('3499.90') + Decimal('1500.10') + Decimal('12345.67')
    files = {f['file']: f for f in r['files']}
    assert files['【建行】交易流水_张三_第二批.xlsx']['dup'] == 2
    assert not files['【某行】回函.txt']['ok']
    assert n == 3                                                     # 三份流水各一份整理版

    import openpyxl
    ws = openpyxl.load_workbook(out)['账户汇总']
    vals = [c for row in ws.iter_rows(values_only=True) for c in row if c is not None]
    assert '合计余额' in vals and 17345.67 in vals


def test_tidy_versions_and_skip_unchanged(tmp_path):
    p = _person(tmp_path)
    A.build(str(p), summary=False, tidy=True)
    tidy_dir = p / '银行流水' / A.TIDY_DIR
    names = {x.name for x in tidy_dir.iterdir()}
    assert names == {'【工行】张三_工商银行_整理.xlsx', '【建行】交易流水_张三_第二批_整理.xlsx',
                     '【建行】交易流水_张三_整理.xlsx'}
    assert not list((p / '银行流水').glob('账户汇总_*'))
    _, _, n = A.build(str(p), summary=False, tidy=True)
    assert n == 0                                                     # 原文件没变不重复生成
    # 生成的文件本身不会被当成流水再读
    assert all(A.TIDY_DIR not in f and '账户汇总_' not in f for f in A.flow_files(str(p / '银行流水')))


def test_is_generated():
    assert A.is_generated(os.path.join('张三', '银行流水', '账户汇总_张三.xlsx'))
    assert A.is_generated(os.path.join('张三', '银行流水', '流水整理版', 'x_整理.xlsx'))
    assert not A.is_generated(os.path.join('张三', '银行流水', '工商银行.xlsx'))


def _run(opts):
    result = {}
    run_job(opts, log=lambda m: None, progress=lambda *a: None,
            ask_password=lambda n, a: None, done_cb=result.update)
    return result


def test_pipeline_writes_summary_and_ledger_ignores_it(tmp_path):
    src = tmp_path / 'in'; src.mkdir()
    with zipfile.ZipFile(src / '建设银行.zip', 'w') as z:
        z.writestr(f'张三_{ID}_交易流水.xlsx', ccb_xlsx())
    with zipfile.ZipFile(src / '农业银行.zip', 'w') as z:
        z.writestr(f'张三_{ID}_开户信息.xlsx', opening_xlsx())
    out = tmp_path / 'out'
    res = _run(JobOptions([str(src)], str(out), Roster.from_text(f'张三,{ID}'), intelligent=False,
                          unit_mode='category', account_summary=True, tidy_flows=True))
    flow = out / f'张三_{ID}' / '银行流水'
    summ = list(flow.glob('账户汇总_*.xlsx'))
    assert len(summ) == 1 and res['account_summaries']
    assert list((flow / A.TIDY_DIR).glob('*_整理.xlsx'))
    # 归档记录里只有两份反馈,汇总表 / 整理版都不在;同步时也不算"你手动放进来的"
    lib = Library(str(out))
    paths = [st['path'] for st in lib.current_files().values()]
    assert len(paths) == 2 and not any(A.is_generated(x) for x in paths)
    assert lib.sync()['unregistered'] == 0

    # 第二次导入新反馈:汇总表按累计重新生成
    src2 = tmp_path / 'in2'; src2.mkdir()
    with zipfile.ZipFile(src2 / '工商银行.zip', 'w') as z:
        z.writestr(f'张三_{ID}_工商银行.csv', icbc_csv())
    _run(JobOptions([str(src2)], str(out), Roster.from_text(f'张三,{ID}'), intelligent=False,
                    unit_mode='category', account_summary=True, tidy_flows=True))
    import openpyxl
    ws = openpyxl.load_workbook(summ[0])['账户汇总']
    accts = {row[4] for row in ws.iter_rows(min_row=2, values_only=True) if isinstance(row[0], int)}
    assert '6222000000000000002' in accts and '2301000000000000001' in accts


def test_library_default_off(tmp_path):
    o = JobOptions([], '.', Roster([]))
    assert o.account_summary is False and o.tidy_flows is False
