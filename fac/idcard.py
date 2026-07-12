# -*- coding: utf-8 -*-
"""身份证号识别与校验(GB 11643)。

18 位:前 17 位加权求和模 11 查表得校验位;
15 位:老式号码,校验省份码与出生日期的合理性。
"""

import re

_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_CHECK = '10X98765432'

# 有效省级行政区代码前两位
_PROVINCES = {
    '11', '12', '13', '14', '15', '21', '22', '23',
    '31', '32', '33', '34', '35', '36', '37',
    '41', '42', '43', '44', '45', '46',
    '50', '51', '52', '53', '54',
    '61', '62', '63', '64', '65', '71', '81', '82',
}

ID18_RE = re.compile(r'(?<![0-9Xx])(\d{17}[\dXx])(?![0-9Xx])')
ID15_RE = re.compile(r'(?<!\d)(\d{15})(?!\d)')


def check_digit(digits17: str) -> str:
    """由前 17 位计算校验位。"""
    s = sum(int(d) * w for d, w in zip(digits17, _WEIGHTS))
    return _CHECK[s % 11]


def _plausible_date(yyyymmdd: str) -> bool:
    y, m, d = int(yyyymmdd[:4]), int(yyyymmdd[4:6]), int(yyyymmdd[6:8])
    return 1900 <= y <= 2099 and 1 <= m <= 12 and 1 <= d <= 31


def valid_id18(s: str) -> bool:
    if len(s) != 18 or not s[:17].isdigit():
        return False
    if s[:2] not in _PROVINCES or not _plausible_date(s[6:14]):
        return False
    return s[17].upper() == check_digit(s[:17])


def valid_id15(s: str) -> bool:
    if len(s) != 15 or not s.isdigit():
        return False
    return s[:2] in _PROVINCES and _plausible_date('19' + s[6:12])


def id15_to_18(s: str) -> str:
    """15 位老号码升位为 18 位(出生年补 19,加校验位)。"""
    d17 = s[:6] + '19' + s[6:]
    return d17 + check_digit(d17)


def find_ids(text: str):
    """从文本中找出通过校验的身份证号(18 位原样返回,15 位也原样返回)。"""
    found = []
    for m in ID18_RE.finditer(text):
        v = m.group(1)
        if valid_id18(v) and v.upper() not in found:
            found.append(v.upper())
    for m in ID15_RE.finditer(text):
        v = m.group(1)
        if valid_id15(v) and v not in found:
            # 避免把 18 位号的子串当成 15 位号:上面的负向断言已保证边界
            found.append(v)
    return found
