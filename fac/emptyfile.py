# -*- coding: utf-8 -*-
"""疑似空值反馈识别。

场景:向银行等单位查询,"此人在本行无账户"时,单位反馈的往往是一个只有表头的
Excel 或一句"查无记录"的回函,4~8 KB。把它们挑出来放进此人目录下的「疑似空值」,
看材料时可以先跳过,想核对再点进去看。

判定(只看小于阈值的文件,大文件一律当作有内容):
- 0 字节                          → 疑似空值
- 表格(xlsx/xls/csv):除表头外没有"实质数据行" → 疑似空值
  实质数据行 = 去掉 被查询人姓名/证号、序号、"无""/""-" 等空值后仍有内容,
  且不含"查无/未开户/无记录"等字样
  —— 只写了被查人姓名证号 + "无" 的行,不算实质数据
- 文档(docx/doc/pdf/txt):正文含"查无/未查询到/无账户/无记录"等字样,或几乎没有文字
- 读不了内容的(图片等):按大小判定
有实质数据行的小表格(比如只有一两条账户记录)会留在正常目录,不会被藏起来。
"""

import os
import re

from .util import long_path, read_text_any_encoding

BUCKET_EMPTY = '疑似空值'
DEFAULT_MAX_KB = 10

# "没有信息"的典型表述
_NO_INFO = re.compile(
    r'查无|未查[询到见]|未能查[询到]|没有查[询到]|未发现|未找到|没有找到|'
    r'无(相关|此|该|任何)?(记录|信息|数据|结果|账户|帐户|账号|帐号|开户|业务|交易|资料|情况)|'
    r'没有(相关|任何)?(记录|信息|数据|账户|帐户|开户|业务|交易)|'
    r'未(开立|开设|开户|办理|登记|发生|在我[行司])|不存在|无此人|非我[行司]客户|'
    r'暂无|查询结果[:：]?\s*无|结果为空|空表')
# 单元格里表示"空"的写法
_NULLS = {'', '无', '/', '-', '--', '—', '——', '空', '暂无', '0', '0.0', '0.00',
          'none', 'null', 'n/a', 'na', '无记录', '无信息', '否'}
_TABLE_EXTS = ('.xlsx', '.xlsm', '.xls', '.csv')
_TEXT_EXTS = ('.docx', '.doc', '.pdf', '.txt', '.rtf', '.wps')
_MAX_ROWS = 300       # 小文件不会太多行,防御性上限


def _rows_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(long_path(path), read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for i, row in enumerate(ws.iter_rows(values_only=True)):
                if i >= _MAX_ROWS:
                    break
                yield ws.title, [('' if c is None else str(c).strip()) for c in row]
    finally:
        wb.close()


def _rows_xls(path):
    import xlrd
    wb = xlrd.open_workbook(long_path(path))
    for sh in wb.sheets():
        for r in range(min(sh.nrows, _MAX_ROWS)):
            yield sh.name, [str(v).strip() for v in sh.row_values(r)]


def _rows_csv(path):
    import csv
    import io
    text = read_text_any_encoding(path) or ''
    for i, row in enumerate(csv.reader(io.StringIO(text))):
        if i >= _MAX_ROWS:
            break
        yield '', [c.strip() for c in row]


def _is_null(cell):
    c = cell.strip().lower()
    if c in _NULLS:
        return True
    # 序号:1、2、03 这类小整数
    return bool(re.fullmatch(r'\d{1,3}(\.0)?', c))


def _table_reason(path, keywords):
    low = path.lower()
    if low.endswith(('.xlsx', '.xlsm')):
        rows = _rows_xlsx(path)
    elif low.endswith('.xls'):
        rows = _rows_xls(path)
    else:
        rows = _rows_csv(path)
    header_seen = {}          # 每个工作表的表头行只跳过一次
    substantive = 0
    no_info_hit = False
    for sheet, cells in rows:
        filled = [c for c in cells if c]
        if not filled:
            continue
        text = ' '.join(filled)
        if _NO_INFO.search(text):
            no_info_hit = True
            continue
        # 表头:每个工作表第一行有 ≥2 个单元格的行;更早的单格行是标题
        if not header_seen.get(sheet):
            if len(filled) >= 2:
                header_seen[sheet] = True
            continue
        rest = [c for c in filled
                if not _is_null(c) and not any(k and k in c for k in keywords)]
        if rest:
            substantive += 1
    if substantive:
        return None
    return '表格只有表头/无实质数据' if not no_info_hit else '表格注明查无记录'


def _text_reason(path, keywords):
    from .content_match import extract_text
    text = extract_text(path) or ''
    if not text.strip():
        return None                   # 读不出文字(如扫描件):交给大小判定
    if _NO_INFO.search(text):
        return '正文注明查无记录'
    rest = text
    for k in keywords:
        if k:
            rest = rest.replace(k, '')
    if len(re.sub(r'\s', '', rest)) < 10:
        return '正文几乎没有内容'
    return None


def empty_reason(path, size=None, max_bytes=DEFAULT_MAX_KB * 1024,
                 keywords=()):
    """小于 max_bytes 且看起来没有实质信息时,返回原因说明;否则返回 None。

    keywords: 被查询对象的姓名/证号/曾用名等,表格里只出现这些不算实质内容。"""
    if size is None:
        try:
            size = os.path.getsize(long_path(path))
        except OSError:
            return None
    if size > max_bytes:
        return None
    if size == 0:
        return '空文件'
    low = path.lower()
    keywords = [k for k in keywords if k]
    try:
        if low.endswith(_TABLE_EXTS):
            return _table_reason(path, keywords)
        if low.endswith(_TEXT_EXTS):
            r = _text_reason(path, keywords)
            if r is not None:
                return r
            # 读得出文字且有内容 → 不是空值;读不出 → 落到下面按大小
            from .content_match import extract_text
            if (extract_text(path) or '').strip():
                return None
    except Exception:
        pass               # 解析失败(损坏/加密):按大小判定
    return f'小于 {max_bytes // 1024} KB'
