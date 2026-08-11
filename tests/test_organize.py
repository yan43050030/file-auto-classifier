# -*- coding: utf-8 -*-
"""「文件整理」模式端到端 + 撤销台账。"""
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.organize import (OrganizeOptions, run_organize, render_layout,
                          collect_files, BUCKET_DUP, BUCKET_JUNK, BUCKET_OLD)
from fac.rules import Rule
from fac import undo as undo_mod

Y2023 = time.mktime((2023, 5, 20, 10, 0, 0, 0, 0, -1))
Y2024 = time.mktime((2024, 8, 1, 10, 0, 0, 0, 0, -1))


def mk(p, content=b'x', mtime=Y2024):
    p = str(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(content)
    os.utime(p, (mtime, mtime))
    return p


def run(opts, confirm=None):
    logs, result = [], {}
    run_organize(opts, log=logs.append, progress=lambda *a: None,
                 confirm_cb=confirm, done_cb=result.update)
    return logs, result


# ---------- 布局模板 ----------

def test_render_layout():
    assert render_layout('{类别}/{年}', '报告.docx', Y2023) == \
        os.path.join('文档', '2023')
    assert render_layout('{年}/{类别}', '照片.jpg', Y2024) == \
        os.path.join('2024', '图片')
    assert render_layout('{类别}', '片子.mp4', Y2024) == '视频'
    assert render_layout('{来源}/{类别}', 'IMG_20240101_1.jpg', Y2024,
                         source='相机照片') == os.path.join('相机照片', '图片')
    assert '2023-05' in render_layout('{类别}/{年月}', 'a.pdf', Y2023)


# ---------- 收集 ----------

def test_collect_skips_output_dir(tmp_path):
    src = tmp_path / 'src'
    out = src / '整理结果'
    mk(src / 'a.txt')
    mk(out / 'already.txt')
    files = collect_files([str(src)], str(out))
    names = {os.path.basename(p) for p, _s, _m in files}
    assert names == {'a.txt'}          # 输出目录内的不再参与


def test_collect_skips_tool_artifacts(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.txt')
    mk(src / '整理台账_20240101_000000.jsonl')
    mk(src / '分类日志_20240101_000000.txt')
    files = collect_files([str(src)], str(tmp_path / 'out'))
    assert {os.path.basename(p) for p, _s, _m in files} == {'a.txt'}


# ---------- 端到端 ----------

def test_organize_by_type_and_year(tmp_path):
    src = tmp_path / 'src'
    mk(src / '工作报告.docx', b'doc', Y2023)
    mk(src / '照片.jpg', b'img', Y2024)
    mk(src / '账目.xlsx', b'xls', Y2024)
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), layout='{类别}/{年}',
                                   preview=False))
    assert r['files'] == 3 and r['moved'] == 3
    assert (out / '文档' / '2023' / '工作报告.docx').exists()
    assert (out / '图片' / '2024' / '照片.jpg').exists()
    assert (out / '表格' / '2024' / '账目.xlsx').exists()
    assert not (src / '工作报告.docx').exists()      # 已移走
    assert r['reports']


def test_organize_copy_mode_keeps_original(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.pdf')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), op_mode='copy',
                                   preview=False, clean_empty_dirs=False))
    assert r['copied'] == 1
    assert (src / 'a.pdf').exists()                  # 原件还在
    assert (out / 'PDF' / '2024' / 'a.pdf').exists()


def test_organize_health_buckets(tmp_path):
    src = tmp_path / 'src'
    mk(src / '正常.docx', b'NORMAL')
    mk(src / 'Thumbs.db', b'junk')
    mk(src / '资料.pdf', b'DUPDATA', Y2023)
    mk(src / 'sub' / '资料副本.pdf', b'DUPDATA', Y2024)
    mk(src / '方案.docx', b'v1', Y2023)
    mk(src / '方案(1).docx', b'v2', Y2024)
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False))
    hs = r['health']
    assert hs['junk'] == 1
    assert hs['dup_extra'] == 1
    assert hs['old_versions'] == 1
    assert list((out / BUCKET_JUNK).rglob('Thumbs.db'))
    assert list((out / BUCKET_DUP).rglob('*.pdf'))
    assert (out / BUCKET_OLD / '方案.docx').exists()
    # 重复组里保留的那份走正常布局
    assert (out / '文档' / '2024' / '方案(1).docx').exists()


def test_organize_user_rules_win_over_type(tmp_path):
    src = tmp_path / 'src'
    mk(src / '2024年增值税发票.pdf', b'INVOICE')
    mk(src / '普通说明.pdf', b'NOTES')
    out = tmp_path / 'out'
    rules = [Rule('contains', '发票', '财务票据')]
    _logs, r = run(OrganizeOptions([str(src)], str(out), rules=rules,
                                   preview=False))
    assert (out / '财务票据' / '2024年增值税发票.pdf').exists()
    assert (out / 'PDF' / '2024' / '普通说明.pdf').exists()


def test_organize_preview_cancel_changes_nothing(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.docx')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=True),
                   confirm=lambda plan: False)
    assert r['cancelled']
    assert (src / 'a.docx').exists()
    assert not (out / '文档').exists()


def test_organize_preview_manual_reassign(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.docx')
    out = tmp_path / 'out'

    def confirm(plan):
        for it in plan:
            it.targets = ['我的重要资料/2024']
        return True

    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=True), confirm)
    assert (out / '我的重要资料' / '2024' / 'a.docx').exists()


