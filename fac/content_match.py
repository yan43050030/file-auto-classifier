# -*- coding: utf-8 -*-
"""内容级匹配:文件名未命中时,读取文件内容(Excel/Word/PDF/文本)查找人员关键字。

所有解析依赖都是可选的,缺失时对应格式返回空字符串,静默降级。
"""

from .util import read_text_any_encoding

try:
    import openpyxl
    HAS_XLSX = True
except Exception:
    HAS_XLSX = False

try:
    import docx                    # python-docx
    HAS_DOCX = True
except Exception:
    HAS_DOCX = False

try:
    import pdfplumber
    HAS_PDF = True
except Exception:
    HAS_PDF = False

# 内容匹配支持的扩展名(用于界面提示)
SUPPORTED_EXTS = ['.txt', '.csv'] + \
    (['.xlsx', '.xlsm'] if HAS_XLSX else []) + \
    (['.docx'] if HAS_DOCX else []) + \
    (['.pdf'] if HAS_PDF else [])

_MAX_CHARS = 200_000     # 读取上限,防超大文件拖慢
_MAX_PDF_PAGES = 10


def _read_xlsx(path, limit):
    parts, total = [], 0
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            for row in ws.iter_rows(values_only=True):
                for c in row:
                    if c is None:
                        continue
                    s = str(c)
                    parts.append(s)
                    total += len(s)
                    if total >= limit:
                        return ' '.join(parts)
    finally:
        wb.close()
    return ' '.join(parts)


def _read_docx(path, limit):
    d = docx.Document(path)
    parts, total = [], 0
    for p in d.paragraphs:
        if p.text:
            parts.append(p.text)
            total += len(p.text)
            if total >= limit:
                return '\n'.join(parts)
    for t in d.tables:
        for row in t.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)
                    total += len(cell.text)
                    if total >= limit:
                        return '\n'.join(parts)
    return '\n'.join(parts)


def _read_pdf(path, limit):
    parts, total = [], 0
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:_MAX_PDF_PAGES]:
            t = page.extract_text() or ''
            if t:
                parts.append(t)
                total += len(t)
                if total >= limit:
                    break
    return '\n'.join(parts)


def extract_text(path: str, max_chars: int = _MAX_CHARS) -> str:
    """提取文件文本内容用于匹配。不支持/解析失败返回空字符串。"""
    low = path.lower()
    try:
        if low.endswith(('.txt', '.csv')):
            return (read_text_any_encoding(path) or '')[:max_chars]
        if low.endswith(('.xlsx', '.xlsm')) and HAS_XLSX:
            return _read_xlsx(path, max_chars)
        if low.endswith('.docx') and HAS_DOCX:
            return _read_docx(path, max_chars)
        if low.endswith('.pdf') and HAS_PDF:
            return _read_pdf(path, max_chars)
    except Exception:
        return ''
    return ''


def can_match(path: str) -> bool:
    return any(path.lower().endswith(e) for e in SUPPORTED_EXTS)
