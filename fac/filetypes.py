# -*- coding: utf-8 -*-
"""文件类型/来源/垃圾文件识别 —— 「文件整理」模式的基础词表。

按"用途"而非扩展名罗列分类:一个大类对应多个扩展名,便于日常查找。
"""

import os
import re

# ---------- 大类词表 ----------
# 顺序即优先级(同一扩展名只会落在第一个匹配的大类)
CATEGORIES = [
    ('文档', ('doc', 'docx', 'wps', 'odt', 'rtf', 'txt', 'md', 'tex',
              'pages', 'xmind', 'mm', 'one')),
    ('表格', ('xls', 'xlsx', 'xlsm', 'xlsb', 'csv', 'et', 'ods', 'numbers')),
    ('演示', ('ppt', 'pptx', 'pptm', 'dps', 'odp', 'key')),
    ('PDF', ('pdf',)),
    ('图片', ('jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'tif', 'tiff',
              'heic', 'heif', 'svg', 'ico', 'raw', 'cr2', 'cr3', 'nef',
              'arw', 'dng', 'orf', 'rw2')),
    ('视频', ('mp4', 'avi', 'mkv', 'mov', 'wmv', 'flv', 'rmvb', 'rm',
              '3gp', 'mpg', 'mpeg', 'webm', 'ts', 'm4v', 'vob', 'f4v')),
    ('音频', ('mp3', 'wav', 'flac', 'aac', 'ogg', 'wma', 'm4a', 'ape',
              'aiff', 'amr', 'mid', 'midi')),
    ('压缩包', ('zip', 'rar', '7z', 'tar', 'gz', 'bz2', 'xz', 'tgz',
                'tbz2', 'txz', 'cab', 'arj')),
    ('光盘镜像', ('iso', 'img', 'mdf', 'nrg', 'bin', 'vhd', 'vmdk')),
    ('安装程序', ('exe', 'msi', 'apk', 'dmg', 'pkg', 'deb', 'rpm',
                  'appimage', 'ipa', 'msix')),
    ('电子书', ('epub', 'mobi', 'azw', 'azw3', 'fb2', 'djvu', 'chm')),
    ('代码脚本', ('py', 'js', 'jsx', 'ts', 'tsx', 'java', 'c', 'cpp', 'cc',
                  'h', 'hpp', 'cs', 'go', 'rs', 'php', 'rb', 'swift', 'kt',
                  'sh', 'bat', 'cmd', 'ps1', 'vbs', 'sql', 'r', 'lua',
                  'html', 'htm', 'css', 'scss', 'less', 'json', 'xml',
                  'yaml', 'yml', 'toml', 'ipynb')),
    ('设计源文件', ('psd', 'ai', 'cdr', 'sketch', 'fig', 'xd', 'indd',
                    'eps', 'dwg', 'dxf', 'skp', '3ds', 'max', 'blend',
                    'c4d', 'stl', 'obj')),
    ('字体', ('ttf', 'otf', 'ttc', 'woff', 'woff2', 'fon', 'fnt')),
    ('数据库', ('db', 'sqlite', 'sqlite3', 'mdb', 'accdb', 'dbf')),
    ('种子与配置', ('torrent', 'ini', 'cfg', 'conf', 'reg', 'plist',
                    'lnk', 'url', 'desktop')),
]

OTHER_CATEGORY = '其他文件'

# 扩展名 → 大类(启动时构建一次)
_EXT_MAP = {}
for _cat, _exts in CATEGORIES:
    for _e in _exts:
        _EXT_MAP.setdefault(_e, _cat)

CATEGORY_NAMES = [c for c, _ in CATEGORIES] + [OTHER_CATEGORY]


def ext_of(fname: str) -> str:
    """取小写扩展名(不含点)。复合扩展如 .tar.gz 返回 gz。"""
    return os.path.splitext(fname)[1].lstrip('.').lower()


def categorize(fname: str) -> str:
    """按文件名判断所属大类。"""
    return _EXT_MAP.get(ext_of(fname), OTHER_CATEGORY)


