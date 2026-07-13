# -*- coding: utf-8 -*-
"""智能识别:从大量文件名中自动发现高频人名,并推测姓名与身份证号的对应关系。

基于统计:一个中文 token 如果在很多文件中出现,大概率是人名(而非"报告""证明"等通用词)。
"""

import os
import re
import collections

from .idcard import find_ids, valid_id18, valid_id15, id15_to_18
from .util import safe_folder_name


# ---------- 停用词 ----------
# 文件命名中常见但不是人名的中文词
_STOP_WORDS = set("""
报告 证明 表格 汇总 反馈 通知 函 附件 复印件 材料 文件 登记 申请 审批 回复
扫描件 说明 情况 事项 个人信息 名单 信息 资料 记录 查询 台账 档案 证件
登记表 审批表 反馈表 明细 清单 名册 统计 花名册 一览表 自查 核查 调查
身份证 户口本 房产证 结婚证 学历 学位 职称 工资 银行 账户 凭证 合同
协议 发票 收据 说明函 承诺书 声明 委托书 判决书 裁定书 调解书 决定书
通知单 确认书 告知书 意见书 建议书 申请书 申诉书 复议 答复 回执 复函
表格模板 空表 样例 示例 样本 查询人 被查询人 填报 审批 审核 经办
盖章 签字 扫描 打印 复印 副本 正本 原件 存根 底稿 草稿 修订 最终
有限公司 分公司 部门 科室 单位 处 局 厅 委员会 领导小组 办公室
""".split()) | {str(i) for i in range(1900, 2030)}  # 年份


# 中文姓名分隔符:标点、数字、字母、下划线等
_TOKEN_SEP_RE = re.compile(r'[-_【】\[\]()（）（）\s\dA-Za-z0-9,，.．。:：;；!！?？/\\@#$%^&*+=|~`"\'<>{}]+')
# 纯中文字符
_CHINESE_RE = re.compile(r'^[一-鿿]{2,4}$')


# ---------- 文件名拆分 ----------

def _tokenize_name(fname: str):
    """把一个文件名拆分成可能有意义的中文 token。"""
    # 去扩展名
    base, _ext = os.path.splitext(fname)
    parts = _TOKEN_SEP_RE.split(base)
    tokens = []
    for p in parts:
        p = p.strip()
        if _CHINESE_RE.match(p) and p not in _STOP_WORDS:
            tokens.append(p)
    return tokens


# ---------- 功能 1:高频候选姓名发现 ----------

def detect_names(files, min_freq=10, log=None):
    """扫描文件名列表(每个元素为 (filepath, filename)),返回高频候选姓名列表。
    每项为 {name, count, samples}。"""
    if not files:
        return []
    counts = collections.Counter()
    name_samples = collections.defaultdict(list)  # name -> [sample filenames]

    for item in files:
        _fp, fname = item[0], item[1]    # 兼容 (fp,fname) 或 (fp,fname,unit)
        for tok in _tokenize_name(fname):
            counts[tok] += 1
            if len(name_samples[tok]) < 3:
                name_samples[tok].append(fname)

    detected = []
    for name, cnt in counts.most_common():
        if cnt < min_freq:
            break
        detected.append({
            'name': name,
            'count': cnt,
            'samples': name_samples[name],
        })

    if log and detected:
        log(f'[智能识别] 发现 {len(detected)} 个候选姓名(在 {min_freq}+ 文件中出现):')
        for d in detected:
            samples = '、'.join(d['samples'][:3])
            if len(d['samples']) > 3:
                samples += '…'
            log(f'  {d["name"]} ({d["count"]}文件: {samples})')

    return detected


# ---------- 功能 2:姓名-身份证号关联 ----------

