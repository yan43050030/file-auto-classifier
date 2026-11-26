# -*- coding: utf-8 -*-
"""归档库:同一个输出目录可以反复导入新的反馈,结果累积在一起。

- 同一人/企业并入已有文件夹:先按身份证号/统一社会信用代码对上,再按名称对上;
  旧文件夹只有名称、新数据带了证号的,把旧文件夹升级改名为「名称_证号」,不另起一个。
- 重复导入同一批反馈:同一单位的同名同内容文件直接跳过,不会产生 (1)(2) 副本。
- 归档记录.jsonl:每放入一个文件记一行(人员/单位/类型/是否疑似空值),
  反馈核对表据此累计生成 —— 历次导入的情况都在一张表里。
"""

import os
import re
import json
import datetime

from .idcard import valid_id18, valid_id15
from .company import valid_uscc
from .util import long_path, sha1_of

LEDGER_NAME = '归档记录.jsonl'
# 这些是工具自己的功能文件夹,不是人员/企业
SPECIAL_FOLDERS = {'未分类', '解压失败', '暂未解压', '原始反馈'}


def _is_code(s):
    s = (s or '').strip().upper()
    return bool(s) and (valid_id18(s) or valid_id15(s) or valid_uscc(s))


# 同一个压缩包下载了两次:「工商银行 (1)」「工商银行 - 副本」视为同一来源
_COPY_TAIL = re.compile(r'(\s*(\(\d+\)|（\d+）|[-_ ]*副本(\s*\(\d+\))?|[-_ ]*copy(\s*\d+)?))+$',
                        re.IGNORECASE)


def unit_key(unit):
    return _COPY_TAIL.sub('', (unit or '').strip()) or (unit or '')


_SPLIT_RE = re.compile(r'[_\s\-—()（）【】\[\]·.,，、]+')


def parse_folder(name):
    """「张三_110…」→ ('张三', '110…');「110…」→ ('', '110…');「张三」→ ('张三', '')。

    用户给文件夹加了备注也认得出:「赵六_110…_重点人员」「重点_赵六_110…」
    → 证号在名称中任意位置都行,名称取证号前面的部分。"""
    if _is_code(name):
        return '', name.upper()
    for tok in _SPLIT_RE.split(name):
        if tok and _is_code(tok):
            before = [t for t in _SPLIT_RE.split(name[:name.find(tok)]) if t]
            return (before[-1] if before else ''), tok.upper()
    return name, ''


