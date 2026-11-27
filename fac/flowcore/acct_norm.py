# -*- coding: utf-8 -*-
# 本文件由 scripts/sync_flowcore.py 从 Case Intel 同步生成,请勿手改;
# 需要改识别规则请改 Case Intel 再同步。
# -*- coding: utf-8 -*-
"""账号归一（全系统唯一来源）。

查控平台 / 部分银行反馈的账号后面会挂币种、钞汇标志："6222021234567890123_156"、"…-156-1"、"…_CNY"。
交易对方那一侧写的却是光秃秃的账号 —— 不去掉后缀，本人账户之间的互转、追踪、内部往来全都对不上。

只去掉"分隔符 + 币种代码（+ 钞汇标志）"这种确定的写法；没有分隔符的（"…123156"）不动，
那种由「账户核对」按前后缀相近给出候选，人确认后记成别名（account_aliases）。
"""
from __future__ import annotations

import re
import unicodedata

# 币种代码：数字（ISO 4217）或字母；后面可再跟钞汇标志
_CUR = {"156": "CNY", "CNY": "CNY", "RMB": "CNY",
        "840": "USD", "USD": "USD", "978": "EUR", "EUR": "EUR", "344": "HKD", "HKD": "HKD",
        "392": "JPY", "JPY": "JPY", "826": "GBP", "GBP": "GBP", "036": "AUD", "AUD": "AUD",
        "124": "CAD", "CAD": "CAD", "702": "SGD", "SGD": "SGD", "756": "CHF", "CHF": "CHF",
        "446": "MOP", "MOP": "MOP"}
_SUFFIX = re.compile(r"^(?P<base>.*?[0-9A-Za-z*]{6,})\s*[_\-/#.·|\s]\s*(?P<cur>156|CNY|RMB|840|USD|978|EUR|344|HKD|392|JPY|"
                     r"826|GBP|036|AUD|124|CAD|702|SGD|756|CHF|446|MOP)"
                     r"(?:\s*[_\-/#.·|\s]\s*(?:0|1|2|钞|汇|现钞|现汇|钞户|汇户))?\s*$", re.I)


def split_suffix(s: str) -> tuple[str, str]:
    """"6222…_156_1" → ("6222…", "CNY")；没有币种后缀 → (原样, "")。"""
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    m = _SUFFIX.match(t)
    if not m:
        return t, ""
    return m.group("base"), _CUR[m.group("cur").upper()]


def norm_acct(s: str) -> str:
    """账号归一：去掉人民币后缀（外币后缀保留，免得和人民币户混成一个）、空格横杠，只留字母数字和打码星号。"""
    base, cur = split_suffix(s)
    t = base if cur == "CNY" else unicodedata.normalize("NFKC", str(s or ""))
    return re.sub(r"[^0-9A-Za-z*]", "", t).upper()
