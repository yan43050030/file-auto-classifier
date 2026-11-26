# -*- coding: utf-8 -*-
"""人员名单:一个人可以有姓名 + 身份证号 + 若干曾用名/别名,任一命中都归同一文件夹。

文本格式(每行一个人,分隔符支持 中英文逗号/分号/制表符/空格):
    张三
    李四,110101199001011234
    王五,110101199001011234,王小五,老王

普通关键字(公司名等)直接写一行即可,等价于只有"姓名"的人员。
企业可写「公司名称,统一社会信用代码」,名称或代码任一命中都归入「名称_代码」文件夹:
    某某科技有限公司,91110108MA01AB2C3T
"""

import re

from .util import safe_folder_name
from .idcard import valid_id15, valid_id18, id15_to_18
from .company import valid_uscc

_SEP_RE = re.compile(r'[,，;；\t]|\s+')


class Person:
    __slots__ = ('name', 'ids', 'aliases', 'folder')

    def __init__(self, name, ids=None, aliases=None):
        self.name = str(name).strip()
        self.ids = [str(i).strip().upper() for i in (ids or []) if str(i).strip()]
        self.aliases = [str(a).strip() for a in (aliases or []) if str(a).strip()]
        self.folder = safe_folder_name(self.name)

    def keywords(self):
        """该人员的全部匹配关键字(含 15/18 位证号互转形式)。"""
        kws = [self.name] + self.aliases + list(self.ids)
        for i in self.ids:
            if valid_id15(i):
                v = id15_to_18(i)
                if v not in kws:
                    kws.append(v)
        return [k for k in kws if k]

    def __repr__(self):
        return f'Person({self.name})'


class Roster:
    def __init__(self, persons=None):
        self.persons = list(persons or [])
        self._rebuild()

    def _rebuild(self):
        # 有身份证号的人员:文件夹名=姓名_完整证号,便于搜索和二次分类
        for p in self.persons:
            if p.ids:
                p.folder = safe_folder_name(f'{p.name}_{p.ids[0]}')
        # 同名且无身份证号的人员用序号区分,避免混档
        name_counts = {}
        for p in self.persons:
            if not p.ids:
                name_counts[p.name] = name_counts.get(p.name, 0) + 1
        for name, cnt in name_counts.items():
            if cnt > 1:
                idx = 1
                for p in self.persons:
                    if p.name == name and not p.ids:
                        p.folder = safe_folder_name(f'{name}_{idx}')
                        idx += 1
        # 匹配索引:按关键字长度降序(最长匹配优先)
        self._index = []
        for p in self.persons:
            for kw in p.keywords():
                self._index.append((kw, p))
        self._index.sort(key=lambda x: -len(x[0]))

    def __len__(self):
        return len(self.persons)

    def match(self, text: str):
        """返回命中的人员列表,最长关键字优先。
        被更长关键字完全覆盖的短命中会被抑制(如"张三丰"命中时不再算"张三")。"""
        if not text:
            return []
        hits = []  # (start, end, person)
        for kw, p in self._index:
            start = 0
            while True:
                i = text.find(kw, start)
                if i < 0:
                    break
                hits.append((i, i + len(kw), p))
                start = i + 1
        kept = []
        for h in hits:
            covered = any(
                o[2] is not h[2] and o[0] <= h[0] and h[1] <= o[1]
                and (o[1] - o[0]) > (h[1] - h[0])
                for o in hits)
            if not covered:
                kept.append(h)
        persons = []
        for _s, _e, p in sorted(kept, key=lambda x: (-(x[1] - x[0]), x[0])):
            if p not in persons:
                persons.append(p)
        return persons

    # ---------- 解析 ----------

    @staticmethod
    def _looks_like_id(tok: str) -> bool:
        """身份证号(18/15 位)或统一社会信用代码。"""
        t = tok.strip().upper()
        return valid_id18(t) or valid_id15(t) or valid_uscc(t)

    @classmethod
    def from_text(cls, text: str):
        """从文本解析名单。每行一个人:姓名[,身份证号][,曾用名…];# 开头为注释。"""
        persons = []
        for line in (text or '').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            toks = [t for t in _SEP_RE.split(line) if t]
            if not toks:
                continue
            name, ids, aliases = toks[0], [], []
            for t in toks[1:]:
                if cls._looks_like_id(t):
                    ids.append(t)
                else:
                    aliases.append(t)
            persons.append(Person(name, ids, aliases))
        return cls(persons)

    @classmethod
    def from_excel(cls, path: str):
        """从 Excel 导入名单。识别表头(姓名/身份证/曾用名),无表头时按
        第1列=姓名、第2列=证号、其余=别名处理。"""
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = [[('' if c is None else str(c).strip()) for c in r]
                for r in ws.iter_rows(values_only=True)]
        wb.close()
        rows = [r for r in rows if any(r)]
        if not rows:
            return cls([])

        header = rows[0]
        name_col = id_col = None
        alias_cols = []
        for i, h in enumerate(header):
            if name_col is None and any(
                    k in h for k in ('姓名', '名字', '人员', 'name', 'Name',
                                     '企业名称', '公司名称', '单位名称',
                                     '纳税人名称', '名称', '户名')):
                name_col = i
            elif any(k in h for k in ('身份证', '证件', '证号', '信用代码',
                                      '纳税人识别号', '税号', '注册号')):
                id_col = i
            elif any(k in h for k in ('曾用名', '别名', '其他名', 'alias')):
                alias_cols.append(i)
        has_header = name_col is not None
        if not has_header:
            name_col = 0
        data = rows[1:] if has_header else rows

        persons = []
        for r in data:
            if name_col >= len(r) or not r[name_col]:
                continue
            name = r[name_col]
            ids, aliases = [], []
            for c in range(len(r)):
                if c == name_col or not r[c]:
                    continue
                # 有表头时只认"身份证/曾用名"列,避免备注等无关列变成匹配关键字
                if has_header and c != id_col and c not in alias_cols:
                    continue
                # 单元格里可能写多个值(顿号/逗号/空格分隔)
                for tok in re.split(r'[、,，;；\s]+', r[c]):
                    if not tok:
                        continue
                    if cls._looks_like_id(tok):
                        ids.append(tok)
                    elif has_header and c == id_col and \
                            re.fullmatch(r'[0-9A-Za-z]{15,20}', tok):
                        ids.append(tok)        # 老式 15/20 位纳税人识别号等
                    elif not has_header or c in alias_cols:
                        aliases.append(tok)
            persons.append(Person(name, ids, aliases))
        return cls(persons)
