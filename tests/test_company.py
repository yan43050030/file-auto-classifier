# -*- coding: utf-8 -*-
"""企业识别:统一社会信用代码校验、公司名称提取、名称↔代码关联、端到端归档。"""
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.company import (valid_uscc, uscc_check_char, find_usccs,
                         find_company_names, build_company_map, CompanyMatcher)
from fac.roster import Roster
from fac.pipeline import JobOptions, run_job

# 公开可查的真实代码(用于验证校验算法)
REAL = ['914403001922038216', '91440300708461136T', '91330100716105852F']


def make_uscc(head8, org8):
    """按国标造一个校验正确的虚构代码(组织机构代码校验位 + 整体校验位)。"""
    w = (3, 7, 9, 10, 5, 8, 4, 2)
    v = 11 - sum(int(c, 36) * x for c, x in zip(org8, w)) % 11
    body = head8 + org8 + ('X' if v == 10 else '0' if v == 11 else str(v))
    return body + uscc_check_char(body)


C1 = make_uscc('91110108', 'MA01AB2C')
C2 = make_uscc('91310115', 'MA1K4D5E')


def test_valid_uscc_real_codes():
    for c in REAL:
        assert valid_uscc(c)
        assert valid_uscc(c.lower())


def test_valid_uscc_rejects_bad():
    assert not valid_uscc('914403001922038217')          # 校验位错
    assert not valid_uscc('91440300708461136Y')
    assert not valid_uscc('9144030070846113')             # 长度不对
    assert not valid_uscc('91440300708461136I')           # 含非法字符 I
    assert not valid_uscc('110101199003078515')           # 身份证号让给身份证


def test_random_18_digit_numbers_rarely_pass():
    import random
    rnd = random.Random(1)
    hits = sum(valid_uscc(''.join(rnd.choice('0123456789') for _ in range(18)))
               for _ in range(20000))
    # 纯数字的真实代码确实存在(如 914403001922038216),无法一刀切排除;
    # 结构 + 两级校验后误认率约 1/2000,且只在名单/人名都没命中时才用到
    assert hits <= 20


def test_find_usccs_boundaries():
    assert find_usccs(f'回执_{C1}_流水.pdf') == [C1]
    assert find_usccs(f'X{C1}') == []                    # 粘连更长字母数字串不算
    assert find_usccs('订单号123456789012345678') == []


def test_find_company_names():
    f = find_company_names
    assert f('关于华为技术有限公司的纳税情况.pdf') == ['华为技术有限公司']
    assert f('阿里巴巴（中国）有限公司开户信息') == ['阿里巴巴(中国)有限公司']
    assert f('反馈_某某科技(北京)有限公司上海分公司.docx') == \
        ['某某科技(北京)有限公司上海分公司']
    assert f('附件2-甲乙科技有限公司、丙丁贸易有限责任公司纳税明细.xlsx') == \
        ['甲乙科技有限公司', '丙丁贸易有限责任公司']
    assert f('某某服装厂_纳税.pdf') == ['某某服装厂']


def test_sender_banks_and_agencies_excluded():
    f = find_company_names
    # 银行/税务是反馈单位,不是被查询企业
    assert f('中国建设银行深圳分行_腾讯科技有限公司_流水.xlsx') == ['腾讯科技有限公司']
    assert f('国家税务总局深圳市税务局_回执.pdf') == []
    assert f('中国人寿保险股份有限公司_回函.pdf') == []
    assert f('公司章程.pdf') == [] and f('数据中心报告.pdf') == []
    assert f('甲乙科技有限公司_专案.pdf', exclude=['甲乙']) == []


