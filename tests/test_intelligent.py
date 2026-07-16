# -*- coding: utf-8 -*-
"""智能识别模块测试。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.intelligent import (
    _tokenize_name,
    is_probable_person_name,
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


# ---------- is_probable_person_name:多层排除规则 ----------

def test_exclude_institutions():
    # 用户实际反馈的误判样本:机构名不能被当成人名
    for w in ('中国银行', '建设银行', '财政局', '保险公司', '铁路',
              '工商银行', '农业银行', '信用社', '派出所', '检察院',
              '供电局', '税务局', '人民医院', '中国移动', '高新区'):
        assert not is_probable_person_name(w), w


def test_exclude_places_and_titles():
    for w in ('北京', '上海', '黑龙江', '中国', '全国',
              '张科长', '李主任', '王经理', '刘书记', '陈律师'):
        assert not is_probable_person_name(w), w


def test_real_names_pass():
    for w in ('张三', '李四', '王小明', '欧阳锋', '张三丰',
              '孙科', '高丽', '常宁'):     # 姓氏开头的真实人名不能误杀
        assert is_probable_person_name(w), w


def test_non_surname_start_rejected():
    # 首字不是姓氏的通用词
    for w in ('建设', '开发', '数据', '综合', '专项'):
        assert not is_probable_person_name(w), w


def test_detect_names_excludes_institutions():
    files = [(f'p{i}', f'中国银行_张三_{i}.pdf') for i in range(15)]
    detected = detect_names(files, min_freq=10)
    names = {d['name'] for d in detected}
    assert '张三' in names
    assert '中国银行' not in names


def test_detect_names_user_exclude():
    files = [(f'p{i}', f'李四_{i}.pdf') for i in range(15)]
    detected = detect_names(files, min_freq=10, exclude=['李四'])
    assert detected == []


def test_detect_names_per_file_once():
    # 同一文件名里同一 token 出现两次只计 1 次
    files = [(f'p{i}', f'张三_张三_{i}.pdf') for i in range(9)]
    detected = detect_names(files, min_freq=10)
    assert detected == []


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


def test_name_id_unambiguous_beats_ambiguous():
    # "1名+1证号"的无歧义文件权重高于"2名+1证号"的歧义文件
    files = [
        ('p0', '张三_李四_110101199003078515_对比.pdf'),   # 歧义:2名1证
        ('p1', '李四_110101199003078515_户口.pdf'),        # 无歧义:证号属于李四
    ]
    n2i, i2n = build_name_id_map(files, {'张三', '李四'})
    assert n2i.get('李四') == '110101199003078515'
    assert i2n.get('110101199003078515') == '李四'
    # 该证号已归李四,不应再分给张三
    assert n2i.get('张三') != '110101199003078515'


def test_name_id_skips_roster_like_files():
    # 一个文件里姓名过多(名单/汇总表),不参与配对
    files = [
        ('p0', '张三_李四_王五_赵六_名册_110101199003078515.pdf'),
    ]
    n2i, _ = build_name_id_map(files, {'张三', '李四', '王五', '赵六'})
    assert n2i == {}


def test_name_id_empty_inputs_return_two_dicts():
    # 旧版名单为空时返回单个 {},调用方按二元组解包会崩溃
    n2i, i2n = build_name_id_map([], {'张三'})
    assert n2i == {} and i2n == {}
    n2i, i2n = build_name_id_map([('p0', 'x.pdf')], set())
    assert n2i == {} and i2n == {}


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
