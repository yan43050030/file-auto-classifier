# -*- coding: utf-8 -*-
"""通用工具:路径、编码、哈希、回收站。"""

import os
import sys
import hashlib


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包:返回资源文件(app.ico / UnRAR.exe)的真实路径。"""
    base = getattr(sys, '_MEIPASS', None)
    if base is None:
        # 包目录的上一级 = 项目根目录
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def long_path(p: str) -> str:
    """Windows 下超长路径加 \\\\?\\ 前缀,突破 260 字符 MAX_PATH 限制。"""
    if sys.platform == 'win32':
        p = os.path.abspath(p)
        if len(p) > 240 and not p.startswith('\\\\?\\'):
            p = '\\\\?\\' + p
    return p


def safe_folder_name(name: str) -> str:
    """把关键字转成合法的文件夹名,去掉 Windows 不允许的字符。"""
    name = str(name).strip()
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip(' .') or '未命名'


def unique_path(dst_folder: str, filename: str) -> str:
    """避免同名覆盖:若已存在则加 (1)(2)…"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dst_folder, filename)
    i = 1
    while os.path.exists(long_path(candidate)):
        candidate = os.path.join(dst_folder, f'{base}({i}){ext}')
        i += 1
    return candidate


def read_text_any_encoding(path: str):
    """自动尝试常见中文编码读取文本文件,失败返回 None。"""
    for enc in ('utf-8-sig', 'gbk', 'utf-16', 'utf-8'):
        try:
            with open(long_path(path), 'r', encoding=enc) as f:
                return f.read()
        except Exception:
            continue
    return None


def sha1_of(path: str, chunk: int = 1 << 20) -> str:
    """计算文件 SHA-1,用于跨单位重复文件去重。"""
    h = hashlib.sha1()
    with open(long_path(path), 'rb') as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def delete_to_trash(path: str) -> str:
    """把文件移入回收站;失败时退回永久删除。返回描述用的方式字符串。"""
    try:
        from send2trash import send2trash
        send2trash(os.path.abspath(path))
        return '回收站'
    except Exception:
        os.remove(path)
        return '永久删除'
