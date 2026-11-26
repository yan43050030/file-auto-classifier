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
    assert detect_category(acct) == '其他数据'
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
        os.path.join('其他数据', '【建设银行】张三_开户信息.txt'),
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
    assert sorted(os.listdir(person / '其他数据')) == [
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
    assert os.listdir(out / f'张三_{ID}' / '其他数据') == ['【建设银行】张三_开户信息.txt']
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
    assert len(os.listdir(person / '其他数据')) == 2
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