def build_name_id_map(files, known_names, log=None):
    """扫描文件名,找出"姓名+身份证号"同时出现的文件,建立 name↔ID 映射。

    known_names: 已知姓名列表(来自用户名单中的人名 + 候选姓名)。
    returns: dict {name: id_string}
    """
    if not files or not known_names:
        return {}
    pair_counts = collections.Counter()       # (name, id) -> count
    names_seen = set()                         # 用于去重 per 文件

    for item in files:
        _fp, fname = item[0], item[1]    # 兼容 (fp,fname) 或 (fp,fname,unit)
        # 找出本文件中的所有候选姓名
        local_names = []
        for tok in _tokenize_name(fname):
            if tok in known_names and tok not in local_names:
                local_names.append(tok)
        # 找出本文件中的所有身份证号(18位+15位)
        local_ids = []
        seen = set()
        for m in find_ids(fname):
            id_str = m.strip().upper()
            if id_str not in seen:
                # 15位转18位统一
                if valid_id15(id_str):
                    id18 = id15_to_18(id_str)
                    if id18 not in seen:
                        local_ids.append(id18)
                        seen.add(id18)
                elif valid_id18(id_str):
                    local_ids.append(id_str)
                seen.add(id_str)
        # 记录本文件中的 name↔ID 配对
        for n in local_names:
            names_seen.add(n)
            for i in local_ids:
                pair_counts[(n, i)] += 1

    # 每个 name 取频率最高的 ID
    name_to_id = {}
    for (name, id_str), cnt in pair_counts.most_common():
        if name not in name_to_id:
            name_to_id[name] = id_str
    # 建立反向映射:ID → name
    id_to_name = {}
    for name, id_str in name_to_id.items():
        if id_str not in id_to_name:
            id_to_name[id_str] = name

    if log and name_to_id:
        log(f'[智能识别] 从文件名推测出 {len(name_to_id)} 组姓名↔身份证号对应关系:')
        for name, id_str in sorted(name_to_id.items()):
            log(f'  {name} ↔ {id_str}')

    return name_to_id, id_to_name


# ---------- 在分类阶段应用 name-ID 映射 ----------

class IntelligentMatcher:
    """结合名单 + 智能识别(name↔ID 映射 + 候选姓名)进行文件名匹配。"""

    def __init__(self, roster, name_to_id, id_to_name, detected_names=None):
        self.roster = roster
        self.name_to_id = name_to_id or {}
        self.id_to_name = id_to_name or {}
        # 候选姓名(高频但暂无 ID 关联的),也用作独立分类
        self.detected_names = set(detected_names or [])

    def match(self, fname: str):
        """返回 (folder_name, via) 或 None。
        优先级:名单 > name↔ID 映射 > 候选姓名 > None"""
        # 1) 名单匹配
        persons = self.roster.match(fname)
        if persons:
            return persons[0].folder, '名单'

        # 2) name↔ID 映射匹配
        tokens = _tokenize_name(fname)
        ids_in_file = find_ids(fname)

        local_names = [t for t in tokens if t in self.name_to_id]
        local_ids = []
        seen = set()
        for m in ids_in_file:
            i = m.strip().upper()
            if valid_id15(i):
                i = id15_to_18(i)
            if valid_id18(i) and i not in seen:
                local_ids.append(i)
                seen.add(i)

        # 2a) 文件名同时有已知姓名和证号 → 用姓名为主
        for n in local_names:
            mid = self.name_to_id.get(n)
            if mid and mid in local_ids:
                return safe_folder_name(f'{n}_{mid}'), '智能(名+证)'

        # 2b) 文件名仅含已知姓名 → 用映射的证号补全文件夹名
        for n in local_names:
            mid = self.name_to_id.get(n)
            if mid:
                return safe_folder_name(f'{n}_{mid}'), '智能(姓名→证号)'

        # 2c) 文件名仅含已知证号 → 用映射的姓名
        for i in local_ids:
            mname = self.id_to_name.get(i)
            if mname:
                return safe_folder_name(f'{mname}_{i}'), '智能(证号→姓名)'

        # 3) 候选姓名(高频但无证号关联),直接以姓名为文件夹
        for t in tokens:
            if t in self.detected_names:
                return safe_folder_name(t), '智能(候选姓名)'

        return None
