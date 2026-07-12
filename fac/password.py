# -*- coding: utf-8 -*-
"""压缩包密码管理与密码本解析。"""

import os

from .util import read_text_any_encoding


class PasswordManager:
    """密码尝试顺序:已验证成功的密码 → 密码本候选(seeds)→ 弹框询问。"""

    def __init__(self, ask_cb, seeds=None):
        # ask_cb(archive_name, attempt) -> str | None(None 表示用户取消)
        self.ask_cb = ask_cb
        self.verified = []       # 已验证成功的密码(优先复用)
        self.seeds = []          # 密码本读取的候选密码
        for s in (seeds or []):
            if s and s not in self.seeds:
                self.seeds.append(s)

    def candidates(self):
        out = list(self.verified)
        for s in self.seeds:
            if s not in out:
                out.append(s)
        return out

    def add(self, pwd):
        if pwd and pwd not in self.verified:
            self.verified.insert(0, pwd)

    def prompt(self, name, attempt):
        return self.ask_cb(name, attempt)


def parse_password_lines(text: str):
    """从一段文本里提取候选密码。兼容"文件名 密码 / 文件名:密码 / 文件名=密码"等格式。"""
    cands = []

    def _add(v):
        v = v.strip().strip('"').strip("'")
        if v and len(v) <= 128 and v not in cands:
            cands.append(v)

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        _add(line)  # 整行也作为候选(纯密码列表的情况)
        for sep in (':', '：', '=', '\t', '，', ','):
            if sep in line:
                _add(line.split(sep, 1)[1])   # 分隔符右侧
                _add(line.rsplit(sep, 1)[1])
        ws = line.split()
        if len(ws) >= 2:
            _add(ws[-1])                       # 多空格分隔时取最后一段
    return cands


def load_password_candidates(paths, log, max_count=300):
    """从若干 txt 文件读取候选密码(自动尝试多种中文编码)。"""
    cands = []
    for p in paths:
        raw = read_text_any_encoding(p)
        if raw is None:
            log(f'  [提示] 密码本读取失败(编码不识别): {os.path.basename(p)}')
            continue
        for c in parse_password_lines(raw):
            if c not in cands:
                cands.append(c)
                if len(cands) >= max_count:
                    return cands
    return cands
