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
    FLOW = ['交易日期', '交易金额', '借贷标志', '账户余额', '对方户名', '摘要']
    a = xlsx(tmp_path / 'h.xlsx', [FLOW])                       # 流水:只有表头
    b = xlsx(tmp_path / 'r.xlsx',
             [FLOW, ['2024-01-02', 88, '贷', 1000, '李四', '转账']])
    with zipfile.ZipFile(src / '甲银行.zip', 'w') as z:
        z.write(a, '张三_账户查询.xlsx')
    with zipfile.ZipFile(src / '乙银行.zip', 'w') as z:
        z.write(b, '张三_账户查询.xlsx')
        z.writestr('张三_回函.txt', '经查,未查询到张三在我行的交易流水。')
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


def test_empty_only_for_bank_feedback(tmp_path):
    """机动车、出入境等信息本来就小,不能被当成疑似空值;银行的查无账户才是。"""
    from fac.emptyfile import BUCKET_EMPTY
    src = tmp_path / 'in'; src.mkdir()
    car = xlsx(tmp_path / 'car.xlsx', [['号牌号码', '车辆类型', '所有人', '状态'],
                                       ['京A12345', '小型轿车', '张三', '正常']])
    car_none = xlsx(tmp_path / 'car0.xlsx', [['号牌号码', '车辆类型', '所有人', '状态']])
    acct_none = xlsx(tmp_path / 'acct.xlsx', [['姓名', '证件号码', '开户行', '账号', '余额']])
    flow_none = xlsx(tmp_path / 'flow.xlsx', [['交易日期', '交易金额', '余额', '对方户名']])
    with zipfile.ZipFile(src / '车管所.zip', 'w') as z:
        z.write(car, '张三_机动车登记信息.xlsx')
        z.write(car_none, '张三_驾驶证信息.xlsx')          # 只有表头,但不是银行
    with zipfile.ZipFile(src / '出入境.zip', 'w') as z:
        z.writestr('张三_出入境记录.txt', '无出入境记录')    # 有"无"字样,但不是银行
    with zipfile.ZipFile(src / '协查反馈.zip', 'w') as z:
        z.write(acct_none, '张三_查询结果.xlsx')            # 账户列表头:是银行资料,但不是流水
        z.write(flow_none, '张三_协查结果.xlsx')            # 流水表头、无数据 → 疑似空值
    with zipfile.ZipFile(src / '建行.zip', 'w') as z:       # 简称
        z.writestr('张三_回函.txt', '经查,该人在我行无交易流水。')
    out = tmp_path / 'out'
    run_job(JobOptions([str(src)], str(out), Roster.from_text('张三'),
                       intelligent=False, empty_detect=True, unit_mode='category'),
            log=lambda m: None, progress=lambda *a: None,
            ask_password=lambda n, a: None)
    empties = sorted(os.listdir(out / '张三' / BUCKET_EMPTY))
    assert empties == ['【协查反馈】张三_协查结果.xlsx', '【建行】张三_回函.txt']
    assert '【协查反馈】张三_查询结果.xlsx' in os.listdir(out / '张三' / '银行流水')
    others = sorted(os.listdir(out / '张三' / '其他数据'))
    assert others == ['【出入境】张三_出入境记录.txt', '【车管所】张三_机动车登记信息.xlsx',
                      '【车管所】张三_驾驶证信息.xlsx']


def test_is_bank_related(tmp_path):
    from fac.doctype import is_bank_related
    t = tmp_path / 'a.txt'; t.write_text('x', encoding='utf-8')
    assert is_bank_related(str(t), '张三_回执.txt', '中国工商银行北京分行')
    assert is_bank_related(str(t), '张三_回执.txt', '农行反馈')
    assert is_bank_related(str(t), '张三_支付宝账户.txt', '某单位')
    assert not is_bank_related(str(t), '张三_回执.txt', '公安局平安建设办公室')
    assert not is_bank_related(str(t), '张三_出入境.txt', '出入境管理局')


def test_bank_non_flow_files_never_empty(tmp_path):
    """开户信息、金融理财等不是交易流水:再小也不进疑似空值,放「银行流水」(银行资料)。"""
    from fac.emptyfile import BUCKET_EMPTY
    from fac.doctype import is_bank_flow
    src = tmp_path / 'in'; src.mkdir()
    opening = xlsx(tmp_path / 'o.xlsx', [['户名', '证件号码', '账号', '开户日期', '联系电话'],
                                         ['张三', ID, '6222', '2015-01-01', '暂无']])
    licai = xlsx(tmp_path / 'l.xlsx', [['产品名称', '购买日期', '购买金额', '状态']])   # 理财:只有表头
    licai_flow = xlsx(tmp_path / 'lf.xlsx', [['交易日期', '交易金额', '余额', '摘要']])  # 名字写理财
    with zipfile.ZipFile(src / '工商银行.zip', 'w') as z:
        z.write(opening, '张三_开户信息.xlsx')
        z.writestr('张三_账户信息.txt', '户名:张三 账号:6222… 状态:正常 未发生冻结')
    with zipfile.ZipFile(src / '建设银行.zip', 'w') as z:
        z.write(licai, '张三_金融理财.xlsx')
        z.write(licai_flow, '张三_理财产品.xlsx')
    out = tmp_path / 'out'
    run_job(JobOptions([str(src)], str(out), Roster.from_text('张三'),
                       intelligent=False, empty_detect=True, unit_mode='category'),
            log=lambda m: None, progress=lambda *a: None,
            ask_password=lambda n, a: None)
    assert not (out / '张三' / BUCKET_EMPTY).exists()
    assert sorted(os.listdir(out / '张三' / '银行流水')) == [
        '【工商银行】张三_开户信息.xlsx', '【工商银行】张三_账户信息.txt',
        '【建设银行】张三_理财产品.xlsx', '【建设银行】张三_金融理财.xlsx']
    # 文件名写明是流水的,即使混了别的词也算流水
    t = tmp_path / 'x.txt'; t.write_text('x', encoding='utf-8')
    assert is_bank_flow(str(t), '张三_理财账户交易流水.xlsx')
    assert not is_bank_flow(str(t), '张三_开户信息.xlsx')
