# -*- coding: utf-8 -*-
# 本文件由 scripts/sync_flowcore.py 从 Case Intel 同步生成,请勿手改;
# 需要改识别规则请改 Case Intel 再同步。
# -*- coding: utf-8 -*-
"""银行流水解析（v3.10）：读文件 → 找表头 → 认列 → 逐行解析 → 体检。

为什么单独成模块
----------------
原来的解析散在 bank_import 里，实测一批常见格式全军覆没：
  - GBK 编码的 CSV（国内银行、支付宝导出的默认编码）整份乱码 ——
    解码用了 errors="replace"，UTF-8 永远"成功"，GBK 回退从来没走到；
  - 借方发生额 / 贷方发生额 分两列（对公账户、多数银行柜面打印）→ 0 笔入库；
  - 只有一列"交易时间 2023-01-05 14:23:45" → 日期丢了，存成空串；
  - 查控平台反馈格式（交易卡号 / 收付标志 / 交易对手账卡号 / 对手户名）
    → 对手账号没认出来、"出"没当成支出、日期丢了；
  - .xls（老格式）读不了；银行导出的".xls"其实是网页表格或文本的，也读不了；
  - 括号负数 (1,000.00)、英文表头 → 0 笔；
  - 认不出来的列只能忽略，没有办法手动指定。
而且跳过了多少行、为什么跳过，导入前后都看不到。

这里的原则
----------
1. 能自动认的自动认，认不出或认错的**可以手动指定**，指定过的格式可以**存成模板**，
   下次同样表头自动套用。
2. 导入前就把"会入库多少笔、跳过多少笔、为什么、是哪几行"算清楚给人看，
   不在导入时悄悄丢行。
3. 用**余额连续性**做体检：金额方向对不对、借贷有没有认反，余额一算就知道。
   文件里根本没有方向信息（金额全是正数、也没有借贷列）时，用余额推断每一笔的方向；
   推断不出来的如实列出，不瞎猜。
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from datetime import date as _date
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import pandas as pd

from . import acct_norm as _acct_norm

# ── 标准字段 ──────────────────────────────────────────────────────────
# key: (显示名, 分组, 说明)
FIELDS: dict[str, tuple[str, str, str]] = {
    "tx_date": ("交易日期", "时间", "可以是只有日期，也可以是日期+时间在一格"),
    "tx_time": ("交易时间", "时间", "只有时刻的列；日期时间在一格的选「交易日期」即可"),
    "amount": ("交易金额", "金额", "一列金额：带正负号，或配合「收支方向」列"),
    "amount_out": ("支出金额（借方）", "金额", "收支分两列时的支出列，如 借方发生额"),
    "amount_in": ("收入金额（贷方）", "金额", "收支分两列时的收入列，如 贷方发生额"),
    "direction": ("收支方向", "金额", "借/贷、收/支、进/出、D/C 这类标志列"),
    "balance_after": ("交易后余额", "金额", ""),
    "counterpart": ("对方户名", "对方", ""),
    "counterpart_account": ("对方账号/卡号", "对方", ""),
    "cp_bank": ("对方开户行", "对方", ""),
    "counterpart_phone": ("对方手机号", "对方", ""),
    "counterpart_id_card": ("对方证件号", "对方", ""),
    "remark": ("摘要/用途", "其他", ""),
    "tx_type": ("交易类型", "其他", "转账/消费/取现 这类描述（不是收支方向）"),
    "channel": ("交易渠道", "其他", ""),
    "branch": ("交易网点", "其他", "取现-存现配对要用"),
    "currency": ("币种", "其他", ""),
    "own_account": ("本方账号/卡号", "本方", "查控反馈一个文件里常有多张卡"),
    "own_card": ("本方卡号", "本方", "账号、卡号分两列时的卡号列（如查询卡号）"),
    "own_name": ("本方户名", "本方", ""),
    "own_id": ("本方证件号", "本方", "查控反馈里查询对象的证件号码"),
    "own_bank": ("本方银行", "本方", "如反馈单位"),
    "cash_flag": ("现金标志", "其他", "现金 / 转账；标明现金的按存取现处理"),
    "success": ("交易是否成功", "其他", "失败的交易不导入"),
    "merchant": ("商户名称", "对方", "对方户名为空时用它"),
    "counterpart_card": ("对方卡号", "对方", "对方账号为空时用它"),
    "sub_account": ("子账户", "本方", "同一账号下的定期等子账户分开成单独账户"),
    "deposit_kind": ("储种", "本方", "活期 / 整存整取 / 通知存款……"),
    "term_len": ("存期", "本方", "有存期的是定期"),
    # 网银导出常把收付双方分列（自己有时在付款方、有时在收款方）：按收支方向取另一方当对手
    "payer_name": ("付款人户名", "对方", "收付款人分列时：收入的对方是付款人"),
    "payer_account": ("付款人账号", "对方", "收付款人分列时用"),
    "payee_name": ("收款人户名", "对方", "收付款人分列时：支出的对方是收款人"),
    "payee_account": ("收款人账号", "对方", "收付款人分列时用"),
}

ALIASES: dict[str, list[str]] = {
    "tx_date": ["交易日期", "日期", "记账日期", "记帐日期", "交易日", "业务日期", "入账日期",
                "发生日期", "会计日期", "账务日期", "交易发生日期", "交易时间", "创建时间",
                "付款时间", "交易创建时间", "trade_date", "trans_date", "date", "transaction date",
                "txn date", "posting date", "value date", "txndate", "postdate", "交易日期时间"],
    "tx_time": ["交易时间", "时间", "记账时间", "交易时刻", "发生时间", "trans_time", "time"],
    "amount": ["交易金额", "金额", "发生额", "发生金额", "交易额", "人民币金额", "amount", "txnamt",
               "amt", "transaction amount"],
    "amount_out": ["借方发生额", "借方金额", "借方", "支出金额", "支出", "付款金额", "转出金额",
                   "取款金额", "支取金额", "出账金额", "付出金额", "debit", "debit amount",
                   "withdrawal", "withdrawals", "withdrawal amount"],
    "amount_in": ["贷方发生额", "贷方金额", "贷方", "收入金额", "收入", "收款金额", "转入金额",
                  "存入金额", "存款金额", "入账金额", "credit", "credit amount", "deposit",
                  "deposits", "deposit amount"],
    "direction": ["借贷标志", "借贷标识", "借贷方向", "借贷", "收付标志", "收付方向", "资金方向",
                  "出入账标志", "进出标志", "收支类型", "收/支", "收/付", "收支", "交易方向",
                  "记账方向", "收支标志", "debit_credit", "dc_flag", "dr/cr", "d/c"],
    "balance_after": ["账户余额", "余额", "本次余额", "交易后余额", "交易余额", "联机余额", "可用余额",
                      "当前余额", "账面余额", "balance", "closing balance", "running balance"],
    "counterpart": ["交易对手", "对方户名", "对方名称", "对方姓名", "对手户名", "对手名称", "对手姓名",
                    "对方账户名", "对方账户名称", "交易对手名称", "交易对手户名", "交易对方", "对方",
                    "收款方", "收款人", "交易对象", "对方单位", "payee", "counterparty",
                    "counterpart", "cp_name", "beneficiary"],
    "counterpart_account": ["对方账号", "对方账户", "对手账号", "对方账户号", "对手账卡号",
                            "交易对手账卡号", "交易对手账号", "对方账卡号", "对方帐号",
                            "对方账号卡号", "counterparty account", "counterpart_account", "cp_acct"],
    "counterpart_card": ["对方卡号", "对手卡号", "交易对方卡号", "对方卡号码"],
    "sub_account": ["子账户", "子账号", "子账户号", "子账户序号", "子户号", "子户", "账户序号", "册号", "笔号",
                    "存单号", "存折册号", "子账户编号", "分户号", "子账户号码", "定期序号"],
    "deposit_kind": ["储种", "存款种类", "储蓄种类", "存款类型", "子账户类别", "子账户类型", "储蓄种类名称",
                     "储种名称", "存款品种", "储蓄品种"],
    "term_len": ["存期", "定期存期", "存款期限", "存期代码"],
    "cp_bank": ["对方行名", "对方开户行", "对方银行", "对方开户机构", "对手行名", "对方账户开户行",
                "对方金融机构名称", "对手开户银行", "对方开户行名", "交易对手开户行", "对方账号开户行",
                "对方开户银行", "对方账户开户银行"],
    "counterpart_phone": ["对方手机号", "对手手机", "对方电话", "counterpart_phone"],
    "counterpart_id_card": ["对方身份证号", "对方证件号", "对手身份证", "对手证件号码",
                            "对方证件号码", "counterpart_id_card"],
    "remark": ["摘要", "交易摘要", "摘要说明", "备注", "用途", "附言", "交易附言", "交易备注",
               "摘要描述", "交易用途", "description", "narrative", "memo", "remark",
               "商品", "商品说明", "商品名称", "交易说明"],
    "tx_type": ["交易类型", "业务类型", "类型", "交易种类", "业务种类", "交易名称"],
    "channel": ["交易渠道", "渠道", "交易方式", "支付方式", "交易介质", "交易发生地", "channel"],
    "branch": ["交易网点", "交易网点名称", "交易机构", "交易机构名称", "网点", "网点名称", "营业网点",
               "交易行", "交易行名", "交易地点", "受理机构", "交易营业厅", "交易机构号"],
    "currency": ["币种", "币别", "货币", "currency"],
    "own_account": ["本方账号", "交易账号", "查询账号", "账号", "客户账号"],
    "own_card": ["本方卡号", "查询卡号", "交易卡号", "卡号"],
    "own_name": ["交易户名", "本方户名", "查询户名", "客户名称", "户名", "账户名称", "查询对象名称", "查询对象",
                 "持卡人", "持卡人姓名", "客户姓名"],
    "own_id": ["证件号码", "证件号", "查询对象证件号码", "本方证件号码", "客户证件号码", "持卡人证件号码",
               "身份证号", "身份证号码"],
    "own_bank": ["反馈单位", "反馈银行", "查询银行", "本方开户行", "本方银行", "所属银行"],
    "cash_flag": ["现金标志", "现转标志", "现转", "现金转账标志", "钞汇现转标志"],
    "success": ["交易是否成功", "是否成功", "交易状态", "交易结果", "成功标志", "交易成功标志"],
    "merchant": ["商户名称", "商户名"],
    "payer_name": ["付款人户名", "付款人名称", "付款人姓名", "付款人", "付款方户名", "付款方名称", "付款方",
                   "付款户名", "付款账户名", "付款账户名称", "付款名称", "汇款人", "汇款人户名", "汇款人名称",
                   "转出户名", "转出方户名", "转出方", "转出账户名"],
    "payer_account": ["付款人账号", "付款账号", "付款方账号", "付款人账户", "付款账户", "付款人卡号", "付款卡号",
                      "付款方账户", "汇款人账号", "转出账号", "转出方账号", "转出卡号", "转出账户"],
    "payee_name": ["收款人户名", "收款人名称", "收款人姓名", "收款方户名", "收款方名称", "收款户名",
                   "收款账户名", "收款账户名称", "收款名称", "转入户名", "转入方户名", "转入方", "转入账户名"],
    "payee_account": ["收款人账号", "收款账号", "收款方账号", "收款人账户", "收款账户", "收款人卡号", "收款卡号",
                      "收款方账户", "转入账号", "转入方账号", "转入卡号", "转入账户"],
}


def _norm(s: Any) -> str:
    """表头归一：全角转半角、去空白、去单位括号、英文小写。"""
    t = unicodedata.normalize("NFKC", str(s or "")).strip()
    t = re.sub(r"\s+", "", t)
    t = re.sub(r"[\(\[（【](元|人民币|rmb|cny|万元)[\)\]）】]$", "", t, flags=re.I)
    return t.lower()


_ALIAS_INDEX: dict[str, list[str]] = {}
for _k, _vs in ALIASES.items():
    for _v in _vs:
        _ALIAS_INDEX.setdefault(_norm(_v), []).append(_k)


def _lookup(h: Any) -> list[str]:
    """列名 → 可能的标准字段。先精确匹配；对不上再试常见写法差异：
    交易对方 / 交易对手 / 对手 → 对方，帐 → 账，开头多个"交易"（交易对方名称 → 对方名称）。"""
    n = _norm(h)
    if n in _ALIAS_INDEX:
        return _ALIAS_INDEX[n]
    variants = [n.replace("交易对方", "对方"), n.replace("交易对手", "对方"), n.replace("对手", "对方"),
                n.replace("帐", "账")]
    if n.startswith("交易") and len(n) > 4:
        variants.append(n[2:])
    for v in variants:
        v2 = v.replace("帐", "账")
        for x in (v, v2):
            if x != n and x in _ALIAS_INDEX:
                return _ALIAS_INDEX[x]
    return []


# ── 读文件 ────────────────────────────────────────────────────────────
def _decode(b: bytes) -> tuple[str, str]:
    """严格解码：解不开就换下一个，不能用 replace 把乱码当成功。"""
    if b.startswith(b"\xff\xfe") or b.startswith(b"\xfe\xff"):
        return b.decode("utf-16"), "UTF-16"
    if len(b) > 64 and b[1::2].count(0) > len(b) // 4:     # 无 BOM 的 UTF-16LE
        try:
            return b.decode("utf-16-le"), "UTF-16"
        except UnicodeDecodeError:
            pass
    for enc, label in (("utf-8-sig", "UTF-8"), ("gb18030", "GBK")):
        try:
            return b.decode(enc), label
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace"), "未知（按 UTF-8 容错读取，可能有乱码）"


def _sniff_delim(text: str) -> str:
    lines = [l for l in text.splitlines()[:60] if l.strip()]
    best, best_score = ",", -1
    for d in (",", "\t", "|", ";"):
        counts = [l.count(d) for l in lines]
        counts = [c for c in counts if c > 0]
        if not counts:
            continue
        # 出现的行多、且列数稳定
        common = max(set(counts), key=counts.count)
        score = counts.count(common) * (common >= 2) + len(counts)
        if score > best_score:
            best, best_score = d, score
    return best


def _text_to_df(text: str, delim: str) -> pd.DataFrame:
    # 空行也保留（后面统一删），否则报给人看的行号和文件里对不上
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    if not any(any(c.strip() for c in r) for r in rows):
        return pd.DataFrame()
    w = max(len(r) for r in rows)
    return pd.DataFrame([[c.strip() for c in r] + [""] * (w - len(r)) for r in rows], dtype=str)


def read_sheets(file_bytes: bytes, filename: str = "") -> tuple[list[tuple[str, pd.DataFrame]], dict]:
    """按文件内容（不按扩展名）判断格式，返回 [(工作表名, 原始表)] 和读取信息。"""
    head = file_bytes[:2048]
    meta: dict = {}
    if head.startswith(b"PK\x03\x04"):
        meta["format"] = "Excel（xlsx）"
        book = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None, dtype=str)
    elif head.startswith(b"\xd0\xcf\x11\xe0"):
        meta["format"] = "Excel（xls 老格式）"
        try:
            book = pd.read_excel(io.BytesIO(file_bytes), sheet_name=None, header=None,
                                 dtype=str, engine="xlrd")
        except ImportError:
            raise ValueError("读取 .xls 需要 xlrd 组件，请更新到最新安装包")
    else:
        text, enc = _decode(file_bytes)
        meta["encoding"] = enc
        low = text[:4096].lower()
        if "<table" in low or "<html" in low:
            meta["format"] = "网页表格（扩展名可能是 .xls）"
            tables = pd.read_html(io.StringIO(text), header=None)
            book = {}
            for i, t in enumerate(tables):
                if not isinstance(t.columns, pd.RangeIndex):   # <thead> 里的表头被当成了列名
                    cols = [" ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in t.columns]
                    t = pd.concat([pd.DataFrame([cols]), pd.DataFrame(t.values)], ignore_index=True)
                book[f"表{i + 1}"] = t.astype(str)
        else:
            d = _sniff_delim(text)
            meta["format"] = "文本表格"
            meta["delimiter"] = {",": "逗号", "\t": "制表符", "|": "竖线", ";": "分号"}[d]
            book = {"文本": _text_to_df(text, d)}
    sheets = []
    for name, df in book.items():
        df = df.fillna("").astype(str)
        df = df.map(lambda v: "" if v.strip().lower() in ("nan", "none", "nat") else v.strip())
        # 删空行空列，但保留原始行号（index = 文件里的第几行 - 1），跳过原因要能对回原文件
        df = df.loc[(df != "").any(axis=1), (df != "").any(axis=0)]
        df.columns = range(df.shape[1])
        sheets.append((str(name), df))
    return sheets, meta


# ── 找表头 / 认列 ─────────────────────────────────────────────────────
def _header_score(cells: list[str]) -> int:
    hits = {k for c in cells if c for k in _lookup(c)}
    return len(hits)


def find_header(df: pd.DataFrame, max_scan: int = 40) -> tuple[int, int]:
    """返回 (表头行号, 命中的标准字段数)。说明行通常只有 1~2 格有字，真表头命中多个别名。"""
    best, best_hits = -1, 0
    for i in range(min(max_scan, len(df))):
        cells = [c for c in df.iloc[i].tolist()]
        if sum(1 for c in cells if c) < 3:
            continue
        h = _header_score(cells)
        if h >= 2 and h > best_hits:
            best, best_hits = i, h
    return best, best_hits


def auto_mapping(headers: list[str], filled: Optional[dict] = None) -> dict[str, str]:
    """原始列名 → 标准字段。每个标准字段只给一列；歧义的"交易时间"按有没有日期列来定。

    filled：{列名: 有内容的行数}。同一字段有几列都能对上时，选内容多的那列；
    全空的列不抢字段（查控反馈常有"商户名称""本方卡号"这类整列空着的）。
    """
    cands: dict[str, list[str]] = {}
    for h in headers:
        for k in _lookup(h):
            cands.setdefault(k, []).append(h)
    if filled:
        for k, hs in cands.items():
            hs.sort(key=lambda h: -(filled.get(h) or 0))       # 稳定排序：同样多时保持原来的先后
            if any(filled.get(h) for h in hs):
                cands[k] = [h for h in hs if filled.get(h)]
    m: dict[str, str] = {}
    used: set[str] = set()
    # 先定日期：有专门的日期列就用它，"交易时间"让给时刻
    date_cols = [h for h in cands.get("tx_date", []) if _norm(h) != "交易时间"]
    if date_cols:
        m[date_cols[0]] = "tx_date"
        used.add(date_cols[0])
    elif cands.get("tx_date"):
        m[cands["tx_date"][0]] = "tx_date"
        used.add(cands["tx_date"][0])
    # 别名表里排在前面的优先：同一列只认一个字段
    order = ["amount_out", "amount_in", "amount", "direction", "balance_after",
             "counterpart_account", "counterpart_card", "counterpart", "merchant", "cp_bank",
             "counterpart_phone", "counterpart_id_card", "tx_time", "remark", "tx_type", "channel",
             "branch", "currency", "own_account", "own_card", "own_name", "own_id", "own_bank",
             "cash_flag", "success", "sub_account", "deposit_kind", "term_len",
             "payer_name", "payer_account", "payee_name", "payee_account"]
    for k in order:
        for h in cands.get(k, []):
            if h in used:
                continue
            m[h] = k
            used.add(h)
            break
    # 收付款人分列：有付款人列时，"收款人 / 收款方"是收款一方，不是对手
    have = set(m.values())
    if {"payer_name", "payer_account"} & have:
        for h, f in list(m.items()):
            if f == "counterpart" and _norm(h) in ("收款人", "收款方") and "payee_name" not in have:
                m[h] = "payee_name"
                have = set(m.values())
    # 只有一列"收入"/"支出"、没有另一半时，它不是分列，别乱认
    if ("amount_in" in have) != ("amount_out" in have) and "amount" not in have:
        pass   # 只有收入或只有支出的单边表（比如收入明细），照样按单边处理
    return m


def header_signature(headers: list[str]) -> str:
    return hashlib.sha1("|".join(_norm(h) for h in headers if h).encode("utf-8")).hexdigest()[:16]


# ── 逐格解析 ──────────────────────────────────────────────────────────
# "0/1" 各家银行含义相反，不认；要用的话手动选方向列后在预览里核对余额体检
_OUT_EXACT = {"借", "支", "出", "付", "支出", "转出", "取", "d", "dr", "debit", "-", "减", "付款",
              "出账", "借方", "取款"}
_IN_EXACT = {"贷", "收", "入", "进", "存", "收入", "转入", "c", "cr", "credit", "+", "增", "收款",
             "入账", "贷方", "存款"}


def parse_direction(v: str) -> Optional[int]:
    """-1 支出 / +1 收入 / 0 明确不计收支 / None 认不出。"0/1"只在单独出现时认。"""
    t = _norm(v)
    if not t:
        return None
    if "不计收支" in t or t in ("其他", "中性", "/"):     # 微信账单里中性交易的收/支写 "/"
        return 0
    if t in _OUT_EXACT:
        return -1
    if t in _IN_EXACT:
        return 1
    if any(k in t for k in ("支出", "转出", "付款", "借方", "取款", "出账", "debit")) or t.startswith("借"):
        return -1
    if any(k in t for k in ("收入", "转入", "收款", "贷方", "存款", "入账", "credit")) or t.startswith("贷"):
        return 1
    return None


def parse_amount(v: str) -> Optional[Decimal]:
    """'¥1,000.00' '(1,000.00)' '1000.00-' '－1000' '1.2E+05' → Decimal；空或认不出 → None。"""
    t = unicodedata.normalize("NFKC", str(v or "")).strip()
    if not t:
        return None
    neg = False
    t = t.replace(",", "").replace("¥", "").replace("元", "").replace(" ", "")
    t = re.sub(r"^(rmb|cny)", "", t, flags=re.I)
    m = re.fullmatch(r"\((.+)\)", t)
    if m:
        t, neg = m.group(1), True
    if t.endswith("-") and len(t) > 1:
        t, neg = t[:-1], not neg
    if t.upper().endswith(("DR", "CR")):
        neg = neg or t.upper().endswith("DR")
        t = t[:-2]
    t = t.lstrip("+")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return -d if neg else d


_DT_PATTERNS = [
    (re.compile(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T]+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?(?:\.\d+)?)?$"), "ymdhms"),
    (re.compile(r"^(\d{4})年(\d{1,2})月(\d{1,2})日?(?:(\d{1,2})[:时](\d{1,2})(?:[:分](\d{1,2})秒?)?)?$"), "ymdhms"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})(?:[ T]?(\d{2})(\d{2})(\d{2})?)?$"), "ymdhms"),
    (re.compile(r"^(\d{4})(\d{2})(\d{2})[ T]+(\d{1,2}):(\d{2})(?::(\d{2}))?$"), "ymdhms"),
]
_TIME_PATTERNS = [
    re.compile(r"^(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?(?:\.\d+)?$"),
    re.compile(r"^(\d{1,2})时(\d{1,2})分(?:(\d{1,2})秒)?$"),
    re.compile(r"^(\d{2})(\d{2})(\d{2})$"),
]


def parse_datetime(v: str) -> tuple[Optional[str], Optional[str]]:
    """一格 → (YYYY-MM-DD, HH:MM:SS)，各自可能为 None。"""
    t = unicodedata.normalize("NFKC", str(v or "")).strip()
    if not t:
        return None, None
    for pat, _ in _DT_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if not (1900 <= y <= 2100 and 1 <= mo <= 12 and 1 <= d <= 31):
            continue
        try:
            _date(y, mo, d)                   # 2 月 30 日、6 月 31 日这种不存在的日期不认
        except ValueError:
            continue
        date = f"{y:04d}-{mo:02d}-{d:02d}"
        tm = None
        if m.lastindex and m.lastindex >= 5 and m.group(4) is not None:
            h, mi = int(m.group(4)), int(m.group(5))
            s = int(m.group(6)) if m.lastindex >= 6 and m.group(6) else 0
            if h < 24 and mi < 60 and s < 60:
                tm = f"{h:02d}:{mi:02d}:{s:02d}"
        if tm == "00:00:00" and re.search(r"\s00:00(:00)?$", t):
            tm = None          # Excel 把纯日期读成 "2023-01-05 00:00:00"，不是真的零点
        return date, tm
    # Excel 序列号（单元格设成了数字格式）
    if re.fullmatch(r"\d{5}(\.\d+)?", t):
        f = float(t)
        if 20000 < f < 80000:
            ts = pd.Timestamp("1899-12-30") + pd.Timedelta(days=f)
            return ts.strftime("%Y-%m-%d"), (ts.strftime("%H:%M:%S") if f % 1 else None)
    return None, parse_time(t)


def parse_time(v: str) -> Optional[str]:
    t = unicodedata.normalize("NFKC", str(v or "")).strip()
    for pat in _TIME_PATTERNS:
        m = pat.match(t)
        if m:
            h, mi = int(m.group(1)), int(m.group(2))
            s = int(m.group(3)) if m.group(3) else 0
            if h < 24 and mi < 60 and s < 60:
                return f"{h:02d}:{mi:02d}:{s:02d}"
    return None


def _norm_acct(s: str) -> str:
    """见 acct_norm：去掉"_156"这类人民币后缀，只留字母数字和打码星号。"""
    return _acct_norm.norm_acct(s)


# ── 主流程 ────────────────────────────────────────────────────────────
@dataclass
class ParseResult:
    records: list[dict] = field(default_factory=list)
    skipped: dict = field(default_factory=dict)          # 原因 → [行号]
    warnings: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


SKIP_REASONS = {
    "no_date": "日期认不出",
    "no_amount": "金额为空或认不出",
    "zero": "金额为 0",
    "neutral": "标注为不计收支（如支付宝内部划转）",
    "summary": "合计 / 小计行",
    "repeat_header": "重复的表头行（分页导出）",
    "failed": "交易未成功（交易是否成功 / 交易状态 写明失败）",
}
_FAIL_WORDS = {"否", "失败", "不成功", "未成功", "交易失败", "n", "no", "false", "fail", "failed"}
_GENERIC_REMARK = {"正常", "无", "-", "--", "/", "成功", "交易成功", "null", "none"}


def _is_cash_flag(v: str) -> bool:
    """现金标志："现金交易""现金""现" → 是；"其他""转账""转" → 否。"""
    t = _norm(v)
    return ("现" in t and "转" not in t) or t in ("cash", "c")


def _float_born(s: str) -> bool:
    """这串数字像是 Excel 当成数字存过、精度已经丢了：17 位以上，且恰好是双精度能精确表示的整数
    （15 位以后的数字被补成了 0 或一串凑出来的数）。真号码碰巧满足的概率极低（18 位约 1/128）。"""
    d = re.sub(r"\D", "", s or "")
    if len(d) < 17 or d != s.strip() or d[0] == "0":     # 前导 0 的号码 Excel 存成数字会丢掉 0，不会是这样
        return False
    n = int(d)
    x = float(n)
    # Excel 只存 15 位有效数字：丢过精度的号码，正好等于某个 15 位有效数字换成双精度后的值
    return x == n and int(float(f"{x:.15g}")) == n


def _id_ok(v: str) -> bool:
    t = re.sub(r"\s", "", v or "").upper()
    if not re.fullmatch(r"\d{17}[\dX]", t):
        return False
    w = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
    return "10X98765432"[sum(int(c) * k for c, k in zip(t[:17], w)) % 11] == t[17]


def _merge_lost_precision(res: "ParseResult", own: dict) -> None:
    """本方账号被 Excel 存成数字、丢了精度的那几行（如 906020006669568000），并回真正的账号：
    同一行的卡号能对上某个账户的卡号，或前 15 位只和一个账户相同。对不上的保持原样并提示。"""
    if len(own) < 2:
        return
    majors = {k: o for k, o in own.items() if not _float_born(k)}
    moved: dict[str, str] = {}
    for k, o in list(own.items()):
        if k in majors:
            continue
        target = None
        cards = set(o["_cards"])
        by_card = [m for m, mo in majors.items() if cards & set(mo["_cards"])]
        if len(by_card) == 1:
            target = by_card[0]
        else:
            by_prefix = [m for m in majors if m[:15] == k[:15]]
            if len(by_prefix) == 1:
                target = by_prefix[0]
        if target:
            moved[k] = target
            t = majors[target]
            t["rows"] += o["rows"]
            for key in ("_cards", "_ids", "_banks"):
                for v, n in o[key].items():
                    if not _float_born(v):
                        t[key][v] = t[key].get(v, 0) + n
            del own[k]
    if moved:
        for r in res.records:
            if r["own_account"] in moved:
                r["own_account"] = moved[r["own_account"]]
        res.warnings.append("；".join(f"本方账号 {k} 像是被 Excel 存成数字后丢了精度，已按卡号 / 前 15 位并入 {v}"
                                     for k, v in moved.items()))
    left = [k for k in own if _float_born(k)]
    if left:
        res.warnings.append(f"本方账号 {'、'.join(left)} 像是被 Excel 存成数字后丢了精度，且对不上其他账号，"
                            "按原样单独列出；请核对原始文件")


_CASH_WORDS = ("现存", "现支", "现取", "现开", "现金", "存现", "取现", "ATM取", "ATM存", "柜面取", "柜面存")


def _cash_codes(res: "ParseResult") -> None:
    """现金标志写成代码（农行 0 / 1 之类）时，哪个代码是现金因行而异：看摘要里明说"现存 / 现支"的行用的是哪个代码。

    某个代码的行里一半以上明写着现金、其他代码几乎没有，就认定它是现金；认不出就不用这一列。
    """
    from collections import Counter
    codes, hits = Counter(), Counter()
    for r in res.records:
        c = _norm(r.get("_cf") or "")
        if c and re.fullmatch(r"[0-9a-z]{1,3}", c):
            codes[c] += 1
            if any(w in f"{r['tx_type']}{r['remark']}" for w in _CASH_WORDS):
                hits[c] += 1
    cash = None
    if len(codes) >= 2:
        share = {c: hits[c] / n for c, n in codes.items()}
        top = max(share, key=share.get)
        if share[top] >= 0.5 and all(v < 0.2 for c, v in share.items() if c != top):
            cash = top
    for r in res.records:
        c = _norm(r.pop("_cf", "") or "")
        if cash and c == cash:
            if "现金" not in r["channel"]:
                r["channel"] = f"{r['channel']} 现金".strip()[:64]
            if len(_norm_acct(r["counterpart_account"])) < 6:
                r["counterpart_account"] = ""
    if cash:
        res.meta["cash_flag_code"] = cash
        res.warnings.append(f"现金标志是代码：按摘要里写明现存 / 现支的行推断「{cash}」= 现金，"
                            f"共 {codes[cash]} 笔按存取现处理")
    elif codes:
        res.meta["cash_flag_code"] = None


def _own_from_opening(res: "ParseResult") -> None:
    """流水里没有户名 / 证件号（农行等把开户信息放在另一张表）：按账号或卡号从开户信息表补上。"""
    recs = res.meta.get("opening_records") or []
    if not recs:
        return
    for o in res.meta.get("own_accounts", []):
        rec = match_opening(recs, [o["account"], o.get("card", "")])
        if not rec:
            continue
        if not o.get("name") and rec.get("open_name"):
            o["name"] = rec["open_name"]
        if not o.get("id") and _id_ok(rec.get("open_id", "")):
            o["id"] = rec["open_id"]
        if rec.get("bank_name"):          # 开户信息表是银行自己的账户资料，以它为准
            o["bank"] = _canonical_bank(rec["bank_name"]) or rec["bank_name"]
        card = rec.get("card_no", "")
        if not o.get("card") and card and _norm_acct(card) != _norm_acct(o["account"]):
            o["card"] = card


def _canonical_bank(text: str) -> Optional[str]:
    from .bankname import canonical_bank
    return canonical_bank(text)


def _order_same_day(res: "ParseResult") -> None:
    """只有日期没有时刻时，同一天几笔的先后在文件里常是乱的：按余额把它们串起来排好。

    同一账户、同一日期（且同一时刻）的一组，能用"上一笔余额 + 本笔金额 = 本笔余额"一笔不漏串成一条链，
    才按链重排；串不起来就保持原样。文件整体倒序的，组内也排成倒序。
    """
    recs = res.records
    by_acct: dict[str, list[int]] = {}
    for i, r in enumerate(recs):
        by_acct.setdefault(r.get("own_account") or "", []).append(i)
    days = 0
    for idxs in by_acct.values():
        dates = [recs[i]["tx_date"] for i in idxs]
        desc = sum(a > b for a, b in zip(dates, dates[1:])) > sum(a < b for a, b in zip(dates, dates[1:]))
        runs, cur = [], [idxs[0]] if idxs else []
        for i in idxs[1:]:
            p, q = recs[cur[-1]], recs[i]
            if (q["tx_date"], q["tx_time"]) == (p["tx_date"], p["tx_time"]):
                cur.append(i)
            else:
                runs.append(cur)
                cur = [i]
        if cur:
            runs.append(cur)
        prev_bal = None
        for run in (runs[::-1] if desc else runs):
            group = [recs[i] for i in run]
            if len(group) >= 2 and all(r["balance_after"] is not None for r in group):
                chain = _balance_chain(group, prev_bal)
                if chain is not None:
                    if desc:
                        chain = chain[::-1]
                    if [id(r) for r in chain] != [id(r) for r in group]:
                        for i, r in zip(run, chain):
                            recs[i] = r
                        days += 1
            last = [recs[i] for i in run]
            prev_bal = (last[0] if desc else last[-1])["balance_after"]
    if days:
        res.meta["reordered_days"] = days
        res.warnings.append(f"有 {days} 天的流水只有日期、同一天内先后是乱的，已按余额前后衔接重新排好顺序")


def _balance_chain(group: list[dict], prev_bal) -> Optional[list[dict]]:
    """把一组流水排成"余额 = 上一笔余额 + 金额"的链（时间正序）。排不出返回 None。"""
    n = len(group)
    if n > 200:
        return None
    before = [r["balance_after"] - r["amount"] for r in group]
    after = [r["balance_after"] for r in group]
    # 起点优先级：接得上前一天的余额 > 余额不是本组任何一笔的结果 > 账户第一天从 0 开始（开户存入）> 其余
    starts = [i for i in range(n) if prev_bal is not None and before[i] == prev_bal]
    starts += [i for i in range(n) if i not in starts and before[i] not in after]
    starts += [i for i in range(n) if i not in starts and prev_bal is None and before[i] == 0]
    starts += [i for i in range(n) if i not in starts]
    budget = [5000]

    def dfs(path: list[int], used: set) -> Optional[list[int]]:
        if len(path) == n:
            return path
        budget[0] -= 1
        if budget[0] < 0:
            return None
        last = after[path[-1]]
        for j in range(n):
            if j not in used and before[j] == last:
                got = dfs(path + [j], used | {j})
                if got:
                    return got
        return None

    for s0 in starts:
        got = dfs([s0], {s0})
        if got:
            return [group[i] for i in got]
        if budget[0] < 0:
            break
    return None


_TERM_WORDS = ("定期", "整存整取", "零存整取", "存本取息", "定活两便", "通知", "存单", "教育储蓄", "整整", "零整")


def _is_term_row(r: dict) -> bool:
    k = r.get("_dkind") or ""
    t = _norm(r.get("_tlen") or "")
    return any(w in k for w in _TERM_WORDS) or (bool(t) and t not in ("0", "00", "000", "活期"))


def _split_sub_accounts(res: "ParseResult", own: dict) -> None:
    """同一账号下有几个子账户（活期 + 一笔笔定期，常见于册号 / 子账户序号列）：各自余额独立，
    混在一个账户里余额对不上、转定期和定期开户还会重复计数。拆成"账号-子账户"单独的账户，标明储种。
    只有一个子账户但写着定期 / 有存期的，整个账户标成定期。"""
    rows_of: dict[str, list[dict]] = {}
    for r in res.records:
        rows_of.setdefault(r["own_account"], []).append(r)
    split = 0
    for oa, rs in rows_of.items():
        subs: dict[str, list[dict]] = {}
        for r in rs:
            subs.setdefault(r.get("_sub") or "", []).append(r)
        if len(subs) < 2:
            if oa in own and rs and sum(_is_term_row(r) for r in rs) > len(rs) / 2:
                own[oa]["kind"] = next((r["_dkind"] for r in rs if r.get("_dkind")), "") or "定期"
            continue
        # 活期那个子账户留在原账号上：不是定期的里面笔数最多的；全是定期就留笔数最多的
        def score(item):
            k, v = item
            return (sum(not _is_term_row(r) for r in v) > len(v) / 2, len(v))
        main = max(subs.items(), key=score)[0]
        base = own.get(oa)
        for sub, v in subs.items():
            if sub == main:
                continue
            key = f"{oa}-{sub}" if sub else f"{oa}-0"
            for r in v:
                r["own_account"] = key
            kind = next((r["_dkind"] for r in v if r.get("_dkind")), "") or \
                ("定期" if any(_is_term_row(r) for r in v) else "子账户")
            own[key] = {"account": key, "name": base["name"] if base else "", "rows": len(v),
                        "_cards": {}, "_ids": dict(base["_ids"]) if base else {},
                        "_banks": dict(base["_banks"]) if base else {}, "kind": kind, "sub_of": oa}
            if base:
                base["rows"] -= len(v)
            split += 1
    for r in res.records:
        for k in ("_sub", "_dkind", "_tlen"):
            r.pop(k, None)
    if split:
        res.warnings.append(f"有 {split} 个子账户（定期等）和主账户写在同一账号下，已按子账户拆成单独的账户"
                            "（账号后加子账户号），各自核对余额；本人活期和定期之间的转存不算收支")


_RMB = ("人民币", "cny", "rmb", "156", "本币", "", "人民币元", "rmb元")
_FX = {"美元": "USD", "usd": "USD", "840": "USD", "美金": "USD", "欧元": "EUR", "eur": "EUR", "978": "EUR",
       "港币": "HKD", "港元": "HKD", "hkd": "HKD", "344": "HKD", "日元": "JPY", "jpy": "JPY", "392": "JPY",
       "英镑": "GBP", "gbp": "GBP", "826": "GBP", "澳元": "AUD", "aud": "AUD", "加元": "CAD", "cad": "CAD",
       "新加坡元": "SGD", "sgd": "SGD", "瑞士法郎": "CHF", "chf": "CHF", "澳门元": "MOP", "mop": "MOP",
       "韩元": "KRW", "krw": "KRW", "新台币": "TWD", "twd": "TWD"}
FX_NAMES = {"USD": "美元", "EUR": "欧元", "HKD": "港币", "JPY": "日元", "GBP": "英镑", "AUD": "澳元",
            "CAD": "加元", "SGD": "新加坡元", "CHF": "瑞士法郎", "MOP": "澳门元", "KRW": "韩元", "TWD": "新台币",
            "FX": "外币"}


def _split_acct_suffix(s: str) -> tuple[str, str]:
    return _acct_norm.split_suffix(s)


def _fx_code(cur: str) -> str:
    """币种 → 外币代码（人民币 / 空 → ""）。"现钞 / 现汇"这类后缀不影响。"""
    n = re.sub(r"(现钞|现汇|钞|汇|户)$", "", _norm(cur))
    if n in _RMB:
        return ""
    return _FX.get(n) or ("FX" if n else "")


def _split_currency(res: "ParseResult", own: dict) -> None:
    """同一账号下的外币：余额是各币种分开记的，混进人民币里余额对不上、收支合计也错。
    拆成"账号-USD"这类单独的账户（金额按原币，不换算）。"""
    moved: dict[str, int] = {}
    for r in res.records:
        code = r.get("_fx") or ""
        if not code:
            continue
        oa = r["own_account"] or ""
        key = f"{oa}-{code}"
        r["own_account"] = key
        if key not in own:
            base = own.get(oa)
            own[key] = {"account": key, "name": base["name"] if base else "", "rows": 0,
                        "_cards": {}, "_ids": dict(base["_ids"]) if base else {},
                        "_banks": dict(base["_banks"]) if base else {},
                        "kind": f"外币（{FX_NAMES.get(code, code)}）", "sub_of": oa, "currency": code}
        own[key]["rows"] += 1
        if oa in own:
            own[oa]["rows"] -= 1
        moved[code] = moved.get(code, 0) + 1
    for k in [k for k, o in own.items() if o["rows"] <= 0 and not o.get("sub_of")]:
        if not any(r["own_account"] == k for r in res.records):
            own.pop(k)
    if moved:
        res.meta["fx_split"] = moved
        res.warnings.append("外币交易已和人民币分开，单独成账户（账号后加币种代码，金额按原币、不换算）："
                            + "、".join(f"{FX_NAMES.get(c, c)} {n} 笔" for c, n in moved.items()))


def _finish_own(own: dict, res: "ParseResult") -> dict:
    """每个本方账号：卡号、证件号、银行取出现最多的那个；丢了精度的卡号、校验位不对的证件号不用。"""
    lost_cards, bad_ids = set(), set()
    for o in own.values():
        cards = {}
        for c, n in o.pop("_cards").items():
            if _float_born(c):
                lost_cards.add(c)
            else:
                cards[c] = n
        ids = o.pop("_ids")
        good_ids = {i: n for i, n in ids.items() if _id_ok(i) and not _float_born(i)}
        bad_ids |= set(ids) - set(good_ids)
        banks = o.pop("_banks")
        o["card"] = max(cards, key=cards.get) if cards else ""
        o["id"] = max(good_ids, key=good_ids.get) if len(good_ids) == 1 else ""
        o["bank"] = max(banks, key=banks.get) if banks else ""
    if lost_cards:
        res.warnings.append(f"卡号 {'、'.join(sorted(lost_cards))} 像是被 Excel 存成数字后丢了精度，没有采用")
    if bad_ids:
        res.warnings.append(f"证件号码 {'、'.join(sorted(bad_ids))} 校验位不对或被 Excel 存成数字丢了精度，"
                            "没有写进开户信息；请核对原始文件")
    return own


def parse_statement(file_bytes: bytes, filename: str = "", options: Optional[dict] = None,
                    templates: Optional[dict] = None) -> ParseResult:
    """options（全部可选）:
        mapping      {原始列名: 标准字段 或 ""(忽略)}，给了就以它为准（未列出的列按自动识别）
        header_row   表头在第几行（从 1 数，指选中的工作表）
        sheet        只读哪个工作表（默认：自动选表头最像的，并合并表头相同的其他表）
        sign         auto / as_is / flip   金额方向
        only_own_account  只导入这个本方账号的行（文件里有多张卡时）
    templates: {签名: 模板 options}，没有手动 mapping 时按表头签名自动套用。
    """
    opts = dict(options or {})
    res = ParseResult()
    sheets, meta = read_sheets(file_bytes, filename)
    res.meta.update(meta)
    if not sheets or all(df.empty for _, df in sheets):
        raise ValueError("文件里没有读到任何表格内容")

    # 1. 选工作表 + 表头
    found = []
    for name, df in sheets:
        if opts.get("sheet") and name != opts["sheet"]:
            continue
        if opts.get("header_row"):
            # 用户给的是打开文件时看到的行号
            pos = list(df.index).index(int(opts["header_row"]) - 1) \
                if int(opts["header_row"]) - 1 in df.index else -1
            if pos < 0:
                raise ValueError(f"第 {opts['header_row']} 行是空行或不存在")
            found.append((name, df, pos, _header_score(df.iloc[pos].tolist())))
        else:
            hr, hits = find_header(df)
            found.append((name, df, hr, hits))
    if not found:
        raise ValueError(f"没有名为「{opts.get('sheet')}」的工作表")
    main = max(found, key=lambda x: (x[3], len(x[1])))
    name, df, hr, hits = main
    if hr < 0 or hr >= len(df):
        hr = 0
        res.warnings.append("没认出表头行，暂按第 1 行当表头 —— 请在下方指定表头所在行，并手动对应各列")
    headers = [str(h) for h in df.iloc[hr].tolist()]
    # 空表头补名，重名加序号
    seen: dict[str, int] = {}
    for i, h in enumerate(headers):
        h = h or f"第{i + 1}列"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        headers[i] = h
    sig = header_signature(headers)
    body_parts = [(name, df.iloc[hr + 1:])]
    used_sheets = [name]
    skipped_sheets = []
    for n2, d2, hr2, _ in found:
        if n2 == name:
            continue
        if hr2 >= 0 and header_signature([str(x) for x in d2.iloc[hr2].tolist()]) == sig:
            body_parts.append((n2, d2.iloc[hr2 + 1:]))
            used_sheets.append(n2)
        elif not d2.empty:
            skipped_sheets.append(n2)
    res.meta.update({
        "sheet": name, "sheets_used": used_sheets, "sheets_skipped": skipped_sheets,
        "header_row": int(df.index[hr]) + 1, "headers": headers, "signature": sig,
        "header_rows": df.iloc[:hr].copy(),
    })
    # 其他工作表里如果是开户信息，读出来（不算"没读取"）
    res.meta["opening_records"] = opening_from_sheets(
        [(n, d) for n, d in sheets if n in skipped_sheets], set())
    res.meta["opening_header"] = extract_open_kv(df.iloc[:hr])
    open_sheets = {r["_sheet"] for r in res.meta["opening_records"]}
    skipped_sheets = [n for n in skipped_sheets if n not in open_sheets]
    res.meta["sheets_skipped"] = skipped_sheets
    if open_sheets:
        res.meta["opening_sheets"] = sorted(open_sheets)
    if skipped_sheets:
        res.warnings.append(f"工作表 {'、'.join(skipped_sheets)} 的表头和主表不同，没有读取；需要的话单独选它导入")

    # 2. 列映射：手动 > 模板 > 自动
    body = df.iloc[hr + 1:]
    filled = {h: int((body[i] != "").sum()) if i in body.columns else 0 for i, h in enumerate(headers)}
    auto = auto_mapping(headers, filled)
    tpl = (templates or {}).get(sig)
    mapping = dict(auto)
    source = "auto"
    if tpl and not opts.get("mapping"):
        mapping = {h: f for h, f in (tpl.get("mapping") or {}).items() if h in headers and f}
        for k in ("sign",):
            opts.setdefault(k, tpl.get(k))
        source = "template"
    if opts.get("mapping"):
        manual = {h: f for h, f in opts["mapping"].items() if h in headers}
        for h, f in manual.items():
            mapping.pop(h, None)
            if f:
                # 一个标准字段只能对应一列：手动指定的顶掉自动的
                for other, ff in list(mapping.items()):
                    if ff == f:
                        mapping.pop(other)
                mapping[h] = f
        source = "manual"
    bad = {f for f in mapping.values() if f not in FIELDS}
    if bad:
        raise ValueError(f"未知的字段：{'、'.join(bad)}")
    res.meta.update({"mapping": mapping, "auto_mapping": auto, "mapping_source": source,
                     "template": tpl and {"id": tpl.get("id"), "name": tpl.get("name")}})
    col_of = {f: headers.index(h) for h, f in mapping.items()}
    # 没有单独的本方账号列、只有卡号列时，卡号就是本方账号
    if "own_card" in col_of and "own_account" not in col_of:
        col_of["own_account"] = col_of["own_card"]
    have = set(col_of)
    if "tx_date" not in have:
        res.warnings.append("没有对应「交易日期」的列，无法导入 —— 请手动指定")
    if not ({"amount", "amount_in", "amount_out"} & have):
        res.warnings.append("没有对应金额的列（交易金额，或 收入/支出 两列），无法导入 —— 请手动指定")

    # 3. 逐行
    dir_source = ("收支分两列" if {"amount_in", "amount_out"} & have and "amount" not in have
                  else "收支方向列" if "direction" in have else "金额正负号")
    norm_headers = {_norm(h) for h in headers}
    unknown_dir = 0
    type_dir = False
    sci = 0
    bad_time = 0
    failed = 0
    currencies: dict[str, int] = {}
    own: dict[str, dict] = {}
    split_parties = bool({"payer_name", "payer_account", "payee_name", "payee_account"} & have)
    suffixed = 0
    # 金额列标着"万元"的（汇总表、部分对公打印）：按万元换成元，Decimal 精确相乘
    scale = {f: Decimal(10000) for f in ("amount", "amount_in", "amount_out", "balance_after")
             if f in col_of and re.search(r"万元|[（(]万[)）]|万$", str(headers[col_of[f]]))}

    def pa(f: str):
        x = parse_amount(g(f))
        return x * scale[f] if x is not None and f in scale else x
    if scale:
        res.warnings.append("金额单位是「万元」（" + "、".join(str(headers[col_of[f]]) for f in scale)
                            + "），已乘以 10000 换算成元")
    party_flip = 0
    for part_name, part in body_parts:
        for idx, row in part.iterrows():
            cells = [str(x) for x in row.tolist()] + [""] * (len(headers) - len(row))
            row_no = int(idx) + 1 if part_name == name else f"{part_name}!{int(idx) + 1}"
            g = lambda f: cells[col_of[f]].strip() if f in col_of and col_of[f] < len(cells) else ""  # noqa: E731
            if {_norm(c) for c in cells if c} and {_norm(c) for c in cells if c} <= norm_headers:
                res.skipped.setdefault("repeat_header", []).append(row_no)
                continue
            sv = g("success")
            if sv and _norm(sv) in _FAIL_WORDS:
                res.skipped.setdefault("failed", []).append(row_no)
                continue
            date, tm = parse_datetime(g("tx_date"))
            if date and not tm and re.fullmatch(r"\d{14}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2}[ T]\S+", g("tx_date")):
                bad_time += 1          # 日期认得出、时刻不合法（如 09:43:62）：保留日期
            if "tx_time" in col_of:
                t2 = parse_time(g("tx_time")) or parse_datetime(g("tx_time"))[1]
                tm = t2 or tm
                if not date:
                    date = parse_datetime(g("tx_time"))[0]
            if not date:
                # 合计行一般没有日期；只在日期认不出时才归为合计行，免得误伤正常交易
                summ = re.search(r"(合计|小计|总计|本页|累计|笔数)", "".join(cells))
                res.skipped.setdefault("summary" if summ else "no_date", []).append(row_no)
                continue
            # 金额 + 方向
            if "amount" in col_of:
                amt = pa("amount")
                if amt is None and ({"amount_in", "amount_out"} & have):
                    amt = (pa("amount_in") or 0) - (pa("amount_out") or 0)
            else:
                ai, ao = pa("amount_in"), pa("amount_out")
                # 支出列里有的银行写正数、有的写负数，一律当支出
                amt = None if ai is None and ao is None else (ai or 0) - abs(ao or 0)
            if amt is None:
                res.skipped.setdefault("no_amount", []).append(row_no)
                continue
            d = parse_direction(g("direction")) if "direction" in col_of else None
            if d is None and "direction" not in col_of and "amount" in col_of and "tx_type" in col_of:
                # 没有专门的方向列时，"交易类型 = 转账支出"这类也能定方向（只认明确的收/支字样）
                dt_ = parse_direction(g("tx_type"))
                if dt_ in (1, -1):
                    d = dt_
                    type_dir = True
            if d == 0:
                res.skipped.setdefault("neutral", []).append(row_no)
                continue
            if "amount" in col_of and d in (1, -1, None):
                if d == -1:
                    amt = -abs(amt)
                elif d == 1:
                    amt = abs(amt)
                elif "direction" in col_of and g("direction"):
                    unknown_dir += 1
            if amt == 0:
                res.skipped.setdefault("zero", []).append(row_no)
                continue
            bal = pa("balance_after")
            cur = g("currency")
            if cur:
                currencies[cur] = currencies.get(cur, 0) + 1
            if re.fullmatch(r"\d(\.\d+)?[eE]\+\d+", g("counterpart_account")):
                sci += 1
            # 本方账号挂着币种后缀（"…_156"、"…_840_1"）：人民币的去掉；外币的按币种另成子账户
            own_raw = g("own_account") or g("own_card")
            obase, ocur = _split_acct_suffix(own_raw)
            if ocur:
                suffixed += 1
                if ocur != "CNY" and not cur:
                    cur = FX_NAMES.get(ocur, ocur)
                    currencies[cur] = currencies.get(cur, 0) + 1
                own_raw = obase
            oa = _norm_acct(own_raw)
            card = _norm_acct(_split_acct_suffix(g("own_card"))[0])
            if oa:
                o = own.setdefault(oa, {"account": own_raw, "name": g("own_name"),
                                        "rows": 0, "_cards": {}, "_ids": {}, "_banks": {}})
                o["rows"] += 1
                if not o["name"] and g("own_name"):
                    o["name"] = g("own_name")
                for key, v in (("_cards", card if card != oa else ""), ("_ids", g("own_id")),
                               ("_banks", g("own_bank"))):
                    if v:
                        o[key][v] = o[key].get(v, 0) + 1
            raw = {h: c for h, c in zip(headers, cells) if c}
            for f in ("branch", "cp_bank", "currency"):
                if g(f):
                    raw[f] = g(f)
            # 交易类型（工资、消费、ATM取款……）比借贷标志（出 / 进）有用得多：方向已经体现在金额正负上
            tt = g("tx_type")
            rm = g("remark")
            if _norm(rm) in _GENERIC_REMARK or re.fullmatch(r"[\d\s.\-/]+", rm):
                rm = ""                     # "0 8 0 1" 这类摘要代码看不懂，用交易类型；原值在原始数据里
            ch = g("channel")
            cf = g("cash_flag")
            cp_name = g("counterpart") or g("merchant")
            cp_acct = g("counterpart_account") or g("counterpart_card")
            if not cp_name and not cp_acct and split_parties:
                # 收付款人分列：收入的对方是付款人，支出的对方是收款人（自己在另一边）
                side = "payer" if amt > 0 else "payee"
                cp_name, cp_acct = g(f"{side}_name"), g(f"{side}_account")
                other = "payee" if side == "payer" else "payer"
                if oa and _norm_acct(cp_acct) == oa and _norm_acct(g(f"{other}_account")) != oa:
                    cp_name, cp_acct = g(f"{other}_name"), g(f"{other}_account")   # 方向写反了的少数行
                    party_flip += 1
            if not cp_acct and re.search(r"ATM|自动柜员|自助取款|自助存款", f"{tt}{ch}", re.I) \
                    and "转" not in f"{tt}{rm}" and "现金" not in ch:
                ch = f"{ch} 现金".strip()           # ATM 上没有对方账号的存取 = 存取现
            if cf and _is_cash_flag(cf):
                if "现金" not in ch:
                    ch = f"{ch} 现金".strip()       # 现金标志 → 渠道里带"现金"，存取现识别据此
                # 柜面他人代存的现金汇款：对方户名是存款人，"对方账号"常是 1、3 这类占位，不是账户；
                # 留着会把它当成转账，追不到之前的取现。原值仍在原始数据里
                if len(_norm_acct(cp_acct)) < 6:
                    cp_acct = ""
            res.records.append({
                "row_no": row_no, "tx_date": date, "tx_time": tm or "",
                "amount": amt, "balance_after": bal,
                "counterpart": cp_name,
                "counterpart_account": cp_acct,
                "tx_type": (tt or g("direction"))[:16], "channel": ch[:64],
                "remark": rm or tt or g("remark"),
                "own_card": card,
                "counterpart_phone": g("counterpart_phone"),
                "counterpart_id_card": g("counterpart_id_card"),
                "own_account": oa, "raw": raw, "_cf": cf,
                "_fx": _fx_code(cur),
                "_sub": _norm_acct(g("sub_account")), "_dkind": g("deposit_kind"), "_tlen": g("term_len"),
                # 旧版指纹用的原始字符串，重复导入同一文件时也能认出来
                "legacy_date": g("tx_date")[:32], "legacy_time": g("tx_time")[:16],
            })
    _merge_lost_precision(res, own)
    _split_sub_accounts(res, own)
    _split_currency(res, own)
    if opts.get("only_own_account"):
        keep = _norm_acct(opts["only_own_account"])
        before = len(res.records)
        res.records = [r for r in res.records if r["own_account"] == keep]
        res.warnings.append(f"只导入本方账号 {opts['only_own_account']} 的 {len(res.records)} 笔，"
                            f"其余 {before - len(res.records)} 笔不属于它")
    if sci:
        res.warnings.append(f"有 {sci} 笔的对方账号是科学计数法（如 6.22E+18）—— 在 Excel 里被当成数字存了，"
                            "后几位已经丢失，无法据此匹配账户。请向银行要原始导出文件，或把该列设成文本后重新导出")
    if bad_time:
        res.warnings.append(f"有 {bad_time} 笔的交易时刻不合法（如 09:43:62），只保留了日期")
    if type_dir and dir_source == "金额正负号":
        dir_source = "交易类型里的收/支字样"
    if suffixed:
        res.warnings.append(f"有 {suffixed} 笔的本方账号后面挂着币种后缀（如「_156」），已按去掉后缀的账号认 ——"
                            "这样交易对方写的正常账号也能对上；原写法保留在原始数据里")
    if party_flip:
        res.warnings.append(f"有 {party_flip} 笔收付款人与收支方向对不上（本方账号出现在对方一侧），已按本方账号取另一方")
    if unknown_dir:
        res.warnings.append(f"有 {unknown_dir} 笔的收支方向列内容认不出，按金额原本的正负号处理")
    if len([o for o in own.values() if not o.get("sub_of")]) > 1 and not opts.get("only_own_account"):
        res.warnings.append(f"文件里有 {len([o for o in own.values() if not o.get('sub_of')])} 个不同的本方账号/卡号，全导进一个账户会混在一起 —— "
                            "可以选「按本方账号拆成多个账户」，或只导入其中一个")
    foreign = {c: n for c, n in currencies.items() if _fx_code(c)}
    if foreign and not res.meta.get("fx_split"):
        res.warnings.append("含外币交易：" + "、".join(f"{c} {n} 笔" for c, n in foreign.items())
                            + "。金额按原币记录，没有换算成人民币")
    _cash_codes(res)
    res.meta["own_accounts"] = sorted(_finish_own(own, res).values(), key=lambda o: -o["rows"])
    _own_from_opening(res)
    _order_same_day(res)
    res.meta["direction_source"] = dir_source

    # 4. 余额体检 / 方向推断
    _balance_check(res, opts.get("sign") or "auto", dir_source)
    return res


def _continuity(recs: list[dict], sign: int = 1) -> tuple[int, int]:
    """相邻两笔的余额差是否正好等于金额：返回 (对得上, 可检查)。文件正序倒序都试，取好的。"""
    best = (0, 0)
    for seq in (recs, recs[::-1]):
        ok = n = 0
        for p, q in zip(seq, seq[1:]):
            if p["balance_after"] is None or q["balance_after"] is None:
                continue
            n += 1
            if q["balance_after"] - p["balance_after"] == q["amount"] * sign:
                ok += 1
        if ok > best[0] or n > best[1] and ok == best[0]:
            best = (ok, n)
    return best


def _continuity_by_account(recs: list[dict], sign: int = 1) -> tuple[int, int]:
    """一个文件里有几个本方账号（查控反馈常见）时，各账户分开核对余额，再加总。"""
    groups: dict[str, list] = {}
    for r in recs:
        groups.setdefault(r.get("own_account") or "", []).append(r)
    ok = n = 0
    for g in groups.values():
        a, b = _continuity(g, sign)
        ok, n = ok + a, n + b
    return ok, n


def _balance_check(res: ParseResult, sign_opt: str, dir_source: str) -> None:
    recs = res.records
    if sign_opt == "flip":
        for r in recs:
            r["amount"] = -r["amount"]
    ok, n = _continuity_by_account(recs)
    chk = {"checked": n, "consistent": ok}
    # 文件没有任何方向信息（金额全为正、没有借贷列、也没分列）→ 用余额推断每笔方向
    no_dir_info = dir_source == "金额正负号" and recs and all(r["amount"] > 0 for r in recs)
    if no_dir_info and n and sign_opt == "auto":
        fixed, unsure = _infer_direction(recs)
        ok, n = _continuity(recs)
        chk.update({"checked": n, "consistent": ok, "inferred_direction": fixed,
                    "direction_unsure": unsure})
        res.meta["direction_source"] = "按余额变化推断"
        res.warnings.append(
            f"文件里没有收支方向（金额都是正数，也没有借贷列），已按前后余额的变化推断出 {fixed} 笔的方向"
            + (f"；另有 {unsure} 笔推断不出，暂按收入处理，请核对或手动指定方向列" if unsure else ""))
    elif n >= 5:
        flipped_ok, _ = _continuity_by_account(recs, -1)
        chk["flipped_consistent"] = flipped_ok
        if ok < n * 0.5 and flipped_ok >= n * 0.8:
            res.warnings.append(
                f"按现在的认法，余额只对得上 {ok}/{n}；如果把金额方向整体反过来能对上 {flipped_ok}/{n} —— "
                "收支方向很可能认反了，请在「金额方向」里选「取反」")
        elif ok < n * 0.8:
            same_day, cross = _gap_profile(recs)
            if same_day == 0 and cross:
                res.warnings.append(
                    f"余额有 {cross} 处前后接不上，全都在两个日期之间（同一天内的都对得上）—— "
                    "通常是银行没有列出的交易（如结息、扣费）或流水不全，不是读错了；需要时向银行调取完整流水")
                chk["gaps_between_days"] = cross
            else:
                res.warnings.append(
                    f"余额只对得上 {ok}/{n}：可能流水不全、排序打乱，或者某些列认错了，请核对")
    res.meta["balance_check"] = chk


def _gap_profile(recs: list[dict]) -> tuple[int, int]:
    """余额接不上的地方：(同一天内的, 跨日期的)。按各账户对得更好的那个方向（正序 / 倒序）数。"""
    groups: dict[str, list] = {}
    for r in recs:
        groups.setdefault(r.get("own_account") or "", []).append(r)
    same = cross = 0
    for g in groups.values():
        best = None
        for seq in (g, g[::-1]):
            bad = [(p, q) for p, q in zip(seq, seq[1:])
                   if p["balance_after"] is not None and q["balance_after"] is not None
                   and q["balance_after"] - p["balance_after"] != q["amount"]]
            if best is None or len(bad) < len(best):
                best = bad
        for p, q in best:
            if p["tx_date"] == q["tx_date"]:
                same += 1
            else:
                cross += 1
    return same, cross


def _infer_direction(recs: list[dict]) -> tuple[int, int]:
    """金额都是正数时，用相邻余额差的符号定方向。返回 (定下来的, 定不了的)。"""
    def try_order(seq):
        signs = {}
        for p, q in zip(seq, seq[1:]):
            if p["balance_after"] is None or q["balance_after"] is None:
                continue
            diff = q["balance_after"] - p["balance_after"]
            if diff == q["amount"]:
                signs[id(q)] = 1
            elif diff == -q["amount"]:
                signs[id(q)] = -1
        # 第一笔：用 自己的余额 - 金额 与下一笔的关系推不出来，只能看它后面一笔的余额
        return signs
    a, b = try_order(recs), try_order(recs[::-1])
    signs = a if len(a) >= len(b) else b
    fixed = unsure = 0
    for r in recs:
        s = signs.get(id(r))
        if s in (1, -1):
            r["amount"] = abs(r["amount"]) * s
            fixed += 1
        else:
            unsure += 1
    return fixed, unsure


def field_options() -> list[dict]:
    return [{"key": k, "label": v[0], "group": v[1], "hint": v[2]} for k, v in FIELDS.items()]


# 调取平台：流水大多不是银行直接给的，而是从两个查控平台调来 —— 同一平台各家银行格式相同。
# 按表头里该平台特有的列认（不看银行名），达到 need 个就算。
PLATFORMS = (
    ("platform_a", "查控平台一（反馈单位 / 审批表格式）",
     ("反馈单位", "审批表", "查询对象名称", "查询反馈结果原因", "本方账号", "本方卡号", "交易对方账号开户行"), 4),
    ("platform_b", "查控平台二（任务流水号 / md5 格式）",
     ("任务流水号", "请求单标识", "md5", "所属银行", "查询反馈结果", "钞汇标志", "证照号码"), 3),
    ("platform_c", "查控平台反馈（交易卡号 / 收付标志格式）", ("交易对手账卡号", "收付标志", "对手户名", "交易卡号"), 2),
)


def detect_platform(headers: list) -> Optional[dict]:
    """认出调取平台的格式：{"key", "name"}；不是平台格式（银行直接给的、微信支付宝……）回 None。"""
    hs = {_norm(str(h)) for h in headers if h is not None}
    best = None
    for key, name, cols, need in PLATFORMS:
        n = sum(1 for c in cols if _norm(c) in hs)
        if n >= need and (best is None or n > best[0]):
            best = (n, key, name)
    return {"key": best[1], "name": best[2]} if best else None


_BANK_RE = re.compile(r"([\u4e00-\u9fa5]{2,14}?(?:银行|信用社|信用合作联社|农商行|村镇银行))")


def bank_from_text(text: str) -> str:
    """表头上方标题、文件名里写着的银行名（认不出是哪家大行时用）：如"某某农村商业银行个人账户明细"。"""
    for m in _BANK_RE.finditer(text or ""):
        name = re.sub(r"^(?:个人|对公|账户|交易|明细|流水|查询|打印)+", "", m.group(1))
        if len(name) >= 4:
            return name
    return ""


def account_from_filename(filename: str) -> str:
    """文件名里的账号 / 卡号（如"张三6222020200011112222流水.xlsx"）：12～25 位连续数字，不像日期。"""
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "")
    for m in re.finditer(r"(?<!\d)(\d{12,25})(?!\d)", stem):
        n = m.group(1)
        if re.fullmatch(r"(19|20)\d{6}(?:(19|20)\d{6})?\d{0,6}", n) and len(n) in (12, 14, 16):
            continue        # 20230101 + 时刻 / 两个日期连写，不是账号
        return n
    return ""


_FN_STOP = re.compile(r"流水|明细|交易|账户|账号|银行|对账|账单|查询|反馈|打印|个人|导出|数据|记录|汇总|信息|资料|"
                      r"工作表|附件|副本|新建|微信|支付宝|财付通|整理|调取|调查|复制")


def name_from_filename(filename: str) -> str:
    """文件名里的户名（如"李四_6230…_交易明细.xlsx"）：被分隔开的 2～4 个字、像人名的一段。"""
    from . import names as R
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", filename or "")
    stem = re.sub(r"^.*[\\/]", "", stem)
    for tok in re.split(r"[_\-\s（）()·.,，、+]+|\d+", stem):
        if 2 <= len(tok) <= 4 and re.fullmatch(r"[\u4e00-\u9fa5]+", tok) and not _FN_STOP.search(tok) \
                and R.is_person_name(tok):
            return tok
    return ""


def detect_source(headers: list[str], header_rows: Optional[pd.DataFrame] = None) -> str:
    text = " ".join(headers)
    if header_rows is not None and not header_rows.empty:
        text += " " + " ".join(str(x) for x in header_rows.values.ravel())
    for name, keys in (("支付宝账单", ("支付宝",)), ("微信支付账单", ("微信",)),
                       ("工商银行", ("工商银行", "工行", "ICBC")), ("建设银行", ("建设银行", "建行", "CCB")),
                       ("农业银行", ("农业银行", "农行")), ("中国银行", ("中国银行", "中行", "BOC")),
                       ("交通银行", ("交通银行", "交行")), ("招商银行", ("招商银行", "招行", "CMB")),
                       ("邮储银行", ("邮储", "邮政储蓄")), ("平安银行", ("平安银行",)),
                       ("浦发银行", ("浦发",)), ("兴业银行", ("兴业银行",)), ("中信银行", ("中信银行",)),
                       ("民生银行", ("民生银行",)), ("光大银行", ("光大银行",)), ("华夏银行", ("华夏银行",)),
                       ("广发银行", ("广发",)), ("农商行/农信社", ("农商", "农村商业", "信用社", "农信"))):
        if any(k in text for k in keys):
            return name
    p = detect_platform(headers)
    if p:       # 平台格式表头里没有银行名：银行看每行的「反馈单位 / 所属银行」
        return p["name"]
    return "未识别的银行（按通用规则读取）"


# ═══════════ v3.11 开户信息摘录 ═══════════
# 三个来源：流水表头上方的说明行 / 同一工作簿里的"开户信息"工作表 / 单独的开户资料文件。
# 键名一律**整词匹配**（归一后相等）—— 子串匹配会把"网点电话""对方地址"当成开户人的。
OPEN_FIELDS: dict[str, str] = {
    "open_name": "开户姓名", "open_id": "证件号码", "account_no": "账号/卡号",
    "bank_name": "开户银行", "branch": "开户网点", "open_date": "开户日期",
    "open_phone": "联系电话", "open_address": "地址", "open_occupation": "职业",
    "open_work_unit": "工作单位", "account_type": "账户类型",
    "card_no": "卡号", "close_date": "销户日期", "account_status": "账户状态",
    "balance": "查询时余额", "last_tx_date": "最后交易日期", "currency": "币种",
}
OPEN_ALIASES: dict[str, list[str]] = {
    "open_name": ["户名", "客户名称", "开户名称", "持卡人姓名", "姓名", "账户名称", "账户名",
                  "账户持有人", "查询对象名称", "被查对象名称", "客户姓名", "开户人", "开户人姓名",
                  "账户户名", "持卡人", "微信昵称", "支付宝昵称", "真实姓名"],
    "account_no": ["账号", "账户", "查询账号", "帐号", "客户账号", "账户号码", "账号卡号", "交易账号"],
    "card_no": ["卡号", "银行卡号", "卡片号码", "查询卡号", "交易卡号", "卡折号", "介质号"],
    "close_date": ["销户日期", "销户时间", "销户日"],
    "account_status": ["账户状态", "卡状态", "账户状态描述", "卡片状态"],
    "balance": ["账户余额", "当前余额", "账户当前余额", "余额"],
    "last_tx_date": ["最后交易时间", "最后交易日期", "末次交易日期", "最近交易日期", "最后动户日期", "末笔交易日期"],
    "currency": ["币种", "币别", "货币"],
    "bank_name": ["开户银行", "开户行", "发卡银行", "银行名称", "查询银行", "银行", "所属银行",
                  "行名", "金融机构名称", "反馈机构", "反馈单位"],
    "open_id": ["身份证号", "身份证号码", "证件号码", "身份证", "公民身份号码", "证件号",
                "开户证件号码", "证照号码", "证件号码身份证"],
    "branch": ["开户网点", "开户支行", "开户机构", "网点名称", "开户行名称", "开户网点名称",
               "开户机构名称", "开户网点号"],
    "open_phone": ["联系电话", "手机号码", "手机号", "移动电话", "联系方式", "电话号码", "电话",
                   "预留电话", "预留手机号", "预留手机号码", "联系手机", "手机", "联系人电话", "住宅电话",
                   "家庭电话"],
    "open_address": ["联系地址", "通讯地址", "家庭住址", "居住地址", "住址", "地址", "证件地址",
                     "户籍地址", "住宅地址", "家庭地址", "通信地址"],
    "open_occupation": ["职业", "职务", "职业类别", "职业名称"],
    "open_work_unit": ["工作单位", "单位名称", "任职单位", "工作单位名称", "单位", "工作单位地址名称"],
    "open_date": ["开户日期", "开户时间", "开户日"],
    "account_type": ["账户类型", "卡种", "卡类型", "账户性质", "卡片类型", "账户类别"],
}
_OPEN_INDEX: dict[str, str] = {}
for _k, _vs in OPEN_ALIASES.items():
    for _v in _vs:
        _OPEN_INDEX[_norm(_v)] = _k


def _open_key(cell: str) -> Optional[str]:
    return _OPEN_INDEX.get(_norm(re.sub(r"[：:]\s*$", "", str(cell or ""))))


def _clean_val(field: str, v: str) -> str:
    v = str(v or "").strip().strip("[]【】")
    if field in ("open_date", "close_date", "last_tx_date"):
        if re.fullmatch(r"(9999|0000)\D?\d{2}\D?\d{2}.*|0+", v):
            return ""                 # 99991231、00000000 之类是"没有"的占位
        d = parse_datetime(v)[0]
        if d and (d < "1901" or d > "2200"):          # 19000101 之类同样是占位
            return ""
        return d or v
    if field == "balance":
        try:
            return f"{Decimal(v.replace(',', '')):.2f}"
        except (InvalidOperation, ValueError):
            return ""
    if field == "account_type":
        if v.upper() in ("CC", "C", "CREDIT"):
            return "信用卡"
        if re.fullmatch(r"[0-9A-Za-z]{1,3}", v):   # 11、DC 这类内部代码，不认识就不写
            return {"DC": "借记卡"}.get(v.upper(), "")
    return v


def _backfill_account(r: dict) -> dict:
    """只有卡号没有账号时，卡号也当账号用（多数银行卡号即账号）。"""
    if r.get("card_no") and not r.get("account_no"):
        r["account_no"] = r["card_no"]
    return r


# 表头上方说明行里常见、但不是开户信息的键：用来切分一格里的多对 键：值
_OTHER_HEAD_KEYS = ("查询期间", "查询日期", "起止日期", "打印日期", "打印时间", "起始日期", "截止日期", "币种", "钞汇",
                    "页码", "第", "查询时间", "导出时间", "交易期间", "账户类型", "单位")


def _kv_segments(cell: str) -> list[tuple[str, str]]:
    """「账号：6222… 户名：张三　开户行：某行」→ [(账号, 6222…), (户名, 张三), (开户行, 某行)]。
    只在认得的键前面切开，值里本身带空格（如网点名）不会被切断。"""
    cell = cell.replace("\u3000", " ")
    marks = []
    for m in re.finditer(r"([\u4e00-\u9fa5A-Za-z（）()/]{1,12})\s*[：:]", cell):
        key = m.group(1)
        st = m.start(1)
        if st == 0 or cell[st - 1].isspace() or cell[st - 1] in "；;，,":
            # 前面是开头 / 空格 / 分隔符：整个词就是键（"网点电话"就是网点电话，不是开户人电话）
            marks.append((st, m.end(), key))
            continue
        # 键和前一个值粘在一起（"张三户名："）：从左往右找最长的认得的键
        for i in range(1, len(key)):
            k = key[i:]
            if _open_key(k) or k in _OTHER_HEAD_KEYS:
                marks.append((st + i, m.end(), k))
                break
    out = []
    for n, (st, en, k) in enumerate(marks):
        end = marks[n + 1][0] if n + 1 < len(marks) else len(cell)
        v = cell[en:end].strip(" \t；;，,")
        out.append((k, v))
    if not marks:
        m = re.match(r"^\s*([^：:]{1,12})[：:]\s*(.*)$", cell)
        if m:
            out.append((m.group(1), m.group(2).strip()))
    return out


def extract_open_kv(df: Optional[pd.DataFrame]) -> dict:
    """说明行 / 竖排的开户信息：返回 {字段: {value, source_row, source_key}}。

    认三种写法：一格里"户名：张三"、一格里"户名：张三  账号：6222…"、键值分在相邻两格。
    """
    out: dict = {}
    if df is None or getattr(df, "empty", True):
        return out
    for idx, row in df.iterrows():
        cells = [str(c).strip() for c in row.tolist()]
        rno = int(idx) + 1 if isinstance(idx, (int,)) or str(idx).isdigit() else None
        nonempty = [c for c in cells if c]
        # 一格里的 键：值（可能一格几对：用空格、全角空格、分号隔开，也可能只隔一个空格）
        for c in nonempty:
            for key, val in _kv_segments(c):
                f = _open_key(key)
                val = _clean_val(f, val) if f else ""
                if f and val and f not in out:
                    out[f] = {"value": val, "source_row": rno, "source_key": key.strip()}
        # 键、值分在相邻两格
        for i in range(len(nonempty) - 1):
            f = _open_key(nonempty[i])
            if f and f not in out and not re.search(r"[：:].", nonempty[i]):
                val = nonempty[i + 1]
                if _open_key(val) is None and len(val) <= 200:
                    out[f] = {"value": _clean_val(f, val), "source_row": rno,
                              "source_key": nonempty[i]}
    if "card_no" in out and "account_no" not in out:
        out["account_no"] = dict(out["card_no"])
    return out


def _open_table(df: pd.DataFrame) -> list[dict]:
    """横排的开户信息表（查控反馈常见：一行一张卡）。认不出返回 []。"""
    best, best_hits = -1, 0
    for i in range(min(20, len(df))):
        cells = df.iloc[i].tolist()
        hits = {_open_key(c) for c in cells if c} - {None}
        tx_hits = _header_score(cells)
        if len(hits) >= 3 and len(hits) > best_hits and tx_hits <= len(hits) - 1:
            best, best_hits = i, len(hits)
    if best < 0:
        return []
    # 同一字段几列都能对上（如"联系电话""联系手机"）：每行取第一个有内容的
    cols = [(j, f) for j, c in enumerate(df.iloc[best].tolist()) if (f := _open_key(c))]
    recs = []
    for idx, row in df.iloc[best + 1:].iterrows():
        cells = row.tolist()
        r: dict = {}
        for j, f in cols:
            if j < len(cells) and str(cells[j]).strip():
                v = _clean_val(f, cells[j])
                if not v:
                    continue
                if f not in r:
                    r[f] = v
                elif f == "open_phone" and v not in r[f].split("、"):
                    r[f] = f"{r[f]}、{v}"[:64]       # 联系电话、联系手机、住宅电话都留
        _backfill_account(r)
        if r.get("open_name") or r.get("account_no") or r.get("open_id"):
            r["_row"] = int(idx) + 1
            recs.append(r)
    return recs


def opening_from_sheets(sheets: list[tuple[str, pd.DataFrame]], skip: set) -> list[dict]:
    """工作簿里除流水表以外的工作表：横排表一行一条，竖排键值整表一条。"""
    out = []
    for name, df in sheets:
        if name in skip or df.empty:
            continue
        recs = _open_table(df)
        if not recs:
            kv = extract_open_kv(df)
            if len(kv) >= 2:
                recs = [{k: v["value"] for k, v in kv.items()}]
        for r in recs:
            r["_sheet"] = name
        out.extend(recs)
    return out


def parse_opening_file(file_bytes: bytes, filename: str = "") -> list[dict]:
    """单独的开户资料文件。"""
    sheets, _ = read_sheets(file_bytes, filename)
    recs = opening_from_sheets(sheets, set())
    if not recs:
        raise ValueError("没有在文件里认出开户信息（需要有 户名 / 证件号码 / 账号 这类列，"
                         "或 \"户名：张三\" 这样的键值）")
    return recs


def match_opening(records: list[dict], account_numbers: list[str]) -> Optional[dict]:
    """多条开户记录时按账号/卡号严格对应；只有一条且没有账号可比时就用它。"""
    nums = {_norm_acct(n) for n in account_numbers if n}
    for r in records:
        if nums and {_norm_acct(r.get("account_no", "")), _norm_acct(r.get("card_no", ""))} & nums:
            return r
    if len(records) == 1 and (not nums or not records[0].get("account_no")):
        return records[0]
    return None
