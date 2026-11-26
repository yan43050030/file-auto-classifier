# -*- coding: utf-8 -*-
"""人员/企业文件夹内的资料类型细分:银行流水 / 其他数据(疑似空值另由 emptyfile 判定)。

判定依据:
1. 文件名含"流水/交易明细/对账单…"           → 银行流水
2. 表格(xlsx/xls/csv)前 20 行里的表头同时出现
   日期类列 + 金额/借贷类列,且总计命中 ≥3 种流水列  → 银行流水
3. PDF/Word 正文开头同样满足上面的列名组合        → 银行流水
4. 其余                                         → 其他数据
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


def detect_category(path, fname=None):
    """返回 '银行流水' 或 '其他数据'。读内容失败时只按文件名判断。"""
    fname = fname or os.path.basename(path)
    if _FLOW_NAME.search(fname):
        return CAT_FLOW
    try:
        if os.path.getsize(long_path(path)) > _MAX_CONTENT_BYTES:
            return CAT_OTHER
    except OSError:
        return CAT_OTHER
    low = path.lower()
    try:
        if low.endswith(('.xlsx', '.xlsm', '.xls', '.csv')):
            if _looks_like_flow_text(_head_text_table(path)):
                return CAT_FLOW
        elif low.endswith(('.pdf', '.docx', '.doc', '.txt')):
            from .content_match import extract_text
            if _looks_like_flow_text(extract_text(path, max_chars=4000) or ''):
                return CAT_FLOW
    except Exception:
        pass
    return CAT_OTHER
