# -*- coding: utf-8 -*-
"""企业识别:统一社会信用代码(GB 32100-2015)校验 + 公司名称提取 + 名称↔代码关联。

典型场景:向银行/税务等单位批量查询企业账户、纳税信息,反馈文件名里有的写
公司名称、有的只写统一社会信用代码。这里把两者认出来并互相关联,
同一家企业的材料统一归入「公司名称_信用代码」文件夹。
"""

import re
import collections

from .util import safe_folder_name

# ---------- 统一社会信用代码 ----------
# 18 位:登记管理部门码(1) + 机构类别码(1) + 行政区划码(6) + 组织机构代码(9) + 校验码(1)
# 字符集不含 I O S V Z
_CHARS = '0123456789ABCDEFGHJKLMNPQRTUWXY'
_VAL = {c: i for i, c in enumerate(_CHARS)}
_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)
_C = '0-9A-HJ-NPQRTUWXY'
USCC_RE = re.compile(rf'(?<![0-9A-Za-z])([{_C}]{{2}}\d{{6}}[{_C}]{{10}})(?![0-9A-Za-z])',
                     re.IGNORECASE)


def uscc_check_char(code17: str) -> str:
    s = sum(_VAL[c] * w for c, w in zip(code17, _WEIGHTS))
    v = 31 - s % 31
    return _CHARS[0 if v == 31 else v]


# 登记管理部门码(第 1 位):1 机构编制 2 外交 3 司法行政 4 文化 5 民政 6 旅游
# 7 宗教 8 工会 9 市场监管(工商) A 军队 N 农业 Y 其他
# 第 2 位机构类别码,按登记管理部门分别规定(GB 32100-2015 附录)
_CATEGORY = {
    '1': '1239', '2': '19', '3': '123459', '4': '19', '5': '1239',
    '6': '129', '7': '129', '8': '19', '9': '123', 'A': '19', 'N': '1239',
    'Y': '1',
}
_DEPT = set(_CATEGORY)
_ORG_W = (3, 7, 9, 10, 5, 8, 4, 2)


def _org_code_ok(org9: str) -> bool:
    """第 9-17 位是组织机构代码(GB 11714),自带一位校验码。"""
    try:
        s = sum(int(c, 36) * w for c, w in zip(org9[:8], _ORG_W))
    except ValueError:
        return False
    v = 11 - s % 11
    return org9[8] == ('X' if v == 10 else '0' if v == 11 else str(v))


def valid_uscc(s: str) -> bool:
    """是否为通过校验的统一社会信用代码。

    三重校验:登记管理部门码合法 + 组织机构代码校验位 + 整体校验位,
    18 位订单号/流水号碰巧通过的概率约为万分之一以下。"""
    s = (s or '').strip().upper()
    if len(s) != 18 or not s[2:8].isdigit() or s[0] not in _DEPT:
        return False
    if s[1] not in _CATEGORY[s[0]]:
        return False
    # 第 3-8 位行政区划码:省级前缀,或国家级 100000
    from .idcard import _PROVINCES
    if s[2:4] not in _PROVINCES and s[2:8] != '100000':
        return False
    if any(c not in _VAL for c in s):
        return False
    if not _org_code_ok(s[8:17]):
        return False
    # 纯数字且恰好像身份证号的,让给身份证号(两种校验同时通过的概率极低)
    from .idcard import valid_id18
    if s.isdigit() and valid_id18(s):
        return False
    return s[17] == uscc_check_char(s[:17])


def find_usccs(text: str):
    """从文本中找出通过校验的统一社会信用代码(大写,去重,保持出现顺序)。"""
    out = []
    for m in USCC_RE.finditer(text or ''):
        v = m.group(1).upper()
        if valid_uscc(v) and v not in out:
            out.append(v)
    return out


# ---------- 公司名称 ----------
# 按长度从长到短排,先匹配完整后缀
_SUFFIXES = sorted("""
有限责任公司 股份有限公司 集团有限公司 集团股份有限公司 有限公司 分公司 子公司 公司
集团 合伙企业 普通合伙 有限合伙 特殊普通合伙 农民专业合作社 专业合作社 合作社 联合社
律师事务所 会计师事务所 税务师事务所 事务所 个体工商户 工作室 经营部 门市部 商行 商贸行
加工厂 制品厂 分厂 厂 营业部 办事处 分店 分部
专卖店 旗舰店 便利店 超市 商店 店 餐馆 饭馆 茶馆 照相馆 诊所 药房 大药房 美容院
批发部 经销部 服务部 维修部 销售部 门市 加工坊 作坊 车行 网吧
养殖场 农场 种植场 牧场 林场 渔场 果园 茶园
""".split(), key=len, reverse=True)
_SUFFIX_RE = re.compile('|'.join(map(re.escape, _SUFFIXES)))
_BRANCH_RE = re.compile(
    r'[\u4e00-\u9fa5()（）]{0,8}?(?:分公司|子公司|分厂|分店|营业部|办事处|分部)')