def test_organize_cleans_empty_dirs(tmp_path):
    src = tmp_path / 'src'
    mk(src / '深' / '层' / 'a.docx')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False,
                                   clean_empty_dirs=True))
    assert r['empty_dirs'] >= 1
    assert not (src / '深' / '层').exists()


def test_organize_no_name_collision(tmp_path):
    # 不同目录下的同名文件(内容不同)整理到同一文件夹时不能互相覆盖
    src = tmp_path / 'src'
    mk(src / 'A' / '说明.txt', b'AAA')
    mk(src / 'B' / '说明.txt', b'BBB')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False,
                                   find_dup=False))
    got = sorted(p.name for p in (out / '文档' / '2024').iterdir())
    assert len(got) == 2 and r['files'] == 2


# ---------- 撤销 ----------

def test_undo_restores_everything(tmp_path):
    src = tmp_path / 'src'
    originals = {
        str(src / '报告.docx'): b'doc',
        str(src / 'sub' / '照片.jpg'): b'img',
        str(src / 'Thumbs.db'): b'junk',
    }
    for p, c in originals.items():
        mk(p, c)
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False))
    assert r['files'] == 3
    for p in originals:
        assert not os.path.exists(p)          # 都被移走了

    logs = []
    stats = undo_mod.undo(r['journal'], log=logs.append)
    assert stats['failed'] == 0
    for p, c in originals.items():
        assert os.path.exists(p), p           # 全部还原回原位
        assert open(p, 'rb').read() == c


def test_undo_copy_mode_removes_copies(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.docx', b'DATA')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), op_mode='copy',
                                   preview=False, clean_empty_dirs=False))
    dst = out / '文档' / '2024' / 'a.docx'
    assert dst.exists()
    stats = undo_mod.undo(r['journal'], log=lambda m: None)
    assert stats['removed'] == 1
    assert not dst.exists()
    assert (src / 'a.docx').exists()          # 原件始终未动


def test_undo_never_overwrites(tmp_path):
    # 撤销时如果原位置已有新文件,不能覆盖
    src = tmp_path / 'src'
    mk(src / 'a.docx', b'OLD')
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False,
                                   clean_empty_dirs=False))
    mk(src / 'a.docx', b'NEW-FILE-SAME-NAME')   # 整理后又新建了同名文件
    undo_mod.undo(r['journal'], log=lambda m: None)
    names = sorted(p.name for p in src.iterdir())
    assert len(names) == 2                      # 新文件保留 + 还原件改名
    assert (src / 'a.docx').read_bytes() == b'NEW-FILE-SAME-NAME'


def test_journal_survives_partial_run(tmp_path):
    # 台账是边做边写的:即使只完成一部分,已完成的也能撤销
    src = tmp_path / 'src'
    for i in range(5):
        mk(src / f'f{i}.docx', f'data{i}'.encode())
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False))
    meta, ops = undo_mod.read_journal(r['journal'])
    assert meta.get('op_mode') == 'move'
    assert len([o for o in ops if o['op'] == 'move']) == 5


def test_find_journals(tmp_path):
    out = tmp_path / 'out'
    src = tmp_path / 'src'
    mk(src / 'a.docx')
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False))
    found = undo_mod.find_journals(str(out))
    assert found and found[0] == r['journal']


def test_duplicate_copy_does_not_orphan_original(tmp_path):
    """副本内容相同且时间更新时,正本不能被连带判成「旧版本」而离开正常分类。"""
    src = tmp_path / 'src'
    mk(src / '年度总结.docx', b'SAME', Y2023)
    mk(src / '年度总结 - 副本.docx', b'SAME', Y2024)
    out = tmp_path / 'out'
    _logs, r = run(OrganizeOptions([str(src)], str(out), preview=False))
    assert r['health']['dup_extra'] == 1
    assert r['health']['old_versions'] == 0
    assert (out / '文档' / '2023' / '年度总结.docx').exists()   # 正本归位
    assert list((out / BUCKET_DUP).glob('*.docx'))              # 副本进重复区


def test_reorganize_is_idempotent(tmp_path):
    """对已整理好的目录重复整理,不能把文件反复改名成 (1)(2)。"""
    src = tmp_path / 'src'
    mk(src / 'a.docx', b'A')
    mk(src / 'b.jpg', b'B')
    out = tmp_path / 'out'
    run(OrganizeOptions([str(src)], str(out), preview=False))
    snap1 = sorted(str(p.relative_to(out)) for p in out.rglob('*')
                   if p.is_file() and not p.name.startswith(('整理', '分类')))
    # 再对整理结果本身跑一次(原地整理 / 重复运行)
    _logs, r2 = run(OrganizeOptions([str(out)], str(out), preview=False))
    snap2 = sorted(str(p.relative_to(out)) for p in out.rglob('*')
                   if p.is_file() and not p.name.startswith(('整理', '分类')))
    assert snap1 == snap2
    assert r2['moved'] == 0            # 一个文件都不该被搬动


def test_inplace_stable_files_still_counted(tmp_path):
    src = tmp_path / 'src'
    mk(src / 'a.docx', b'A')
    run(OrganizeOptions([str(src)], str(src), preview=False))
    _logs, r = run(OrganizeOptions([str(src)], str(src), preview=False))
    assert r['files'] == 1 and r['moved'] == 0
