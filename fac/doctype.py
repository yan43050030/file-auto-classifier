# -*- coding: utf-8 -*-
"""人员/企业文件夹内的资料类型细分:银行流水 / 其他数据(疑似空值另由 emptyfile 判定)。

「银行流水」文件夹放 银行/支付机构 的全部反馈(交易流水、账户信息、开户资料…),
包括人民银行账户信息;其余来源(人社、卫健、国土、社保、不动产、出生医学证明、保险、
出入境、旅馆住宿、人口户籍、铁路票面/同行人等)放「其他数据」。

判定顺序:
1. 文件名提到银行/支付机构(工商银行、农行、人民银行、支付宝…)→ 银行
2. 文件名提到上述非银行来源                                → 其他
3. 文件名含"流水/交易明细/对账单…"                         → 银行
4. 同样的规则再看来源单位(压缩包名)
5. 都看不出时看内容:表头像流水(交易日期 + 金额/借贷 + 余额/对方户名…),
   或有账号/卡号/开户行等账户列                               → 银行
"""

import os
import re

from .util import long_path, read_text_any_encoding

CAT_FLOW = '银行流水'
CAT_OTHER = '其他数据'
CATEGORIES = (CAT_FLOW, CAT_OTHER)

_FLOW_NAME = re.compile(
    r'流水|交易明细|账户明细|帐户明细|交易记录|对账单|明细账|资金明细|收支明细|'
    r'交易清单|明细查询|交易查询|账户交易|帐户交易|资金往来|往来明细')
_DATE_COLS = ('交易日期', '交易时间', '记账日期', '入账日期', '交易日', '发生日期')
_AMT_COLS = ('交易金额', '发生额', '借方', '贷方', '借贷', '收入', '支出',
             '收入金额', '支出金额', '收付', '入账金额', '出账金额')
_OTHER_COLS = ('余额', '账户余额', '对方户名', '对方账号', '对方账户', '交易对手',
               '对手户名', '对手账号', '摘要', '交易摘要', '用途', '交易类型',
               '交易渠道', '交易网点', '币种')
_MAX_CONTENT_BYTES = 50 * 1024 * 1024     # 超大文件不读内容,只看文件名


def _looks_like_flow_text(text):
    d = any(c in text for c in _DATE_COLS)
    a = sum(1 for c in _AMT_COLS if c in text)
    o = sum(1 for c in _OTHER_COLS if c in text)
    return d and a >= 1 and (1 + a + o) >= 3


def _head_text_table(path):
    low = path.lower()
    parts = []
    if low.endswith(('.xlsx', '.xlsm')):
        import openpyxl
        wb = openpyxl.load_workbook(long_path(path), read_only=True, data_only=True)
        try:
            for ws in wb.worksheets[:3]:
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i >= 20:
                        break
                    parts.extend(str(c) for c in row if c is not None)
        finally:
            wb.close()
    elif low.endswith('.xls'):
        import xlrd
        wb = xlrd.open_workbook(long_path(path), on_demand=True)
        for sh in wb.sheets()[:3]:
            for r in range(min(sh.nrows, 20)):
                parts.extend(str(v) for v in sh.row_values(r))
    elif low.endswith('.csv'):
        txt = read_text_any_encoding(path) or ''
        parts.append('\n'.join(txt.splitlines()[:20]))
    return ' '.join(parts)


# ---------- 银行类 / 非银行类 来源 ----------
# 银行与支付机构(含不会撞车的简称;平安/民生/中信等在公安、政务文件里也常见,不收)
_BANK_NAME = re.compile(
    r'银行|人行|征信|信用社|信用合作|农商行|农村商业|农信社|村镇银行|邮储|'
    r'[工建农交招]行|浦发|支付宝|财付通|微信支付|网商|银联|云闪付|京东支付|'
    r'快钱|拉卡拉|易宝|支付机构')
