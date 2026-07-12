# -*- coding: utf-8 -*-
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.idcard import check_digit
from fac.roster import Roster, Person

ID_A = '11010119900307851' + check_digit('11010119900307851')
ID_B = '32010219851212001' + check_digit('32010219851212001')


def test_longest_match_wins():
    r = Roster.from_text('张三\n张三丰\n')
    ps = r.match('张三丰_材料.txt')
    assert [p.name for p in ps] == ['张三丰']   # 旧版 bug:会归入张三


def test_plain_keyword():
    r = Roster.from_text('某某有限公司\n')
    assert [p.name for p in r.match('某某有限公司_年报.pdf')] == ['某某有限公司']


def test_multi_identity_same_person():
    r = Roster.from_text(f'李四,{ID_B},李小四\n')
    p = r.persons[0]
    assert r.match(f'反馈_{ID_B}.xlsx') == [p]      # 证号命中
    assert r.match('李小四_银行流水.pdf') == [p]     # 曾用名命中
    assert r.match('李四_房产.docx') == [p]          # 姓名命中


def test_comment_and_blank_lines():
    r = Roster.from_text('# 注释\n\n张三\n')
    assert len(r) == 1


def test_duplicate_names_get_id_suffix():
    r = Roster.from_text(f'王伟,{ID_A}\n王伟,{ID_B}\n')
    folders = {p.folder for p in r.persons}
    assert len(folders) == 2
    assert all('王伟_' in f for f in folders)


def test_multiple_hits_ordering():
    r = Roster.from_text('张三\n李四\n')
    ps = r.match('李四与张三对比.txt')
    assert {p.name for p in ps} == {'张三', '李四'}


def test_id15_variant_matches_18():
    # 名单里登记 15 位老号,文件名里是升位后的 18 位也能命中
    r = Roster.from_text('赵六,110101900307851\n')
    v18 = '11010119900307851' + check_digit('11010119900307851')
    assert [p.name for p in r.match(f'{v18}.pdf')] == ['赵六']


def test_from_excel(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['姓名', '身份证号', '曾用名', '备注'])
    ws.append(['张三', ID_A, '张小三', '这是备注不应成为关键字'])
    ws.append(['李四', ID_B, '', ''])
    f = tmp_path / '名单.xlsx'
    wb.save(f)
    r = Roster.from_excel(str(f))
    assert len(r) == 2
    p = r.persons[0]
    assert p.name == '张三' and ID_A in p.ids and '张小三' in p.aliases
    # 备注列不应参与匹配
    assert r.match('这是备注不应成为关键字.txt') == []


def test_from_excel_no_header(tmp_path):
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(['张三', ID_A])
    ws.append(['李四', ID_B])
    f = tmp_path / 'plain.xlsx'
    wb.save(f)
    r = Roster.from_excel(str(f))
    assert len(r) == 2
    assert ID_A in r.persons[0].ids
