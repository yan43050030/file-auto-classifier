# -*- coding: utf-8 -*-
"""文件体检:重复、版本族、垃圾、大文件、空目录。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac import health


def mk(p, content=b'x', mtime=None):
    p = str(p)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, 'wb') as f:
        f.write(content)
    if mtime:
        os.utime(p, (mtime, mtime))
    return p


def pairs(paths):
    return [(p, os.path.getsize(p)) for p in paths]


def test_find_duplicates_basic(tmp_path):
    a = mk(tmp_path / 'a.txt', b'SAME-CONTENT')
    b = mk(tmp_path / 'sub' / 'b.txt', b'SAME-CONTENT')
    c = mk(tmp_path / 'c.txt', b'DIFFERENT')
    groups = health.find_duplicates(pairs([a, b, c]))
    assert len(groups) == 1
    assert set(groups[0]) == {a, b}


def test_find_duplicates_same_size_different_content(tmp_path):
    a = mk(tmp_path / 'a.txt', b'AAAA')
    b = mk(tmp_path / 'b.txt', b'BBBB')      # 同样大小,内容不同
    assert health.find_duplicates(pairs([a, b])) == []


def test_find_duplicates_large_files(tmp_path):
    # 超过 1MB 的走"先比前 64KB"两段式,结果须与全量比一致
    big = b'Z' * (2 * 1024 * 1024)
    a = mk(tmp_path / 'a.bin', big)
    b = mk(tmp_path / 'b.bin', big)
    c = mk(tmp_path / 'c.bin', big[:-1] + b'Q')
    groups = health.find_duplicates(pairs([a, b, c]))
    assert len(groups) == 1 and set(groups[0]) == {a, b}


def test_duplicate_keeps_original_first(tmp_path):
    # 名字像副本的不应被选为"保留"
    orig = mk(tmp_path / '报告.docx', b'DATA', mtime=1000000)
    copy = mk(tmp_path / '报告(1).docx', b'DATA', mtime=2000000)
    groups = health.find_duplicates(pairs([copy, orig]))
    assert groups[0][0] == orig


def test_empty_files_not_duplicates(tmp_path):
    a = mk(tmp_path / 'a.txt', b'')
    b = mk(tmp_path / 'b.txt', b'')
    assert health.find_duplicates(pairs([a, b])) == []


def test_version_families(tmp_path):
    new = mk(tmp_path / '方案(1).docx', b'v2', mtime=2000000)
    old = mk(tmp_path / '方案.docx', b'v1', mtime=1000000)
    fams = health.find_version_families(pairs([new, old]))
    assert len(fams) == 1
    base, paths = fams[0]
    assert base == '方案'
    assert paths[0] == new          # 最新的排第一


def test_version_families_requires_marker(tmp_path):
    # 都没有副本标记,只是名字接近,不该成组
    a = mk(tmp_path / '会议纪要1.docx', b'a')
    b = mk(tmp_path / '会议纪要2.docx', b'b')
    assert health.find_version_families(pairs([a, b])) == []


def test_version_families_same_ext_only(tmp_path):
    a = mk(tmp_path / '方案.docx', b'a')
    b = mk(tmp_path / '方案(1).pdf', b'b')
    assert health.find_version_families(pairs([a, b])) == []


def test_find_junk(tmp_path):
    j1 = mk(tmp_path / 'Thumbs.db', b'x')
    j2 = mk(tmp_path / '~$报告.docx', b'x')
    ok = mk(tmp_path / '报告.docx', b'x')
    found = dict(health.find_junk(pairs([j1, j2, ok])))
    assert j1 in found and j2 in found and ok not in found


def test_find_large(tmp_path):
    small = mk(tmp_path / 's.bin', b'x' * 100)
    big = mk(tmp_path / 'b.bin', b'x' * 5000)
    out = health.find_large(pairs([small, big]), threshold=1000)
    assert [p for p, _s in out] == [big]


def test_find_empty_dirs(tmp_path):
    os.makedirs(tmp_path / 'empty' / 'nested')
    os.makedirs(tmp_path / 'full')
    mk(tmp_path / 'full' / 'f.txt', b'x')
    empties = health.find_empty_dirs([str(tmp_path)])
    assert str(tmp_path / 'empty' / 'nested') in empties
    assert str(tmp_path / 'empty') in empties      # 只剩空子目录也算空
    assert str(tmp_path / 'full') not in empties


def test_human_size():
    assert health.human_size(0) == '0 B'
    assert health.human_size(1536) == '1.5 KB'
    assert 'MB' in health.human_size(5 * 1024 * 1024)