# ---------- 来源识别 ----------
# 文件名里往往带着来源痕迹,据此可分出"微信文件""截图""相机照片"等
SOURCE_PATTERNS = [
    ('微信文件', (
        r'^微信图片[_\-]?\d+',
        r'^mmexport\d+',
        r'^wx_camera_\d+',
        r'^wx_?\d{10,}',
        r'^微信[_\-]',
    )),
    ('QQ文件', (
        r'^QQ图片\d+',
        r'^QQ视频',
        r'^QQ截图\d+',
        r'^MobileQQ',
    )),
    ('截图', (
        r'^(screenshot|screen ?shot)[_\- ]?\d',
        r'^(屏幕截图|截图|截屏)[_\- ]?\d',
        r'^snipaste[_\-]?\d',
        r'^(snap|捕获)\d+',
    )),
    ('相机照片', (
        r'^(img|dsc|dscf|dscn|pict|pxl|dji|gopr|p\d{7})[_\-]?\d+',
        r'^\d{8}_\d{6}$',            # 20240115_143022
    )),
    ('未完成下载', (
        r'\.(crdownload|part|download|downloading|!ut|td)$',
        r'\.partial$',
    )),
]

_SOURCE_RE = [(name, [re.compile(p, re.I) for p in pats])
              for name, pats in SOURCE_PATTERNS]


def detect_source(fname: str):
    """识别文件来源(微信/QQ/截图/相机/未完成下载)。识别不出返回 None。"""
    stem = os.path.splitext(fname)[0]
    for name, regs in _SOURCE_RE:
        for r in regs:
            # 未完成下载的特征在完整文件名(含扩展名)上
            target = fname if name == '未完成下载' else stem
            if r.search(target):
                return name
    return None


# ---------- 垃圾/临时文件 ----------
_JUNK_NAMES = {
    'thumbs.db', 'ehthumbs.db', 'ehthumbs_vista.db', '.ds_store',
    'desktop.ini', 'iconcache.db', '.localized', 'folder.htt',
    '$recycle.bin', 'system volume information', '.spotlight-v100',
    '.trashes', '.fseventsd', 'ntuser.dat',
}
_JUNK_SUFFIXES = ('.tmp', '.temp', '.bak', '.old', '.chk', '.gid',
                  '.crdownload', '.part', '.download', '.!ut')
_JUNK_PREFIXES = ('~$', '.~lock.')


def junk_reason(fname: str, size: int = -1):
    """判断是否是可清理的垃圾/临时文件。返回原因字符串,不是则返回 None。"""
    low = fname.lower()
    if low in _JUNK_NAMES:
        return '系统缓存文件'
    if low.startswith(_JUNK_PREFIXES):
        return 'Office 临时文件'
    if low.endswith(_JUNK_SUFFIXES):
        if low.endswith(('.crdownload', '.part', '.download', '.!ut')):
            return '未完成的下载'
        return '临时/备份文件'
    if size == 0:
        return '空文件(0 字节)'
    return None


# ---------- 版本/副本文件识别 ----------
# 只认"系统或人为生成副本"的明确标记,不动裸数字结尾(如"会议纪要2"可能是另一次会议)
_COPY_MARKERS = [
    re.compile(r'[（(]\s*\d+\s*[)）]$'),                    # 报告(1)
    re.compile(r'的副本\d*$'),                               # 报告的副本(须排在通用副本规则前)
    re.compile(r'[-_ ]*(副本|拷贝|复件)\d*$'),               # 报告 - 副本 / 报告-副本2
    re.compile(r'[-_ ]*copy(\s*\(?\d+\)?)?$', re.I),        # 报告 - Copy (2)
    re.compile(r'[-_ ]*(最终版?|终稿|定稿|final)\d*$', re.I),  # 报告-最终版2
    re.compile(r'[-_ ]*(修改版?|修订版?|revised?)\d*$', re.I),
    re.compile(r'[-_ ]*[vV]\d+(\.\d+)*$'),                  # 报告_v2 / 报告-V1.2
    re.compile(r'[-_ ]*第?\d+版$'),                          # 报告第3版
    re.compile(r'[-_ ]*\(\s*(new|旧|old)\s*\)$', re.I),
]


def strip_copy_markers(stem: str):
    """剥掉文件名主干末尾的副本/版本标记,可能连续剥多层。

    返回 (基名, 剥掉的层数)。层数为 0 表示这不是一个副本/版本文件。"""
    base = stem.strip()
    n = 0
    for _ in range(4):          # 最多剥 4 层,防病态文件名
        changed = False
        for r in _COPY_MARKERS:
            m = r.search(base)
            if m and m.start() > 0:      # 剥完不能为空
                base = base[:m.start()].rstrip(' -_')
                n += 1
                changed = True
                break
        if not changed:
            break
    return base.strip(), n


def is_copy_like(fname: str) -> bool:
    """文件名看起来像副本(用于重复文件组里挑该保留哪一个)。"""
    stem = os.path.splitext(fname)[0]
    _base, n = strip_copy_markers(stem)
    return n > 0
