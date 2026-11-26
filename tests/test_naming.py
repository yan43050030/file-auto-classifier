# -*- coding: utf-8 -*-
"""文件名精简:信息/来源在前、姓名_证号在后;单位前缀精简;不造成重复导入。"""
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.naming import shorten_name, shorten_unit
from fac.idcard import check_digit
from fac.roster import Roster
from fac.pipeline import JobOptions, run_job

ID = '230303197511020123'
ID = ID[:17] + check_digit(ID[:17])
LONG1 = f'【某某查【2026】第123456号_2026年11月11日】张三_{ID}_某某查【2026】第123456号_保险信息.xlsx'
LONG2 = f'【202600010001查询结果】国土资源厅信息-张三-{ID}e1dhshrush23whdu.xlsx'


def test_user_examples():
    assert shorten_name(LONG1, '张三', ID) == (f'保险信息_张三_{ID}.xlsx', '20261111')
    assert shorten_name(LONG2, '张三', ID)[0] == f'国土资源厅信息_张三_{ID}.xlsx'


def test_keeps_unknown_parts_and_short_names():
    assert shorten_name('张三_工商银行流水.xlsx', '张三', ID)[0] == f'工商银行流水_张三_{ID}.xlsx'
    assert shorten_name(f'张三_{ID}.xlsx', '张三', ID)[0] == f'张三_{ID}.xlsx'
    assert shorten_name('【批次】.pdf')[0] == '【批次】.pdf'        # 去光了就保留原名
    old15 = ID[:6] + ID[8:17]
    assert shorten_name(f'张三_{old15}_户籍.pdf', '张三', ID, [old15])[0] == \
        f'户籍_张三_{ID}.pdf'


def test_shorten_unit():
    assert shorten_unit('某某查【2026】第123456号') == ''
    assert shorten_unit('202600010001查询结果') == ''
    assert shorten_unit('【202600010001查询结果】') == ''
    assert shorten_unit('第1批_工商银行') == '第1批_工商银行'
    assert shorten_unit('中国工商银行北京分行') == '中国工商银行北京分行'


def _run(src_files, out, **kw):
    src = out.parent / f'in{len(list(out.parent.glob("in*")))}'
    src.mkdir()
    for arc, files in src_files.items():
        with zipfile.ZipFile(src / arc, 'w') as z:
            for n, d in files.items():
                z.writestr(n, d)
    r = {}
    run_job(JobOptions([str(src)], str(out), Roster.from_text(f'张三,{ID}'),
                       unit_mode='category', intelligent=False, **kw),
            log=lambda m: None, progress=lambda *a: None,
            ask_password=lambda n, a: None, done_cb=r.update)
    return r


def test_pipeline_short_names_and_no_duplicate_on_reimport(tmp_path):
    out = tmp_path / 'out'
    batch = {'某某查【2026】第123456号.zip': {LONG1: '保单号 P001 ' * 5},
             '工商银行.zip': {LONG2.replace('国土资源厅信息', '工商银行账户信息'): '账号 6222 ' * 5}}
    _run(batch, out, short_names=True)
    person = out / f'张三_{ID}'
    assert sorted(os.listdir(person / '其他数据')) == [f'保险信息_张三_{ID}.xlsx']
    assert sorted(os.listdir(person / '银行流水')) == [f'【工商银行】工商银行账户信息_张三_{ID}.xlsx']
    assert (out / '文件名对照表.xlsx').exists()
    # 重新导入:开着精简、关掉精简,都不会再放一份
    assert _run(batch, out, short_names=True)['reimport_skipped'] == 2
    assert _run(batch, out, short_names=False)['reimport_skipped'] == 2
    assert len(list(person.rglob('*.xlsx'))) == 2


def test_collision_gets_date_then_number(tmp_path):
    out = tmp_path / 'out'
    a = f'【某某查【2026】第1号_2026年11月11日】张三_{ID}_保险信息.xlsx'
    b = f'【某某查【2026】第2号_2026年12月01日】张三_{ID}_保险信息.xlsx'
    _run({'a.zip': {a: 'v1' * 9}}, out, short_names=True)
    _run({'b.zip': {b: 'v2' * 9}}, out, short_names=True)
    names = sorted(os.listdir(out / f'张三_{ID}' / '其他数据'))
    assert names == [f'【a】保险信息_张三_{ID}.xlsx', f'【b】保险信息_张三_{ID}.xlsx'] or \
        names == [f'保险信息_张三_{ID}.xlsx', f'保险信息_张三_{ID}_20261201.xlsx']


def test_collision_same_unit_uses_date(tmp_path):
    out = tmp_path / 'out'
    a = f'【某某查【2026】第1号_2026年11月11日】张三_{ID}_保险信息.xlsx'
    b = f'【某某查【2026】第2号_2026年12月01日】张三_{ID}_保险信息.xlsx'
    _run({'某某查【2026】第1号.zip': {a: 'v1' * 9, b: 'v2' * 9}}, out, short_names=True)
    names = sorted(os.listdir(out / f'张三_{ID}' / '其他数据'))
    # 后放的那个补上它自己原文号块里的日期(谁先谁后取决于处理顺序)
    assert names[0] == f'保险信息_张三_{ID}.xlsx'
    assert names[1] in (f'保险信息_张三_{ID}_20261111.xlsx', f'保险信息_张三_{ID}_20261201.xlsx')
