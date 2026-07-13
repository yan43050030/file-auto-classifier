# -*- coding: utf-8 -*-
"""高级分类规则:按文件类型/大小/时间/自定义字符/正则表达式 匹配文件到指定文件夹。

规则在名单匹配之后、身份证号识别之前执行(名单最高优先级)。
"""

import os
import re

from .util import safe_folder_name


class Rule:
    __slots__ = ('rule_type', 'value', 'target', 'enabled')

    def __init__(self, rule_type: str, value: str, target: str, enabled: bool = True):
        self.rule_type = rule_type   # ext|size_gt|size_lt|date_before|date_after|contains|regex
        self.value = value.strip()
        self.target = target.strip()
        self.enabled = enabled

    def match(self, filepath: str, fname: str, st_size: int, st_mtime: float) -> bool:
        """检测该规则是否匹配给定文件。"""
        if not self.enabled or not self.value:
            return False
        try:
            if self.rule_type == 'ext':
                # .pdf 或 pdf 都行
                v = self.value.strip('.').lower()
                return fname.lower().endswith('.' + v)
            if self.rule_type == 'size_gt':
                return st_size > _parse_size(self.value)
            if self.rule_type == 'size_lt':
                return st_size < _parse_size(self.value)
            if self.rule_type == 'date_before':
                ts = _parse_date(self.value)
                return ts is not None and st_mtime < ts
            if self.rule_type == 'date_after':
                ts = _parse_date(self.value)
                return ts is not None and st_mtime > ts
            if self.rule_type == 'contains':
                return self.value.lower() in fname.lower()
            if self.rule_type == 'regex':
                return bool(re.search(self.value, fname, re.I))
        except Exception:
            return False
        return False

    def folder(self) -> str:
        return safe_folder_name(self.target) if self.target else '未命名规则'

    def to_dict(self):
        return {'rule_type': self.rule_type, 'value': self.value,
                'target': self.target, 'enabled': self.enabled}

    @classmethod
    def from_dict(cls, d: dict):
        return cls(d.get('rule_type', ''), d.get('value', ''),
                   d.get('target', ''), bool(d.get('enabled', True)))

    def __repr__(self):
        return f'Rule({self.rule_type}:{self.value}->{self.target})'


def match_rules(filepath: str, rules: list):
    """用规则列表依次匹配一个文件,返回命中的第一个 Rule。未命中返回 None。"""
    fname = os.path.basename(filepath)
    try:
        st = os.stat(filepath)
    except OSError:
        return None
    for r in rules:
        if r.match(filepath, fname, st.st_size, st.st_mtime):
            return r
    return None


# ---------- 解析辅助 ----------

_SIZE_UNITS = {'B': 1, 'KB': 1024, 'MB': 1024 ** 2, 'GB': 1024 ** 3,
               'K': 1024, 'M': 1024 ** 2, 'G': 1024 ** 3}


def _parse_size(s: str) -> int:
    s = s.strip().upper().replace(' ', '')
    if not s:
        return 0
    m = re.match(r'^(\d+(?:\.\d+)?)\s*(B|KB|MB|GB|K|M|G)?$', s)
    if m:
        return int(float(m.group(1)) * _SIZE_UNITS.get(m.group(2) or 'B', 1))
    return int(float(s))


def _parse_date(s: str):
    """解析日期字符串为 Unix 时间戳。支持 YYYY-MM-DD / YYYYMMDD / YYYY / 中文年-月-日。"""
    s = s.strip()
    if not s:
        return None
    for fmt, pattern in [
        ('%Y-%m-%d', r'^\d{4}-\d{2}-\d{2}$'),
        ('%Y%m%d', r'^\d{8}$'),
        ('%Y', r'^\d{4}$'),
    ]:
        if re.match(pattern, s):
            try:
                import time_cal as _tc
            except Exception:
                pass
            import time
            try:
                st = time.strptime(s, fmt)
            except Exception:
                continue
            import calendar
            return calendar.timegm(st)
    # 中文格式:2024年1月1日
    cn = re.match(r'^(\d{4})年(\d{1,2})月(\d{1,2})日$', s)
    if cn:
        import calendar
        import datetime
        try:
            dt = datetime.datetime(int(cn.group(1)), int(cn.group(2)),
                                   int(cn.group(3)))
            return dt.timestamp()
        except Exception:
            pass
    return None
