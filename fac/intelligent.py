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
铁路 公路 高铁 地铁 航空 机场 港口 码头 车站 海关 边检 邮政 快递 物流
保险 证券 期货 基金 信托 电力 电信 移动 联通 石油 石化 烟草 燃气
税务 财政 公安 司法 民政 人社 社保 医保 住建 交通 运输 水利 农业 林业
商务 文旅 卫健 应急 审计 市监 城管 环保 能源 教育 科技 工信 发改 国资
不动产 出入境 车管所 供电 供水 供热 自来水
""".split()) | {str(i) for i in range(1900, 2030)}  # 年份

# 地名/区域词(整词排除):省级行政区、常见区域词
_PLACE_WORDS = set("""
中国 中华 全国 国家 国际 华北 华东 华南 华中 西北 西南 东北 中原 沿海
北京 天津 河北 山西 辽宁 吉林 上海 江苏 浙江 安徽 福建 江西 山东 河南
湖北 湖南 广东 广西 海南 重庆 四川 贵州 云南 西藏 陕西 甘肃 青海 宁夏
新疆 香港 澳门 台湾 内蒙古 黑龙江 内蒙 京津冀 长三角 珠三角
""".split())

# 机构/场所后缀(多字,任意长度 token 命中即排除):
# 中国银行、建设银行、保险公司、派出所、财政局 等机构名统统落网
_ORG_SUFFIXES = (
    '银行', '支行', '分行', '总行', '信用社', '公司', '集团', '企业',
    '保险', '证券', '基金', '中心', '协会', '学会', '商会', '工会',
    '医院', '学校', '大学', '学院', '中学', '小学', '幼儿园',
    '法院', '检察院', '派出所', '看守所', '监狱', '交易所', '事务所',
    '营业部', '研究所', '研究院', '设计院', '铁路', '车站', '机场',
    '港口', '地铁', '高速', '超市', '商场', '市场', '酒店', '宾馆',
    '饭店', '药店', '政府', '街道', '社区', '村委', '居委', '大队',
    '支队', '总队', '中队',
)
# 机构后缀(单字,仅对 3-4 字 token 生效:财政局/组织部/办事处/高新区…
# 2 字 token 不适用,避免误伤"孙科"这类真实人名)
_ORG_SUFFIX_CHARS = '局厅部委办处所院站队社厂矿校园馆科会区县市镇乡村街路'

# 职务/称谓后缀(整词或"姓+职务"形式排除:张科长、李主任 不是归档用人名)
_TITLE_SUFFIXES = (
    '科长', '处长', '局长', '厅长', '部长', '主任', '经理', '书记',
    '组长', '队长', '所长', '行长', '校长', '院长', '厂长', '站长',
    '会长', '社长', '镇长', '乡长', '村长', '县长', '市长', '省长',
    '主席', '委员', '秘书', '助理', '专员', '干事',
    '律师', '法官', '检察官', '警官', '民警', '医生', '护士', '老师',
    '教授', '会计', '出纳', '同志', '先生', '女士', '小姐',
)

# 常见中文姓氏(单字,涵盖百家姓与当代常见姓;首字不是姓氏的词基本不可能是人名)
_SURNAMES = set(
    '王李张刘陈杨黄赵吴周徐孙马朱胡郭何林罗高郑梁谢宋唐许韩冯邓曹彭曾肖田董袁潘蒋蔡余于杜叶程苏魏吕丁任沈姚卢姜崔钟谭陆汪范金石廖贾夏韦付方白邹孟熊秦邱江尹薛闫段雷侯龙史陶黎贺顾毛郝龚邵万钱严覃武戴莫孔向汤常温康施文牛樊葛邢安齐易乔伍庞颜倪苗庄聂章鲁岳翟殷詹申欧耿关兰焦俞左柳甘祝包宁尚符舒阮柯纪梅童凌毕单季裴霍涂成苟宇糜谷盛曲路房蒲蒙屈简饶车侯宫湛祁禹狄贝臧计伏井富巫乌巴弓牧隗山全班仰秋仲伊仇栾暴钭厉戎祖景束幸司韶郜蓟薄印宿怀邰从鄂索咸籍赖卓蔺屠池阴郁胥能苍双闻莘党贡劳逄姬扶堵冉宰郦雍却璩桑桂濮寿通边扈燕冀郏浦农别晏柴瞿阎充慕连茹习宦艾鱼容古慎戈庾终暨居衡步都满弘匡国寇广禄阙东殳沃利蔚越夔隆师巩厍晁勾敖融冷訾辛阚那毋沙乜养鞠须丰巢蒯相查后荆红游竺权逯盖益桓公花米海燕'
)
# 复姓
_COMPOUND_SURNAMES = (
    '欧阳', '司马', '上官', '夏侯', '诸葛', '闻人', '东方', '赫连',
    '皇甫', '尉迟', '公羊', '澹台', '公冶', '宗政', '濮阳', '淳于',
    '单于', '太叔', '申屠', '公孙', '仲孙', '轩辕', '令狐', '钟离',
    '宇文', '长孙', '慕容', '鲜于', '闾丘', '司徒', '司空', '司寇',
    '万俟', '子车', '颛孙', '端木', '巫马', '公西', '漆雕', '乐正',
    '拓跋', '夹谷', '宰父', '谷梁', '段干', '百里', '东郭', '南门',
    '呼延', '羊舌', '微生', '梁丘', '左丘', '东门', '西门', '南宫',
)


def is_probable_person_name(token: str) -> bool:
    """多层规则判断一个 2-4 字中文 token 是否可能是人名。

    排除:停用词/地名/机构后缀/职务称谓;
    要求:首字(或前两字)是中文姓氏。
    """
    if not _CHINESE_RE.match(token):
        return False
    if token in _STOP_WORDS or token in _PLACE_WORDS:
        return False
    # 机构/场所后缀:中国银行、保险公司、财政局、高新区…
    if any(token.endswith(s) for s in _ORG_SUFFIXES):
        return False
    if len(token) >= 3 and token[-1] in _ORG_SUFFIX_CHARS:
        return False
    # 职务称谓:张科长、李主任、王律师…(2 字职务词本身也排除)
    if any(token.endswith(s) for s in _TITLE_SUFFIXES):
        return False
    # 姓氏验证:人名必然以姓氏开头
    if len(token) == 4:
        # 4 字:复姓 + 双字名,或"父姓+母姓+双字名"
        return token[:2] in _COMPOUND_SURNAMES or (
            token[0] in _SURNAMES and token[1] in _SURNAMES)
    return token[0] in _SURNAMES or token[:2] in _COMPOUND_SURNAMES


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

def detect_names(files, min_freq=10, exclude=None, log=None):
    """扫描文件名列表(每个元素为 (filepath, filename)),返回高频候选姓名列表。
    每项为 {name, count, samples}。

    exclude: 用户自定义排除词(机构名/项目名等),命中的 token 不会被当成人名。
    候选必须通过 is_probable_person_name 的多层规则(姓氏开头、非机构/地名/职务)。
    """
    if not files:
        return []
    exclude_set = {str(x).strip() for x in (exclude or []) if str(x).strip()}
    counts = collections.Counter()
    name_samples = collections.defaultdict(list)  # name -> [sample filenames]
    rejected = collections.Counter()               # 被排除的高频词(供日志核对)

    for item in files:
        _fp, fname = item[0], item[1]    # 兼容 (fp,fname) 或 (fp,fname,unit)
        for tok in set(_tokenize_name(fname)):     # 同一文件内出现多次只计 1 次
            if tok in exclude_set or not is_probable_person_name(tok):
                rejected[tok] += 1
                continue
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

    if log:
        if detected:
            log(f'[智能识别] 发现 {len(detected)} 个候选姓名(在 {min_freq}+ 文件中出现):')
            for d in detected:
                samples = '、'.join(d['samples'][:3])
                if len(d['samples']) > 3:
                    samples += '…'
                log(f'  {d["name"]} ({d["count"]}文件: {samples})')
        # 高频但被排除的词也报出来,便于发现误杀(真人名可手动加进名单)
        rej_hot = [(t, c) for t, c in rejected.most_common(8) if c >= min_freq]
        if rej_hot:
            log('[智能识别] 以下高频词被判定为非人名(机构/地名/职务等),'
                '如确是人名请加入名单:')
            log('  ' + '、'.join(f'{t}({c})' for t, c in rej_hot))

    return detected


# ---------- 功能 2:姓名-身份证号关联 ----------

def build_name_id_map(files, known_names, log=None):
    """扫描文件名,找出"姓名+身份证号"同时出现的文件,建立 name↔ID 映射。

    known_names: 已知姓名列表(来自用户名单中的人名 + 候选姓名)。
    returns: dict {name: id_string}
    """
    if not files or not known_names:
        return {}, {}
    pair_counts = collections.Counter()       # (name, id) -> 加权计数

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
        # 一个文件里姓名太多(如名单/汇总表),配对无意义,跳过
        if len(local_names) > 3:
            continue
        # 记录本文件中的 name↔ID 配对;"1 名 + 1 证号"是无歧义证据,权重更高
        weight = 3 if (len(local_names) == 1 and len(local_ids) == 1) else 1
        for n in local_names:
            for i in local_ids:
                pair_counts[(n, i)] += weight

    # 每个 name 取加权频率最高的 ID;同一 ID 不允许分给第二个人(先到先得,
    # 后到的低置信配对宁可放弃,避免两个人的材料被合并)
    name_to_id = {}
    id_to_name = {}
    for (name, id_str), _cnt in pair_counts.most_common():
        if name in name_to_id or id_str in id_to_name:
            continue
        name_to_id[name] = id_str
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