class Library:
    """输出目录里已有的人员/企业文件夹索引 + 归档记录。"""

    def __init__(self, out_dir, log=None):
        self.out_dir = out_dir
        self.log = log or (lambda m: None)
        self.by_code, self.by_name = {}, {}
        self.renames = {}            # 旧文件夹名 -> 新文件夹名(执行时才真正改名)
        self.existing = set()
        try:
            names = os.listdir(long_path(out_dir))
        except OSError:
            names = []
        for n in names:
            if n in SPECIAL_FOLDERS or n.startswith('.'):
                continue
            if not os.path.isdir(long_path(os.path.join(out_dir, n))):
                continue
            self._index(n)
            self.existing.add(n)
        self.ledger_path = os.path.join(out_dir, LEDGER_NAME)
        # 已导入文件:(对象键, 单位键, 原文件名, sha1)。对象键优先用证号/信用代码,
        # 这样用户给人员文件夹改了名(加备注)也认得出是同一人的旧文件
        self._imported = set()
        recs = list(self._read_ledger())
        renames = {r.get('from'): r.get('to') for r in recs if r.get('type') == 'rename'}
        for rec in recs:
            if rec.get('type') == 'file':
                f = rec.get('folder')
                seen = set()
                while f in renames and f not in seen:
                    seen.add(f)
                    f = renames[f]
                self._imported.add((self._who(f), unit_key(rec.get('unit')),
                                    rec.get('name'), rec.get('sha1')))

    @staticmethod
    def _who(folder):
        name, code = parse_folder(folder or '')
        return code or folder

    @property
    def has_existing(self):
        return bool(self.existing)

    def _index(self, folder):
        name, code = parse_folder(folder)
        if code:
            self.by_code.setdefault(code, folder)
        if name:
            lst = self.by_name.setdefault(name, [])
            if folder not in lst:
                lst.append(folder)

    def _unindex(self, folder):
        name, code = parse_folder(folder)
        if code and self.by_code.get(code) == folder:
            del self.by_code[code]
        if name and folder in self.by_name.get(name, []):
            self.by_name[name].remove(folder)

    # ---------- 目标文件夹对齐 ----------

    def resolve(self, target):
        """把本次计划的目标文件夹对到已有文件夹上。返回最终使用的文件夹名。"""
        if not target or target in SPECIAL_FOLDERS:
            return target
        target = self.renames.get(target, target)
        if target in self.existing:
            return target
        name, code = parse_folder(target)
        if code and code in self.by_code:
            old = self.by_code[code]                   # 证号/信用代码相同 = 同一人/企业
            if name and old.upper() == code and old not in self.renames:
                # 旧文件夹就是光秃秃的证号、这次知道了名称:升级为「名称_证号」
                # (用户自己加过备注的文件夹名一律不动)
                self.renames[old] = target
                self._unindex(old)
                self.existing.discard(old)
                self._index(target)
                self.existing.add(target)
                return target
            return old
        cands = self.by_name.get(name, []) if name else []
        if code:
            plain = [f for f in cands if not parse_folder(f)[1] and f == name]
            if len(plain) == 1 and len(cands) == 1:
                old = plain[0]                         # 旧的只有名称:升级改名
                self.renames[old] = target
                self._unindex(old)
                self.existing.discard(old)
        elif len(cands) == 1:
            return cands[0]                            # 只有名称:名称唯一才并入
        self._index(target)
        self.existing.add(target)
        return target

    def apply_renames(self):
        """执行阶段:把需要升级的旧文件夹真正改名,并记入归档记录。"""
        for old, new in list(self.renames.items()):
            src = os.path.join(self.out_dir, old)
            dst = os.path.join(self.out_dir, new)
            if not os.path.isdir(long_path(src)) or os.path.exists(long_path(dst)):
                continue
            try:
                os.rename(long_path(src), long_path(dst))
                self._append({'type': 'rename', 'from': old, 'to': new})
                self.log(f'  [归档库] 「{old}」补全为「{new}」(新反馈带了证号/信用代码)')
            except OSError as e:
                self.log(f'  [提示] 文件夹改名失败 {old} → {new}: {e}')

    # ---------- 重复导入 ----------

    def already_imported(self, folder, unit, name, src, dst_candidate=None):
        """同一单位、同名、同内容的文件已经导入过 → True(跳过)。

        有归档记录时按记录判断;老版本生成的目录没有记录,则看目标位置
        是否已有同名且内容相同的文件。"""
        try:
            digest = sha1_of(src)
        except OSError:
            return False, ''
        if (self._who(folder), unit_key(unit), name, digest) in self._imported:
            return True, digest
        if dst_candidate and os.path.isfile(long_path(dst_candidate)):
            try:
                if os.path.getsize(long_path(dst_candidate)) == \
                        os.path.getsize(long_path(src)) and \
                        sha1_of(dst_candidate) == digest:
                    return True, digest
            except OSError:
                pass
        return False, digest

    # ---------- 归档记录 ----------

    def _read_ledger(self):
        try:
            with open(self.ledger_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            yield json.loads(line)
                        except ValueError:
                            continue
        except OSError:
            return

    def _append(self, rec):
        rec.setdefault('time', datetime.datetime.now().isoformat(timespec='seconds'))
        try:
            with open(self.ledger_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        except OSError:
            pass

    def record(self, folder, unit, name, digest, category, empty, rel_path):
        self._imported.add((self._who(folder), unit_key(unit), name, digest))
        self._append({'type': 'file', 'folder': folder, 'unit': unit,
                      'name': name, 'sha1': digest, 'category': category,
                      'empty': bool(empty), 'path': rel_path})

    def file_records(self):
        """全部文件记录(已套用文件夹改名),供《文件名对照表》使用。"""
        recs = list(self._read_ledger())
        renames = {r.get('from'): r.get('to') for r in recs if r.get('type') == 'rename'}
        out = []
        for r in recs:
            if r.get('type') != 'file':
                continue
            path = r.get('path') or ''
            parts = path.replace('\\', '/').split('/')
            if parts and parts[0] in renames:
                parts[0] = renames[parts[0]]
                path = os.path.join(*parts)
            out.append({'time': r.get('time', ''), 'unit': r.get('unit', ''),
                        'name': r.get('name', ''), 'path': path,
                        'category': r.get('category', '')})
        return out

    def cumulative_matrix(self):
        """按归档记录累计:({(人员, 单位): 文件数}, {(人员, 单位): 疑似空值数})。"""
        matrix, empty = {}, {}
        renames = {}
        recs = list(self._read_ledger())
        for rec in recs:
            if rec.get('type') == 'rename':
                renames[rec.get('from')] = rec.get('to')

        def final(f):
            seen = set()
            while f in renames and f not in seen:
                seen.add(f)
                f = renames[f]
            return f

        for rec in recs:
            if rec.get('type') != 'file':
                continue
            key = (final(rec.get('folder')), rec.get('unit') or '')
            matrix[key] = matrix.get(key, 0) + 1
            if rec.get('empty'):
                empty[key] = empty.get(key, 0) + 1
        return matrix, empty
