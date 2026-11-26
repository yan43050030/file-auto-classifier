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
# 结果目录顶层的工具自身文件(不是归档的材料)
_TOOL_FILES = ('反馈核对表', '文件名对照表', '分类日志_', '整理台账_', '整理报告', '整理历史')


def _top(rel):
    return rel.replace('\\', '/').split('/')[0]


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
                k = (unit_key(rec.get('unit')), rec.get('name'), rec.get('sha1'))
                self._imported.add((self._who(f),) + k)
                if rec.get('auto'):
                    # 预览里手动改归过:按"自动分类结果"也记一份,重新导入时认得出
                    self._imported.add((self._who(rec['auto']),) + k)

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

    def already_imported(self, folder, unit, name, src, dst_candidate=None,
                         auto_folder=''):
        """同一单位、同名、同内容的文件已经导入过 → True(跳过)。

        有归档记录时按记录判断;老版本生成的目录没有记录,则看目标位置
        是否已有同名且内容相同的文件。"""
        try:
            digest = sha1_of(src)
        except OSError:
            return False, ''
        k = (unit_key(unit), name, digest)
        if (self._who(folder),) + k in self._imported:
            return True, digest
        if auto_folder and (self._who(auto_folder),) + k in self._imported:
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

    def record(self, folder, unit, name, digest, category, empty, rel_path,
               auto_folder=''):
        k = (unit_key(unit), name, digest)
        self._imported.add((self._who(folder),) + k)
        self._seq = getattr(self, '_seq', 0) + 1
        rec = {'type': 'file', 'id': f'{datetime.datetime.now():%Y%m%d%H%M%S%f}-{self._seq}',
               'folder': folder, 'unit': unit,
               'name': name, 'sha1': digest, 'category': category,
               'empty': bool(empty), 'path': rel_path}
        if auto_folder and auto_folder != folder:
            self._imported.add((self._who(auto_folder),) + k)
            rec['auto'] = auto_folder          # 自动分类本来要放的位置(手动改归过)
        self._append(rec)

    # ---------- 当前状态(折叠归档记录) ----------

    def current_files(self):
        """把归档记录按时间顺序折叠成"每个文件现在的状态"。

        事件:file(导入)/ rename(工具补全文件夹名)/
              move(同步时发现被你挪动或改名)/ gone(同步时发现已被你删除)。
        返回 {记录id: {folder, unit, name, sha1, path, category, empty, auto, gone, time}}。"""
        state = {}
        for rec in self._read_ledger():
            t = rec.get('type')
            if t == 'file':
                rid = rec.get('id') or rec.get('path')
                state[rid] = {'folder': rec.get('folder'), 'unit': rec.get('unit') or '',
                              'name': rec.get('name') or '', 'sha1': rec.get('sha1'),
                              'path': rec.get('path') or '', 'category': rec.get('category', ''),
                              'empty': bool(rec.get('empty')), 'auto': rec.get('auto', ''),
                              'gone': False, 'time': rec.get('time', '')}
            elif t == 'rename':
                old, new = rec.get('from'), rec.get('to')
                for st in state.values():
                    if st['folder'] == old:
                        st['folder'] = new
                    parts = st['path'].replace('\\', '/').split('/')
                    if parts and parts[0] == old:
                        parts[0] = new
                        st['path'] = os.path.join(*parts)
            elif t == 'move':
                st = state.get(rec.get('id'))
                if st:
                    st['path'] = rec.get('path') or st['path']
                    st['folder'] = rec.get('folder') or st['folder']
                    st['gone'] = False
            elif t == 'gone':
                st = state.get(rec.get('id'))
                if st:
                    st['gone'] = True
        return state

    def file_records(self):
        """全部文件的当前状态,供《文件名对照表》使用。"""
        return [{'time': st['time'], 'unit': st['unit'], 'name': st['name'],
                 'path': st['path'], 'category': st['category'], 'gone': st['gone']}
                for st in self.current_files().values()]

    def cumulative_matrix(self):
        """按归档记录累计:({(人员, 单位): 文件数}, {(人员, 单位): 疑似空值数})。
        文件被你挪到别人文件夹的,计在新的人名下;删掉的仍计入(单位确实反馈过)。"""
        matrix, empty = {}, {}
        for st in self.current_files().values():
            key = (st['folder'], st['unit'])
            matrix[key] = matrix.get(key, 0) + 1
            if st['empty']:
                empty[key] = empty.get(key, 0) + 1
        return matrix, empty

    # ---------- 同步:把你手动做的调整写进记录 ----------

    def sync(self, cancel=None):
        """对照磁盘上的实际情况更新归档记录。返回统计 dict。

        - 记录里的文件不在原位置了:在未登记的文件里找回来
          (先按内容完全相同,再按"文件名包含原文件名"——你加了备注又改了内容也能认出)
          → 记一条 move;找不到 → 记一条 gone(视为你已删除)
        - 未登记的其余文件(你手动放进来的)只统计,不改动。"""
        stats = {'moved': 0, 'gone': 0, 'unregistered': 0, 'checked': 0}
        state = self.current_files()
        if not state:
            return stats
        active = {rid: st for rid, st in state.items() if not st['gone']}
        registered = {os.path.normcase(os.path.normpath(st['path']))
                      for st in active.values()}
        missing = []
        for rid, st in active.items():
            stats['checked'] += 1
            if not os.path.isfile(long_path(os.path.join(self.out_dir, st['path']))):
                missing.append((rid, st))
        unreg = []
        for root, dirs, files in os.walk(long_path(self.out_dir)):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            rel_root = os.path.relpath(root, long_path(self.out_dir))
            for f in files:
                rel = os.path.normpath(os.path.join(rel_root, f))
                if rel_root == '.' and (f == LEDGER_NAME or f.startswith(_TOOL_FILES)):
                    continue
                if os.path.normcase(rel) not in registered:
                    unreg.append(rel)
        if missing:
            self._match_missing(missing, unreg, stats, cancel)
        stats['unregistered'] = len(unreg)
        if stats['moved'] or stats['gone']:
            self.log(f'[同步记录] 你挪动/改名的 {stats["moved"]} 个文件已更新到新位置,'
                     f'{stats["gone"]} 个已不在归档库里(视为你已删除)。')
        return stats

    def _match_missing(self, missing, unreg, stats, cancel):
        hashes = {}

        def digest(rel):
            if rel not in hashes:
                try:
                    hashes[rel] = sha1_of(os.path.join(self.out_dir, rel))
                except OSError:
                    hashes[rel] = None
            return hashes[rel]

        for rid, st in missing:
            if cancel is not None and cancel.is_set():
                return
            hit = next((u for u in unreg if digest(u) == st['sha1']), None)
            if hit is None:
                old = os.path.basename(st['path'])
                stem, ext = os.path.splitext(old)
                cands = [u for u in unreg
                         if os.path.splitext(u)[1].lower() == ext.lower()
                         and stem and stem in os.path.splitext(os.path.basename(u))[0]]
                same_person = [u for u in cands if _top(u) == st['folder']]
                pick = same_person or cands
                hit = pick[0] if len(pick) == 1 else None
            if hit is not None:
                unreg.remove(hit)
                self._append({'type': 'move', 'id': rid, 'path': hit, 'folder': _top(hit)})
                stats['moved'] += 1
            else:
                self._append({'type': 'gone', 'id': rid})
                stats['gone'] += 1
