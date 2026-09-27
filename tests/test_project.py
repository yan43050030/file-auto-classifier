# -*- coding: utf-8 -*-
"""项目/工程目录识别与整体保留。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac import project as proj


def mkproj(base, name, marker, extra=('src/main.py', 'README.md')):
    root = os.path.join(str(base), name)
    os.makedirs(root, exist_ok=True)
    mp = os.path.join(root, marker)
    os.makedirs(os.path.dirname(mp), exist_ok=True) if os.sep in marker else None
    if marker.startswith('.') and marker in ('.git', '.svn', '.hg'):
        os.makedirs(mp, exist_ok=True)
    else:
        open(mp, 'w').write('x')
    for e in extra:
        p = os.path.join(root, e)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'w').write('code')
    return root


def test_marker_detection(tmp_path):
    for marker, expect in [('package.json', 'Node 项目'),
                           ('requirements.txt', 'Python 项目'),
                           ('pom.xml', 'Maven 项目'),
                           ('Cargo.toml', 'Rust 项目'),
                           ('go.mod', 'Go 项目'),
                           ('.git', 'Git 仓库')]:
        root = mkproj(tmp_path, f'p_{marker.strip(".")}', marker)
        assert proj.marker_of(root) == expect, marker


def test_marker_by_extension(tmp_path):
    root = mkproj(tmp_path, 'vs', 'MyApp.sln')
    assert proj.marker_of(root) == 'VS 解决方案'


def test_plain_folder_is_not_project(tmp_path):
    d = tmp_path / '普通资料'
    d.mkdir()
    (d / '报告.docx').write_text('x')
    (d / '照片.jpg').write_text('y')
    assert proj.marker_of(str(d)) is None


def test_find_projects_does_not_descend(tmp_path):
    src = tmp_path / 'src'
    root = mkproj(src, 'outer', 'package.json')
    # 项目里嵌套的子项目不应单独列出
    mkproj(root, 'sub', 'requirements.txt')
    found = proj.find_projects([str(src)])
    assert list(found) == [os.path.abspath(root)]


def test_input_root_itself_not_treated_as_project(tmp_path):
    # 输入根本身像项目时不整体搬运,否则等于什么都没整理
    root = mkproj(tmp_path, 'whole', 'package.json')
    assert proj.find_projects([root]) == {}


def test_dir_stats(tmp_path):
    root = mkproj(tmp_path, 'p', 'go.mod')
    n, total = proj.dir_stats(root)
    assert n == 3 and total > 0        # go.mod + src/main.py + README.md


def test_is_inside(tmp_path):
    root = mkproj(tmp_path, 'p', 'go.mod')
    inside = os.path.join(root, 'src', 'main.py')
    assert proj.is_inside(inside, [root]) == root
    assert proj.is_inside(str(tmp_path / '别的.txt'), [root]) == ''


# ---------- 弱标志:需同时有源码才算项目 ----------

def test_weak_marker_needs_source_code():
    # 资料文件夹里恰好放着 Makefile 教程,不该被整体搬走
    assert marker_of_entries(['Makefile', '笔记.docx', '截图.png']) is None
    assert marker_of_entries(['Dockerfile', '说明.pdf']) is None
    assert marker_of_entries(['CMakeLists.txt', '教程.mp4']) is None
    # 同目录有源码才算真工程
    assert marker_of_entries(['Makefile', 'main.c', 'util.h']) == '工程目录'
    assert marker_of_entries(['Dockerfile', 'app.py']) == '容器项目'
    assert marker_of_entries(['CMakeLists.txt', 'lib.cpp']) == 'CMake 项目'


def test_strong_marker_needs_no_source():
    # 强标志单独出现即可认定
    assert marker_of_entries(['package.json', 'readme.txt']) == 'Node 项目'
    assert marker_of_entries(['.git', '资料.pdf']) == 'Git 仓库'
    assert marker_of_entries(['go.mod']) == 'Go 项目'


def marker_of_entries(entries):
    """用给定的目录条目列表直接判定(不落盘)。"""
    return proj.marker_of('/不存在的路径', entries)


def test_inplace_project_detection(tmp_path):
    # 原地整理(输出目录==输入目录)时,项目识别不能被"排除输出目录"关掉,
    # 否则已保护好的项目会在下次整理时被打散
    root = mkproj(tmp_path, 'app', 'package.json')
    found = proj.find_projects([str(tmp_path)], out_dir=str(tmp_path))
    assert os.path.abspath(root) in found


def test_out_dir_excluded_when_separate(tmp_path):
    # 输出目录独立(不在输入里)时,其中已整理好的项目不再重复处理
    src = tmp_path / 'src'
    out = tmp_path / 'out'
    src.mkdir()
    mkproj(out, 'already', 'package.json')
    mkproj(src, 'new', 'go.mod')
    found = proj.find_projects([str(src)], out_dir=str(out))
    assert {os.path.basename(p) for p in found} == {'new'}


def test_out_dir_under_input_is_excluded(tmp_path):
    # 输出目录是输入的子目录时也要排除,否则会把上次的成果再翻一遍
    src = tmp_path / 'src'
    out = src / '整理结果'
    mkproj(src, 'new', 'go.mod')
    mkproj(out, 'already', 'package.json')
    found = proj.find_projects([str(src)], out_dir=str(out))
    assert {os.path.basename(p) for p in found} == {'new'}
