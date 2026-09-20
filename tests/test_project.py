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