# 名称允许的字符:汉字 + 括号(如「华为技术(深圳)有限公司」)+ 少量字母数字
_RUN_RE = re.compile(r'[一-龥（）()A-Za-z0-9]+')
# 名称前面常粘着的无关词(文件名如「关于某某有限公司的纳税情况」)
_LEAD_NOISE = sorted("""
关于 有关 涉及 附件 查询 反馈 回复 回函 复函 答复 协查 协助 对 致 向 给 的
被查询人 被查询单位 查询对象 纳税人 企业 单位 名称 账户 开户 纳税 申报
""".split(), key=len, reverse=True)
# 这些是"反馈单位"(银行、税务、法院…)而不是被查询的企业,不作为归档对象
_SENDER_WORDS = (
    '银行', '信用社', '信用合作', '农商', '农信', '村镇银行', '证券', '保险',
    '税务', '公安', '法院', '检察', '财政', '人民政府', '管理局', '监督管理',
    '市场监管', '不动产登记', '公积金', '社会保险', '社保', '医保', '海关',
    '支付', '财付通', '清算',
    # 常见调取来源(数据提供方,不是被查企业)
    '铁路', '国铁', '人社', '人力资源', '卫健', '卫生', '自然资源', '国土',
    '出入境', '移民管理', '民航', '航空', '邮政', '电网', '供电',
    '市场监督', '住宿', '征信',
)


# 正式的企业/组织名称后缀(正文里出现即可信);店铺类名称需在文件名中出现过
_FORMAL_RE = re.compile(r'公司|合作社|联合社|合伙|事务所|个体工商户')


def known_names_from_files(files, exclude=()):
    names = set()
    for item in files:
        names.update(find_company_names(item[1], exclude))
    return names


def _norm(name: str) -> str:
    return name.replace('（', '(').replace('）', ')').strip()


def _strip_lead(s: str) -> str:
    changed = True
    while changed:
        changed = False
        s = s.lstrip('()（）0123456789')
        for w in _LEAD_NOISE:
            if s.startswith(w) and len(s) - len(w) >= 4:
                s = s[len(w):]
                changed = True
                break
    return s


def find_company_names(text: str, exclude=()):
    """从文本(文件名/正文)中提取公司名称,按出现顺序去重返回。"""
    out = []
    for run in _RUN_RE.findall(text or ''):
        # 一段文字里可能连着好几个名称,逐个切出(取到每个后缀的结尾)
        start = 0
        for m in _SUFFIX_RE.finditer(run):
            cand = run[start:m.end()]
            # 后面紧跟分支机构(如「…有限公司上海分公司」)时,合成一个完整名称
            if _BRANCH_RE.match(run, m.end()):
                continue
            cand = _norm(_strip_lead(cand))
            start = m.end()
            body = _SUFFIX_RE.sub('', cand)
            if len(re.sub(r'[()A-Za-z0-9]', '', body)) < 2:
                continue          # 只有"公司"、"总公司"这类,不是名称
            if any(w in cand for w in _SENDER_WORDS):
                continue
            if any(w and w in cand for w in exclude):
                continue
            if cand not in out:
                out.append(cand)
    return out


# ---------- 名称 ↔ 代码 关联 ----------

def build_company_map(files, exclude=(), log=None):
    """扫描全部文件名,"名称 + 代码"同时出现的文件是二者对应的证据。
    返回 (name→code, code→name)。"""
    pair = collections.Counter()
    for item in files:
        fname = item[1]
        names = find_company_names(fname, exclude)
        codes = find_usccs(fname)
        if not names or not codes or len(names) > 2:
            continue
        w = 3 if (len(names) == 1 and len(codes) == 1) else 1
        for n in names:
            for c in codes:
                pair[(n, c)] += w
    n2c, c2n = {}, {}
    for (n, c), _cnt in pair.most_common():
        if n in n2c or c in c2n:
            continue
        n2c[n] = c
        c2n[c] = n
    if log and n2c:
        log(f'[企业识别] 从文件名推测出 {len(n2c)} 组公司名称↔统一社会信用代码对应关系:')
        for n, c in sorted(n2c.items())[:50]:
            log(f'  {n} ↔ {c}')
    return n2c, c2n


class CompanyMatcher:
    """未命中名单的文件:按公司名称 / 统一社会信用代码归档。"""

    def __init__(self, name_to_code=None, code_to_name=None, exclude=(),
                 known_names=None):
        self.n2c = dict(name_to_code or {})
        self.c2n = dict(code_to_name or {})
        self.exclude = tuple(exclude or ())
        # 在某个文件名里出现过的名称(正文里只认这些 + 正式企业名称,
        # 避免把流水里的交易对手"XX便利店"当成归属对象)
        self.known = set(known_names or ()) | set(self.n2c)

    def _folder(self, name, code):
        if name and code:
            return safe_folder_name(f'{name}_{code}')
        return safe_folder_name(name or code)

    def match(self, fname: str):
        """返回 (文件夹, 依据) 或 None。代码优先(唯一、无歧义)。"""
        codes = find_usccs(fname)
        names = find_company_names(fname, self.exclude)
        for c in codes:
            n = self.c2n.get(c)
            if not n and len(names) == 1:
                n = names[0]
            return self._folder(n, c), '企业(信用代码)'
        for n in names:
            return self._folder(n, self.n2c.get(n)), '企业(名称)'
        return None

    def match_content(self, text: str):
        """文件名没线索时看正文:先找信用代码,再找出现最多的公司名称。"""
        if not text:
            return None
        codes = find_usccs(text)
        if codes:
            c = codes[0]
            return self._folder(self.c2n.get(c), c), '企业(内容信用代码)'
        counts = collections.Counter()
        for n in find_company_names(text, self.exclude):
            if n not in self.known and not _FORMAL_RE.search(n):
                continue
            counts[n] = text.count(n) or 1
        if counts:
            n = counts.most_common(1)[0][0]
            return self._folder(n, self.n2c.get(n)), '企业(内容名称)'
        return None
