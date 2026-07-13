# -*- coding: utf-8 -*-
"""智能识别模块测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.intelligent import (
    _tokenize_name,
    detect_names,
    build_name_id_map,
    IntelligentMatcher,
)
from fac.roster import Roster


# ---------- tokenize ----------

def test_tokenize_simple():
    assert '张三' in _tokenize_name('张三_户籍证明.pdf')
    assert '李四' in _tokenize_name('110101199003078515_李四_报告.docx')


def test_tokenize_stop_words():
    # 报告/证明 等停用词应被过滤
    tokens = _tokenize_name('反馈报告_情况说明.pdf')
    assert '反馈' not in tokens    # 单字 或 停用词
    assert '报告' not in tokens
    assert '说明' not in tokens


def test_tokenize_short():
    # 长度 != 2-4 的纯中文 token 被跳过
    assert not _tokenize_name('张.pdf')
    assert not _tokenize_name('张三李四王五赵.txt')


# ---------- detect_names ----------

def test_detect_names_basic():
    files = []
    for i in range(15):
        files.append((f'p{i}', f'张三_{i}_报告.pdf'))
    for i in range(10):
        files.append((f'q{i}', f'李四_{i}_证明.docx'))
    detected = detect_names(files, min_freq=10)
    names = {d['name'] for d in detected}
    assert '张三' in names
    assert '李四' in names


def test_detect_names_below_threshold():
    files = [(f'p{i}', f'王五_{i}.pdf') for i in range(5)]
    detected = detect_names(files, min_freq=10)
    assert detected == []


def test_detect_names_stop_word_filtered():
    files = [(f'p{i}', f'报告_{i}.pdf') for i in range(15)]
    detected = detect_names(files, min_freq=10)
    names = {d['name'] for d in detected}
    assert '报告' not in names


# ---------- build_name_id_map ----------

def test_name_id_from_filename():
    files = [
        ('p0', '张三_110101199003078515_户口本.pdf'),
        ('p1', '110101199003078515_张三_银行流水.xlsx'),
        ('p2', '李四_320102198512120014_房产证.pdf'),
    ]
    n2i, i2n = build_name_id_map(files, {'张三', '李四'})
    assert n2i.get('张三') == '110101199003078515'
    assert n2i.get('李四') == '320102198512120014'
    assert i2n.get('110101199003078515') == '张三'


def test_name_id_majority_vote():
    # 同一个 name 对应多个 ID,取出现次数最多的
    files = [
        ('p0', '张三_110101199003078515_A.pdf'),
        ('p1', '张三_110101199003078515_B.pdf'),
        ('p2', '张三_110101199003078515_C.pdf'),
        ('p3', '张三_999999999999999999_D.pdf'),  # 错误的证号,仅出现1次
    ]
    n2i, _ = build_name_id_map(files, {'张三'})
    assert n2i.get('张三') == '110101199003078515'


# ---------- IntelligentMatcher ----------

def test_matcher_name_id_cross():
    n2i = {'张三': '110101199003078515'}
    i2n = {'110101199003078515': '张三'}
    im = IntelligentMatcher(Roster.from_text(''), n2i, i2n)
    # 文件名同时有姓名+证号
    f, via = im.match('张三_110101199003078515_报告.pdf')
    assert '张三' in f and '110101199003078515' in f
    assert '智能' in via


def test_matcher_name_only():
    n2i = {'张三': '110101199003078515'}
    i2n = {'110101199003078515': '张三'}
    im = IntelligentMatcher(Roster.from_text(''), n2i, i2n)
    # 文件名只有姓名没有证号
    f, via = im.match('张三_银行流水.pdf')
    assert '张三' in f and '110101199003078515' in f
    via_kw = '智能' in via


def test_matcher_id_only():
    n2i = {'张三': '110101199003078515'}
    i2n = {'110101199003078515': '张三'}
    im = IntelligentMatcher(Roster.from_text(''), n2i, i2n)
    # 文件名只有证号没有姓名
    f, via = im.match('110101199003078515_数据.pdf')
    assert '张三' in f and '110101199003078515' in f


def test_matcher_no_match():
    n2i = {'张三': '110101199003078515'}
    i2n = {'110101199003078515': '张三'}
    im = IntelligentMatcher(Roster.from_text(''), n2i, i2n)
    assert im.match('王五_文件.pdf') is None


def test_matcher_with_roster():
    # 名单优先于智能识别
    r = Roster.from_text('张三,110101199003078515\n')
    im = IntelligentMatcher(r, {}, {})
    f, via = im.match('张三_证明.pdf')
    assert '张三_110101199003078515' in f
    assert via == '名单'