def test_name_code_mapping_links_both_kinds_of_files():
    files = [('p', f'甲乙科技有限公司_{C1}_开户资料.pdf'),
             ('p', f'丙丁贸易有限公司{C2}.xlsx')]
    n2c, c2n = build_company_map(files)
    assert n2c == {'甲乙科技有限公司': C1, '丙丁贸易有限公司': C2}
    m = CompanyMatcher(n2c, c2n)
    assert m.match('甲乙科技有限公司_纳税申报表.pdf')[0] == f'甲乙科技有限公司_{C1}'
    assert m.match(f'{C1}_对公账户流水.xlsx')[0] == f'甲乙科技有限公司_{C1}'
    assert m.match('公司资料.pdf') is None
    assert m.match('某某有限公司_回执.pdf')[0] == '某某有限公司'       # 无代码时用名称
    assert m.match_content(f'纳税人识别号:{C2}')[0] == f'丙丁贸易有限公司_{C2}'


def test_roster_accepts_uscc():
    r = Roster.from_text(f'甲乙科技有限公司,{C1},甲乙科技\n张三')
    p = r.persons[0]
    assert p.ids == [C1] and p.aliases == ['甲乙科技']
    assert p.folder == f'甲乙科技有限公司_{C1}'
    assert r.match(f'{C1}_流水.xlsx') == [p]
    assert r.match('甲乙科技_纳税.pdf') == [p]


def test_roster_excel_company_headers(tmp_path):
    import pytest
    openpyxl = pytest.importorskip('openpyxl')
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(['序号', '纳税人名称', '统一社会信用代码', '备注'])
    ws.append([1, '甲乙科技有限公司', C1, '重点'])
    ws.append([2, '老字号商行', '440301123456789', ''])     # 老式 15 位税号
    p = tmp_path / '企业名单.xlsx'; wb.save(p)
    r = Roster.from_excel(str(p))
    assert [(x.name, x.ids) for x in r.persons] == [
        ('甲乙科技有限公司', [C1]), ('老字号商行', ['440301123456789'])]


def _run(opts):
    logs, result = [], {}
    run_job(opts, log=logs.append, progress=lambda *a: None,
            ask_password=lambda n, a: None, done_cb=result.update)
    return logs, result


def test_pipeline_groups_company_files_without_roster(tmp_path):
    src = tmp_path / 'in'; src.mkdir()
    with zipfile.ZipFile(src / '建设银行反馈.zip', 'w') as z:
        z.writestr(f'甲乙科技有限公司_{C1}_开户资料.pdf', 'a')
        z.writestr('丙丁贸易有限公司_对公流水.xlsx', 'b')
    with zipfile.ZipFile(src / '税务局反馈.zip', 'w') as z:
        z.writestr(f'{C1}_纳税申报.pdf', 'c')               # 只有代码
        z.writestr('甲乙科技有限公司_欠税情况.pdf', 'd')     # 只有名称
        z.writestr('回执.txt', f'纳税人:丙丁贸易有限公司 情况说明')   # 只有正文
        z.writestr('张三_说明.txt', 'e')
    out = tmp_path / 'out'
    _logs, r = _run(JobOptions([str(src)], str(out), Roster([]),
                               content_match=True, intelligent=False))
    folder = out / f'甲乙科技有限公司_{C1}'
    got = sorted(p.name for p in folder.rglob('*') if p.is_file())
    assert got == [f'{C1}_纳税申报.pdf', f'甲乙科技有限公司_{C1}_开户资料.pdf',
                   '甲乙科技有限公司_欠税情况.pdf']
    got2 = sorted(p.name for p in (out / '丙丁贸易有限公司').rglob('*') if p.is_file())
    assert got2 == ['丙丁贸易有限公司_对公流水.xlsx', '回执.txt']
    assert list((out / '未分类').rglob('张三_说明.txt'))
    # 反馈单位(银行/税务)不会被当成企业建文件夹
    assert not any('银行' in p.name or '税务' in p.name
                   for p in out.iterdir() if p.is_dir())


def test_pipeline_auto_company_can_be_disabled(tmp_path):
    src = tmp_path / 'in'; src.mkdir()
    with zipfile.ZipFile(src / 'a.zip', 'w') as z:
        z.writestr('甲乙科技有限公司_流水.pdf', 'a')
    out = tmp_path / 'out'
    _run(JobOptions([str(src)], str(out), Roster([]), auto_company=False,
                    intelligent=False))
    assert list((out / '未分类').rglob('甲乙科技有限公司_流水.pdf'))
