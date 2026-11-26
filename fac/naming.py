# -*- coding: utf-8 -*-
"""文件名精简(可选,默认开启)。

查询反馈的文件名往往很长,有用的信息被挤到最后看不见,例如:
    【某某查【2026】第123456号_2026年11月11日】张三_230303197511020123_某某查【2026】第123456号_保险信息.xlsx
    【202600010001查询结果】国土资源厅信息-张三-230303197511020123e1dhshrush23whdu.xlsx
精简为「信息/来源在前,姓名_证号在后」(证号保留,防重名):
    保险信息_张三_230303197511020123.xlsx
    国土资源厅信息_张三_230303197511020123.xlsx

只去掉明确的"噪音":开头的【…】整块、文号(某某查【2026】第123456号)、
证号后面粘着的乱码;不认识的部分原样保留。原名记在归档记录里,
另生成《文件名对照表》可随时查回原名。是否"导入过"按原名判断,
所以开关这个功能都不会造成重复导入。
"""

import os
import re

from .util import safe_folder_name

# 开头的【…】整块(块内可再套一层【2026】)
_LEAD = re.compile(r'^\s*【(?:[^【】]|【[^【】]*】)*】')
# 文号:某某查【2026】第123456号 / 〔2026〕 / [2026] / (2026)
_DOCNO = re.compile(r'[一-龥A-Za-z]{0,12}[【〔\[(（]\s*\d{4}\s*[】〕\])）]'
                    r'\s*第?\s*\d+\s*号')
# 证号后面粘着的随机串(字母数字混合 ≥6 位)
_ID_TAIL = re.compile(r'(?<![0-9A-Za-z])(\d{17}[\dXx]|[0-9A-HJ-NPQRTUWXY]{18})'
                      r'([A-Za-z0-9]{6,})(?![0-9A-Za-z])')
_SEP = re.compile(r'[_\-—–\s·]+')
_DATE_CN = re.compile(r'(\d{4})年(\d{1,2})月(\d{1,2})日')
_DATE_NUM = re.compile(r'(?<!\d)(20\d{2})[-./]?(\d{2})[-./]?(\d{2})(?!\d)')
# 单位名里只剩这些词时,视为没有信息量
_GENERIC_UNIT = {'', '查询结果', '查询', '结果', '反馈', '反馈结果', '回复', '回执',
                 '数据', '信息', '材料', '资料', '附件', '文件', '批次'}


def _date_token(text):
    m = _DATE_CN.search(text or '')
    if m:
        return f'{m.group(1)}{int(m.group(2)):02d}{int(m.group(3)):02d}'
    m = _DATE_NUM.search(text or '')
    if m:
        return f'{m.group(1)}{m.group(2)}{m.group(3)}'
    return ''


def _strip_noise(text):
    """去掉开头【…】块、文号、证号后乱码。返回 (精简后文本, 被去掉部分里的日期)。"""
    removed = []
    m = _LEAD.match(text)
    if m:
        removed.append(m.group(0))
        text = text[m.end():]
    removed.extend(x.group(0) for x in _DOCNO.finditer(text))
    text = _DOCNO.sub('', text)
    text = _ID_TAIL.sub(lambda x: x.group(1), text)
    return text, _date_token(' '.join(removed))


def shorten_unit(unit):
    """来源单位(压缩包名)精简:去文号/【…】块/长串批次号/日期;
    只剩"查询结果"之类没信息量的词时返回空串(文件名就不加单位前缀)。"""
    s, _d = _strip_noise(unit or '')
    s = re.sub(r'【[^【】]*】', ' ', s)
    s = _DATE_CN.sub(' ', s)
    s = re.sub(r'\d{8,}', ' ', s)            # 202600010001 这类批次号
    s = _SEP.sub('_', s).strip('_ ')
    return '' if s in _GENERIC_UNIT else s


def _remove_token(text, tok):
    if not tok:
        return text
    return text.replace(tok, ' ').replace(tok.lower(), ' ')


def shorten_name(fname, who_name='', who_code='', extra_tokens=()):
    """精简单个文件名(不含单位前缀)。返回 (新文件名, 日期标记)。

    who_name / who_code:此文件归属的人员/企业名称与证号(取自目标文件夹)。
    extra_tokens:要一并去掉的其他写法(如 15 位老证号、曾用名不去,保留)。"""
    stem, ext = os.path.splitext(fname)
    text, date = _strip_noise(stem)
    if who_name or who_code:
        for tok in [who_code, *extra_tokens, who_name]:
            text = _remove_token(text, tok)
    info = _SEP.sub('_', text).strip('_ ')
    if who_name or who_code:
        parts = [p for p in (info, who_name, who_code) if p]
    else:
        parts = [info] if info else []
    new = '_'.join(parts) or stem
    return safe_folder_name(new) + ext, date


def with_date(fname, date):
    stem, ext = os.path.splitext(fname)
    return f'{stem}_{date}{ext}' if date else fname
