# -*- coding: utf-8 -*-
"""反馈核对表:人员 × 来源单位 矩阵,空格即"该单位未反馈",可直接当催办清单。"""

import csv
import os

from .util import unique_path


def write_matrix_report(out_dir: str, matrix: dict, log):
    """matrix: {(folder, unit): count}。生成 CSV(Excel 可直接打开);
    装了 openpyxl 时同时生成 xlsx。返回生成的文件路径列表。"""
    if not matrix:
        return []
    units = sorted({u for (_f, u) in matrix})
    folders = []
    for (f, _u) in matrix:
        if f not in folders:
            folders.append(f)
    # 未分类放最后
    folders.sort(key=lambda f: (f == '未分类', f))

    header = ['人员/文件夹'] + units + ['合计']
    rows = []
    for f in folders:
        counts = [matrix.get((f, u), 0) for u in units]
        rows.append([f] + [c if c else '' for c in counts] + [sum(counts)])
    total_row = ['合计'] + \
        [sum(matrix.get((f, u), 0) for f in folders) for u in units] + \
        [sum(matrix.values())]

    written = []
    csv_path = unique_path(out_dir, '反馈核对表.csv')
    with open(csv_path, 'w', newline='', encoding='utf-8-sig') as fp:
        w = csv.writer(fp)
        w.writerow(header)
        w.writerows(rows)
        w.writerow(total_row)
    written.append(csv_path)

    try:
        import openpyxl
        from openpyxl.styles import Font, PatternFill
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = '反馈核对表'
        ws.append(header)
        for c in ws[1]:
            c.font = Font(bold=True)
        miss_fill = PatternFill('solid', fgColor='FFF2CC')   # 空格标黄提醒
        for r in rows:
            ws.append(r)
            row_idx = ws.max_row
            for col in range(2, 2 + len(units)):
                if ws.cell(row=row_idx, column=col).value in ('', None):
                    ws.cell(row=row_idx, column=col).fill = miss_fill
        ws.append(total_row)
        for c in ws[ws.max_row]:
            c.font = Font(bold=True)
        ws.column_dimensions['A'].width = 22
        xlsx_path = unique_path(out_dir, '反馈核对表.xlsx')
        wb.save(xlsx_path)
        written.append(xlsx_path)
    except ImportError:
        pass
    except Exception as e:
        log(f'  [提示] 生成 xlsx 核对表失败(已生成 CSV): {e}')
    return written
