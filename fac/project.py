# -*- coding: utf-8 -*-
"""项目目录识别 —— 代码仓库 / 工程目录要整体保留,不能按类型打散。

一个 Python 项目被拆成"代码脚本/2024/main.py + 可清理/空文件/__init__.py"
就彻底废了,所以整理时把这类目录当成一个整体搬运。
"""

import os

# 目录里出现这些文件(或目录)就认定为项目,整体保留
PROJECT_MARKERS = {
    '.git': 'Git 仓库',
    '.svn': 'SVN 仓库',
    '.hg': 'Mercurial 仓库',
    'package.json': 'Node 项目',
    'pnpm-lock.yaml': 'Node 项目',
    'yarn.lock': 'Node 项目',
    'requirements.txt': 'Python 项目',
    'pyproject.toml': 'Python 项目',
    'setup.py': 'Python 项目',
    'Pipfile': 'Python 项目',
    'pom.xml': 'Maven 项目',
    'build.gradle': 'Gradle 项目',
    'build.gradle.kts': 'Gradle 项目',
    'Cargo.toml': 'Rust 项目',
    'go.mod': 'Go 项目',
    'composer.json': 'PHP 项目',
    'Gemfile': 'Ruby 项目',
    'node_modules': 'Node 项目',
    '.venv': 'Python 虚拟环境',
    'venv': 'Python 虚拟环境',
    'vcpkg.json': 'C++ 项目',
}

# 弱标志:单独出现不足以认定项目(资料文件夹里也可能恰好放着 Makefile 教程),
# 必须同目录里还有源代码文件才算
WEAK_MARKERS = {
    'Makefile': '工程目录',
    'makefile': '工程目录',
    'GNUmakefile': '工程目录',
    'Dockerfile': '容器项目',
    'CMakeLists.txt': 'CMake 项目',
    'configure': '工程目录',
    'build.sh': '工程目录',
}

# 判断"弱标志成立"所需的源代码文件扩展名
SOURCE_EXTS = {
    '.c', '.cc', '.cpp', '.cxx', '.h', '.hpp', '.hxx', '.py', '.js', '.ts',
    '.go', '.rs', '.java', '.cs', '.php', '.rb', '.swift', '.kt', '.m',
    '.mm', '.sh', '.lua', '.scala', '.pl', '.f90', '.asm', '.s',
}

# 按扩展名判定(目录里有这类文件即认定)
PROJECT_MARKER_EXTS = {
    '.sln': 'VS 解决方案',
    '.xcodeproj': 'Xcode 项目',
    '.csproj': '.NET 项目',
    '.vcxproj': 'C++ 项目',
    '.uproject': 'Unreal 项目',
}

BUCKET_PROJECT = '项目'


def marker_of(dir_path: str, names=None):
    """判断一个目录是不是项目根。是则返回项目类型说明,否则返回 None。

    names 可传入已列好的目录内条目,省一次 listdir。"""
    try:
        entries = names if names is not None else os.listdir(dir_path)
    except OSError:
        return None
    entry_set = set(entries)
    for marker, kind in PROJECT_MARKERS.items():
        if marker in entry_set:
            return kind
    for e in entries:
        ext = os.path.splitext(e)[1].lower()
        if ext in PROJECT_MARKER_EXTS:
            return PROJECT_MARKER_EXTS[ext]
    # 弱标志:还要同目录里有源代码文件才算项目,
    # 否则"放着 Makefile 教程的资料夹"会被整体搬走
    for marker, kind in WEAK_MARKERS.items():
        if marker in entry_set and _has_source(entries):
            return kind
    return None


def _has_source(entries) -> bool:
    return any(os.path.splitext(e)[1].lower() in SOURCE_EXTS for e in entries)


def dir_stats(dir_path: str):
    """统计目录里的文件数与总大小(用于预览显示)。"""
    n, total = 0, 0
    for root, _dirs, files in os.walk(dir_path):
        for f in files:
            n += 1
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n, total


def find_projects(inputs, out_dir=None, log=None):
    """在输入目录里找出所有项目根目录。

    返回 {项目根绝对路径: (类型说明, 文件数, 总大小)}。
    项目内部不再继续深入 —— 嵌套的子项目不单独列出,随外层整体搬运。
    """
    found = {}
    out_abs = os.path.abspath(out_dir) if out_dir else None
    in_roots = {os.path.abspath(p) for p in inputs}
    # 原地整理(输出目录就是输入目录)时不能把输出目录整个排除,
    # 否则项目识别全部失效 —— 已经保护好的项目会在下次整理时被打散
    in_place = bool(out_abs) and out_abs in in_roots
    for p in inputs:
        p_abs = os.path.abspath(p)
        if not os.path.isdir(p_abs):
            continue
        for root, dirs, names in os.walk(p_abs):
            root_abs = os.path.abspath(root)
            if out_abs and not in_place and (
                    root_abs == out_abs or
                    root_abs.startswith(out_abs + os.sep)):
                dirs[:] = []
                continue
            # 输入根目录本身即使像项目也不整体搬(否则等于什么都没整理)
            if root_abs == p_abs:
                continue
            kind = marker_of(root_abs, names + dirs)
            if kind:
                n, total = dir_stats(root_abs)
                found[root_abs] = (kind, n, total)
                dirs[:] = []          # 不再深入项目内部
    if log and found:
        log(f'[项目] 识别出 {len(found)} 个项目/工程目录,将整体保留不打散:')
        for path, (kind, n, _t) in sorted(found.items())[:10]:
            log(f'  {os.path.basename(path)}({kind},{n} 个文件)')
        if len(found) > 10:
            log(f'  …共 {len(found)} 个')
    return found


def is_inside(path: str, project_roots) -> str:
    """文件是否位于某个项目目录内。是则返回该项目根路径。"""
    ap = os.path.abspath(path)
    for root in project_roots:
        if ap.startswith(root + os.sep):
            return root
    return ''
