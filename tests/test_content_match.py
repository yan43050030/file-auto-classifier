# -*- coding: utf-8 -*-
"""内容匹配:旧版 .doc/.xls 提取与智能内容匹配。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.content_match import extract_text
from fac.idcard import check_digit
from fac.intelligent import IntelligentMatcher
from fac.roster import Roster

ID_A = '11010119900307851' + check_digit('11010119900307851')


def test_doc_heuristic_utf16(tmp_path):
    # 构造含 UTF-16LE 中文与 ASCII 证号的伪 .doc(非 OLE,走原始字节扫描)
    payload = b'\x00\x01garbage' + '张三户籍材料'.encode('utf-16-le') \
        + b'\x00\x00' + ID_A.encode('ascii') + b'\xff\xfe junk'
    f = tmp_path / '回执.doc'
    f.write_bytes(payload)
    text = extract_text(str(f))
    assert '张三' in text
    assert ID_A in text


def test_doc_heuristic_gbk(tmp_path):
    payload = b'\x00' + '李四流水'.encode('gbk') + b'\x00'
    f = tmp_path / 'a.doc'
    f.write_bytes(payload)
    assert '李四' in extract_text(str(f))


def test_xls_reading(tmp_path):
    xlwt = pytest.importorskip('xlwt')
    pytest.importorskip('xlrd')
    wb = xlwt.Workbook()
    ws = wb.add_sheet('反馈')
    ws.write(0, 0, '姓名')
    ws.write(1, 0, '张三')
    ws.write(1, 1, ID_A)          # 文本证号
    ws.write(2, 1, 6222001.0)     # 整数浮点不应带 .0
    f = tmp_path / '旧表.xls'
    wb.save(str(f))
    text = extract_text(str(f))
    assert '张三' in text and ID_A in text
    assert '6222001' in text and '6222001.0' not in text


def test_matcher_content_by_id():
    n2i = {'张三': ID_A}
    i2n = {ID_A: '张三'}
    im = IntelligentMatcher(Roster.from_text(''), n2i, i2n)
    r = im.match_content(f'关于协查的复函 公民 {ID_A} 情况如下')
    assert r is not None
    folder, via = r
    assert '张三' in folder and ID_A in folder and '内容' in via


def test_matcher_content_by_name_longest_first():
    im = IntelligentMatcher(Roster.from_text(''), {}, {},
                            detected_names={'张三', '张三丰'})
    folder, _via = im.match_content('兹证明张三丰同志…')
    assert folder == '张三丰'


def test_matcher_content_no_match():
    im = IntelligentMatcher(Roster.from_text(''), {}, {}, {'张三'})
    assert im.match_content('与本案无关的说明') is None
    assert im.match_content('') is None
