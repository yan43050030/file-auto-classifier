# -*- coding: utf-8 -*-
# 本文件由 scripts/sync_flowcore.py 从 Case Intel 同步生成,请勿手改;
# 需要改识别规则请改 Case Intel 再同步。
"""银行名称归一(摘自 Case Intel branch_lib.canonical_bank,不含数据库部分)。"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional

_BANKS = [
    ("工商银行", ("工商银行", "工行", "ICBC")),
    ("建设银行", ("建设银行", "建行", "CCB")),
    ("农业银行", ("农业银行", "农行", "ABC")),
    ("邮储银行", ("邮政储蓄", "邮储", "PSBC")),
    ("光大银行", ("光大银行",)),
    ("民生银行", ("民生银行",)),
    ("交通银行", ("交通银行", "交行", "BOCOM")),
    ("招商银行", ("招商银行", "招行", "CMB")),
    ("浦发银行", ("浦东发展银行", "浦发")),
    ("中信银行", ("中信银行",)),
    ("兴业银行", ("兴业银行",)),
    ("华夏银行", ("华夏银行",)),
    ("广发银行", ("广发银行", "广东发展银行")),
    ("平安银行", ("平安银行",)),
    ("浙商银行", ("浙商银行",)),
    ("渤海银行", ("渤海银行",)),
    ("恒丰银行", ("恒丰银行",)),
    ("中国银行", ("中国银行", "中行", "BOC")),      # 放最后：别把"中国工商银行"认成它
]
_LOCAL_BANK = re.compile(r"([一-龥]{2,20}?(?:农村商业银行|农村合作银行|农商银行|农商行|"
                         r"信用合作联社|农村信用社|信用社|村镇银行|商业银行|银行))")


def canonical_bank(text: Optional[str]) -> Optional[str]:
    t = unicodedata.normalize("NFKC", str(text or "")).replace(" ", "")
    if not t:
        return None
    up = t.upper()
    for name, keys in _BANKS:
        for k in keys:
            if (k.isascii() and re.search(rf"(?<![A-Z]){k}(?![A-Z])", up)) or (not k.isascii() and k in t):
                return name
    m = _LOCAL_BANK.search(t)
    if m:
        return re.sub(r"(股份有限公司|有限责任公司|有限公司)$", "", m.group(1))
    return None
