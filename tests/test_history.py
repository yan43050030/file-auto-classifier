# -*- coding: utf-8 -*-
"""整理历史索引:记录、搜索、列出历次整理。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac import history


def test_record_and_search(tmp_path):
    out = str(tmp_path)
    rows = [('报告.docx', '/原/工作/报告.docx', '/新/文档/2023/报告.docx',
             100, '文档/2023', '类型:文档'),
            ('照片.jpg', '/原/图/照片.jpg', '/新/图片/2024/照片.jpg',
             200, '图片/2024', '类型:图片')]
    assert history.record_run(out, 'journal.jsonl', rows) == 2
    found = history.search(out, '报告')
    assert len(found) == 1
    _run_at, fname, src, dst, _cat = found[0]
    assert fname == '报告.docx'
    assert src.endswith('工作/报告.docx') and '文档/2023' in dst


def test_search_by_path_fragment(tmp_path):
    out = str(tmp_path)
    history.record_run(out, 'j', [('a.txt', '/移动硬盘/旧资料/a.txt',
                                   '/结果/文档/2020/a.txt', 1, '文档/2020', '')])
    assert history.search(out, '旧资料')
    assert history.search(out, '文档/2020')
    assert history.search(out, '不存在的东西') == []


def test_search_missing_db_is_safe(tmp_path):
    assert history.search(str(tmp_path / 'nope'), 'x') == []
    assert history.list_runs(str(tmp_path / 'nope')) == []


def test_list_runs(tmp_path):
    out = str(tmp_path)
    history.record_run(out, 'j1', [('a.txt', '/x/a.txt', '/y/a.txt', 1, 'c', '')])
    runs = history.list_runs(out)
    assert runs and runs[0][1] == 'j1' and runs[0][2] == 1


def test_record_empty_is_noop(tmp_path):
    assert history.record_run(str(tmp_path), 'j', []) == 0
    assert not os.path.exists(history.db_path(str(tmp_path)))