# 人民银行(账户信息汇总)、人民银行征信中心(征信报告):归入银行流水,但从不判为疑似空值
_PBOC = re.compile(r'人民银行|人行|征信')
# 常见非银行来源(调取清单):人社厅个人基本信息、卫健委全员人口、国土自然资源、
# 社保、不动产、出生医学证明、保险、出入境记录/证件、旅馆住宿、人口和户籍、
# 铁路票面/同行人、税务缴纳、增值税专用发票、自然资源部 ……
# 这些数据本来就小,也常含"个人账户/银行账号/购方开户行及账号"等字样,
# 一律不算银行类
_NON_BANK = re.compile(
    r'人社|人力资源|社会保障|社保|社会保险|医保|医疗保险|养老|失业|工伤|'
    r'卫健|卫生|健康委|全员人口|人口|户籍|户口|身份证|'
    r'国土|自然资源|不动产|房产|房屋|土地|'
    r'出生医学|出生证|保险|寿险|财险|'
    r'出入境|护照|港澳|通行证|旅馆|住宿|酒店|'
    r'铁路|火车|票面|同行人|航空|民航|'
    r'车管|机动车|驾驶|车辆|公积金|税务|纳税|缴税|完税|税收|增值税|发票|'
    r'工商登记|市场监管|市场监督|企业基本信息|纳税人|婚姻|殡葬|'
    r'公安|派出所|看守所|监狱|法院|检察')
# 表头里的账户类列(查无账户时银行常回一张只有这些表头的表)
_ACCOUNT_COLS = ('账号', '帐号', '卡号', '开户行', '开户网点', '开户机构',
                 '开户日期', '销户日期', '账户状态', '帐户状态')


def _source_says(text):
    """'bank' / 'other' / None:按文件名或来源单位名判断。"""
    if not text:
        return None
    if _BANK_NAME.search(text):
        return 'bank'
    if _NON_BANK.search(text):
        return 'other'
    if _FLOW_NAME.search(text):
        return 'bank'
    return None


# 银行反馈里"不是交易流水"的资料:开户信息、账户信息、理财、基金、保险、贷款、
# 信用卡资料、存款证明、签约信息、客户 / 基本信息、资产 …… 这些本来就小,不能当疑似空值
_NOT_FLOW_NAME = re.compile(
    r'开户|账户信息|帐户信息|账户资料|帐户资料|客户信息|客户资料|基本信息|理财|基金|'
    r'保险|贷款|借款|信用卡申请|存款证明|资信|签约|绑定|销户|挂失|冻结|查封|资产|'
    r'持仓|证券|期货|保管箱|印鉴|预留|联系方式|手机号')


# 银行名称(全称、分支机构、简称、支付机构),用于判断"文件名里是不是只写了银行名"
_BANK_FULL = re.compile(
    r'(中国)?[\u4e00-\u9fa5]{0,12}?(银行|信用社|信用合作联社|农商行|农村商业银行|村镇银行)'
    r'(股份有限公司|有限责任公司|有限公司)?'
    r'([\u4e00-\u9fa5]{0,10}?(分行|支行|营业部|分理处|网点|中心))*'
    r'|[工建农交招]行|中行|浦发|邮储|支付宝|财付通|微信支付|网商|银联|云闪付|京东支付')
_GENERIC = re.compile(
    r'查询结果|查询反馈|协查结果|协查|查询|结果|反馈|回复|回执|回函|复函|答复|数据|材料|资料|'
    r'附件|文件|批次|第[一二三四五六七八九十\d]+批|情况|说明|名单|汇总|导出|新|补充|更新')
_DOCNO = re.compile(r'[\u4e00-\u9fa5A-Za-z]{0,12}[【〔\[(（]\s*\d{4}\s*[】〕\])）]\s*第?\s*\d+\s*号')


