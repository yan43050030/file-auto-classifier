# -*- coding: utf-8 -*-
"""疑似空值:查无账户等小反馈单独放;有实质数据的小表格不能被藏起来。"""
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.emptyfile import empty_reason, BUCKET_EMPTY
from fac.idcard import check_digit
from fac.roster import Roster
from fac.pipeline import JobOptions, run_job

openpyxl = pytest.importorskip('openpyxl')
ID = '11010119900307851' + check_digit('11010119900307851')
KW = ['张三', ID]


def xlsx(path, rows, title=None):
    wb = openpyxl.Workbook(); ws = wb.active
    if title:
        ws.append([title])
    for r in rows:
        ws.append(r)
    wb.save(path)
    return str(path)


HEAD = ['序号', '姓名', '证件号码', '开户行', '账号', '余额']


def test_header_only_table_is_empty(tmp_path):
    p = xlsx(tmp_path / 'a.xlsx', [HEAD], title='某某银行账户查询反馈表')
    assert empty_reason(p, keywords=KW) == '表格只有表头/无实质数据'


def test_row_with_only_queried_person_and_nulls_is_empty(tmp_path):
    p = xlsx(tmp_path / 'a.xlsx', [HEAD, [1, '张三', ID, '无', '/', '-']])
    assert empty_reason(p, keywords=KW)


def test_row_saying_no_account_is_empty(tmp_path):
    p = xlsx(tmp_path / 'a.xlsx', [HEAD, [1, '张三', ID, '该客户在我行未开户', '', '']])
    assert empty_reason(p, keywords=KW) == '表格注明查无记录'


def test_small_table_with_real_account_is_kept(tmp_path):
    # 只有一条账户记录的小表格 —— 必须留在正常目录
    p = xlsx(tmp_path / 'a.xlsx',
             [HEAD, [1, '张三', ID, '某某银行朝阳支行', '6222020200012345678', 1523.4]])
    assert os.path.getsize(p) < 10 * 1024
    assert empty_reason(p, keywords=KW) is None


def test_text_and_csv(tmp_path):
    t = tmp_path / '回函.txt'
    t.write_text('经查,张三(证件号码 %s)在我行无账户。' % ID, encoding='utf-8')
    assert empty_reason(str(t), keywords=KW) == '正文注明查无记录'
    t2 = tmp_path / '说明.txt'
    t2.write_text('张三于2021年在我行开立账户,卡号6222…,目前状态正常,'
                  '近一年交易明细见附件。', encoding='utf-8')
    assert empty_reason(str(t2), keywords=KW) is None
    c = tmp_path / 'a.csv'
    c.write_text('姓名,账号\n张三,无\n', encoding='utf-8')
    assert empty_reason(str(c), keywords=KW)


def test_size_threshold_and_unreadable(tmp_path):
    big = xlsx(tmp_path / 'big.xlsx', [HEAD])
    assert empty_reason(big, max_bytes=1024, keywords=KW) is None   # 超阈值不判
    z = tmp_path / '空.pdf'; z.write_bytes(b'')
    assert empty_reason(str(z)) == '空文件'
    img = tmp_path / '盖章.jpg'; img.write_bytes(b'\xff\xd8' + b'0' * 3000)
    assert empty_reason(str(img)) == '小于 10 KB'                    # 读不了 → 按大小


def test_pipeline_puts_empty_into_person_subfolder_and_report(tmp_path):
    src = tmp_path / 'in'; src.mkdir()
    a = xlsx(tmp_path / 'h.xlsx', [HEAD])
    b = xlsx(tmp_path / 'r.xlsx',
             [HEAD, [1, '张三', ID, '某某支行', '6222020200012345678', 88]])
    with zipfile.ZipFile(src / '甲银行.zip', 'w') as z:
        z.write(a, '张三_账户查询.xlsx')
    with zipfile.ZipFile(src / '乙银行.zip', 'w') as z:
        z.write(b, '张三_账户查询.xlsx')
        z.writestr('张三_回函.txt', '经查,张三在我行无开户记录。')
    out = tmp_path / 'out'
    logs, r = [], {}
    run_job(JobOptions([str(src)], str(out), Roster.from_text(f'张三,{ID}'),
                       intelligent=False, empty_detect=True),
            log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None, done_cb=r.update)
    person = out / f'张三_{ID}'
    assert (person / BUCKET_EMPTY / '甲银行' / '张三_账户查询.xlsx').exists()
    assert (person / BUCKET_EMPTY / '乙银行' / '张三_回函.txt').exists()
    assert (person / '乙银行' / '张三_账户查询.xlsx').exists()      # 有数据,正常放
    assert r['empty'] == 2
    wb = openpyxl.load_workbook(out / '反馈核对表.xlsx')
    rows = [[c.value for c in row] for row in wb.active.iter_rows()]
    header = rows[0]
    me = next(x for x in rows if x[0] == f'张三_{ID}')
    assert me[header.index('甲银行')] == '疑似空'
    assert me[header.index('乙银行')] == '2(空1)'


def test_pipeline_empty_detect_off(tmp_path):
    src = tmp_path / 'in'; src.mkdir()
    a = xlsx(tmp_path / 'h.xlsx', [HEAD])
    with zipfile.ZipFile(src / '甲银行.zip', 'w') as z:
        z.write(a, '张三_账户查询.xlsx')
    out = tmp_path / 'out'
    run_job(JobOptions([str(src)], str(out), Roster.from_text('张三'),
                       intelligent=False, empty_detect=False),
            log=lambda m: None, progress=lambda *a: None,
            ask_password=lambda n, a: None)
    assert (out / '张三' / '甲银行' / '张三_账户查询.xlsx').exists()