def _only_bank_name(stem, unit='', keywords=()):
    """文件名去掉银行名、人名 / 证号、文号、日期、"查询结果"这类通用词后,还剩不剩说明文字。
    一般只写「工商银行」「张三_建设银行」的,实际就是交易流水。"""
    s = re.sub(r'【[^】]*】', ' ', stem)
    s = _DOCNO.sub(' ', s)
    for k in sorted((k for k in keywords if k), key=len, reverse=True):
        s = s.replace(k, ' ')
    s = _BANK_FULL.sub(' ', s)
    s = re.sub(r'\d{4}年\d{1,2}月(\d{1,2}日)?', ' ', s)
    s = _GENERIC.sub(' ', s)
    s = re.sub(r'[^\u4e00-\u9fa5]', '', s)           # 数字、字母、符号都不算说明
    # 剩下 ≤3 个汉字多半是没在名单里的人名;再多就是有别的说明(如"余额证明")
    return len(s) <= 3


def is_bank_flow(path, fname=None, unit='', keywords=()):
    """是不是"交易流水"类文件(疑似空值只对这类判定)。

    1. 文件名写着 流水 / 交易明细 / 对账单 → 是;
    2. 文件名写明开户信息 / 理财 / 基金 / 保险 / 贷款…… → 不是;
    3. 文件名只写了银行名(加人名、证号、文号、"查询结果"之类)、没有别的说明 → 是
       (实际中只写「工商银行」「建设银行」的反馈,大多就是交易流水);
    4. 都看不出时看表头:有交易日期 + 交易金额 / 借贷这类流水列的是(只有表头的也算)。"""
    fname = fname or os.path.basename(path)
    stem = os.path.splitext(fname)[0]
    if _FLOW_NAME.search(stem):
        return True
    if _NOT_FLOW_NAME.search(stem):
        return False
    if _only_bank_name(stem, unit, keywords):
        return True
    low = path.lower()
    try:
        if low.endswith(('.xlsx', '.xlsm', '.xls', '.csv')):
            return _looks_like_flow_text(_head_text_table(path))
        if low.endswith(('.pdf', '.docx', '.doc', '.txt')):
            from .content_match import extract_text
            text = extract_text(path, max_chars=4000) or ''
            # 回函写明"未查询到交易流水 / 无交易明细"之类,也算流水查询的回复
            return _looks_like_flow_text(text) or bool(_FLOW_NAME.search(text))
    except Exception:
        pass
    return False


def is_pboc(fname='', unit=''):
    return bool(_PBOC.search(fname or '') or _PBOC.search(unit or ''))


def is_bank_related(path, fname=None, unit=''):
    """是否银行/支付类反馈。

    先看文件名,再看来源单位(压缩包名):提到银行/支付机构 → 是;
    提到人社/卫健/不动产/出入境/铁路等非银行来源 → 否;
    都看不出时再看内容:表头像流水(交易日期+金额+余额…)或有账号/卡号/开户行列 → 是。"""
    fname = fname or os.path.basename(path)
    stem = os.path.splitext(fname)[0]
    for text in (stem, unit):
        v = _source_says(text)
        if v:
            return v == 'bank'
    low = path.lower()
    try:
        if os.path.getsize(long_path(path)) > _MAX_CONTENT_BYTES:
            return False
        if low.endswith(('.xlsx', '.xlsm', '.xls', '.csv')):
            head = _head_text_table(path)
            if _looks_like_flow_text(head):
                return True
            return any(c in head for c in _ACCOUNT_COLS)
        if low.endswith(('.pdf', '.docx', '.doc', '.txt')):
            from .content_match import extract_text
            return _looks_like_flow_text(extract_text(path, max_chars=4000) or '')
    except Exception:
        pass
    return False


def detect_category(path, fname=None, unit=''):
    """返回 '银行流水'(银行/支付机构的全部反馈:账户信息、交易流水等)或 '其他数据'。"""
    return CAT_FLOW if is_bank_related(path, fname, unit) else CAT_OTHER
