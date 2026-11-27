# -*- coding: utf-8 -*-
# 本文件由 scripts/sync_flowcore.py 从 Case Intel 同步生成,请勿手改;
# 需要改识别规则请改 Case Intel 再同步。
# -*- coding: utf-8 -*-
"""快捷工具：不建案件、不入库，拿到流水文件马上出结果。

  一、账户快捷统计   每个账户：收 / 付笔数和金额、交易量、净额、期初 / 期末 / 最高 / 最低余额、存取现；
                     几个文件里的账户之间互转单列，给出剔除互转后的合计
  二、流水快速清洗   一批流水合成一张、按日期时间排好：本方、收付、金额、余额、对方，加上摘要 / 附言 / 备注
                     各列（一个不丢），以及网点、柜员号、终端号、传票 / 凭证号、日志号、IP、MAC、商户等
                     查传票、看用卡轨迹用得上的列；全空的列、每行都一样的列不放进表里（写在「说明」页）
  三、流水整理       保留原表每一行、每个有内容的列：查询卡号、审批表、查询反馈原因和全空的列删掉（或隐藏），
                     户名、账号、时间、类型、金额、余额、对方、摘要附言等重要列移到前面，其余放后面；
                     调好列宽行高、冻结表头、加筛选，时间写成 年-月-日 时:分:秒，金额变成数字（不取整）

金额全程用 Decimal，原样两位小数，不四舍五入。
"""
from __future__ import annotations

import io
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Callable, Optional

from . import statement_parser as SP

MAX_FILES = 200
MAX_TOTAL = 300 * 1024 * 1024


# ═══════════════════════════════════════════════════════════
# 列分类（整理、清洗共用）
# ═══════════════════════════════════════════════════════════
def _n(h: str) -> str:
    return re.sub(r"[\s_（）()【】\[\]:：/\\\-]+", "", str(h or "")).lower()


_CP = ("对方", "对手", "收款", "付款", "交易对")
_ADMIN = re.compile(r"审批表|查询卡号|查询账号|查询对象账号|反馈结果|反馈原因|反馈说明|查询结果原因|查询反馈|文书号|协查编号|查询编号|查询单号")


def is_admin(h: str) -> bool:
    """查询 / 审批类的列：对看流水没有用（查询卡号、审批表、查询反馈结果原因……）。"""
    return bool(_ADMIN.search(_n(h)))


def _has(h: str, *ws) -> bool:
    return any(w in h for w in ws)


# 重要列：顺序就是整理后从左到右的顺序。每条：(组名, 判断)
_GROUPS: list[tuple[str, Callable[[str], bool]]] = [
    ("户名", lambda h: (h in ("名称", "姓名", "户名", "客户名", "持卡人") or _has(h, "查询对象名称", "账户名称", "客户名称",
                                                                     "账户户名", "本方户名", "本方名称", "持卡人姓名", "户主"))
     and not _has(h, *_CP, "商户", "网点", "开户行", "机构", "行名", "单位", "银行")),
    ("账号", lambda h: _has(h, "账号", "卡号", "账户号") and not _has(h, *_CP, "查询", "商户", "流水", "子账")),
    ("时间", lambda h: (_has(h, "交易时间", "交易日期", "记账日期", "记账时间", "入账日期", "入账时间", "发生时间", "发生日期")
                      or h in ("日期", "时间", "交易时刻"))),
    ("类型", lambda h: _has(h, "交易类型", "借贷标志", "借贷", "收付标志", "收支", "业务类型", "交易方式", "交易种类",
                           "现金标志", "钞汇") and not _has(h, *_CP)),
    ("金额", lambda h: _has(h, "金额", "发生额", "收入", "支出", "存入", "取出", "借方", "贷方") and not _has(h, "余额", *_CP)),
    ("余额", lambda h: _has(h, "余额") and not _has(h, *_CP)),
    ("对方户名", lambda h: _has(h, *_CP) and _has(h, "名称", "户名", "姓名", "名字", "人") and not _has(h, "开户行", "银行", "行名", "证件", "机构")),
    ("对方账号", lambda h: _has(h, *_CP) and _has(h, "账号", "卡号", "账户") and not _has(h, "开户行", "银行", "行名", "机构", "余额")),
    ("对方银行", lambda h: _has(h, *_CP) and _has(h, "开户行", "银行", "行名", "机构", "网点")),
    ("摘要附言", lambda h: _has(h, "摘要", "附言", "备注", "用途", "说明", "描述", "附加", "交易内容", "交易信息", "注释", "事由")),
    ("网点地点", lambda h: _has(h, "网点", "交易机构", "交易行", "营业", "发生地", "交易地点", "地址", "地区", "受理机构")),
    ("商户", lambda h: _has(h, "商户", "商家")),
    ("柜员终端", lambda h: _has(h, "柜员", "终端", "设备", "ip", "mac", "渠道")),
    ("凭证流水", lambda h: _has(h, "传票", "凭证", "日志号", "流水号", "交易号", "序号码", "订单", "参考号", "检索号", "批次")),
    ("对方其他", lambda h: _has(h, *_CP)),
]
GROUP_NAMES = [g for g, _ in _GROUPS] + ["其他"]


def group_of(header: str) -> str:
    h = _n(header)
    for g, f in _GROUPS:
        if f(h):
            return g
    return "其他"


# ═══════════════════════════════════════════════════════════
# 值的整理
# ═══════════════════════════════════════════════════════════
_TS14 = re.compile(r"^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})$")
_TS8 = re.compile(r"^(\d{4})(\d{2})(\d{2})$")
_NUM = re.compile(r"^-?(\d{1,3}(,\d{3})+|\d+)(\.\d+)?$")


def nice_time(v: str) -> str:
    s = str(v or "").strip()
    m = _TS14.match(s)
    if m:
        return f"{m[1]}-{m[2]}-{m[3]} {m[4]}:{m[5]}:{m[6]}"
    m = _TS8.match(s)
    if m and 1900 < int(m[1]) < 2100 and 1 <= int(m[2]) <= 12:
        return f"{m[1]}-{m[2]}-{m[3]}"
    return s


def as_decimal(v: str) -> Optional[Decimal]:
    s = str(v or "").strip().replace("¥", "").replace("￥", "")
    if not s or not _NUM.match(s):
        return None
    try:
        return Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None


def _w(s: str) -> int:
    """显示宽度：汉字算 2。"""
    return sum(2 if ord(c) > 0x2E80 else 1 for c in str(s))


def _y(d: Optional[Decimal]) -> str:
    return "" if d is None else f"{d:.2f}"


# ═══════════════════════════════════════════════════════════
# 读文件
# ═══════════════════════════════════════════════════════════
@dataclass
class Parsed:
    filename: str
    res: Optional[SP.ParseResult] = None
    error: str = ""


def parse_all(files: list[tuple[str, bytes]]) -> list[Parsed]:
    if len(files) > MAX_FILES:
        raise ValueError(f"一次最多 {MAX_FILES} 个文件")
    if sum(len(b) for _, b in files) > MAX_TOTAL:
        raise ValueError("文件合计超过 300 MB，请分批处理")
    out = []
    for name, b in files:
        try:
            res = SP.parse_statement(b, name)
        except Exception as e:  # noqa: BLE001 —— 一个文件认不出不影响其他文件
            out.append(Parsed(name, error=str(e)[:200] or type(e).__name__))
            continue
        if not res.records:
            why = next((w for w in res.warnings if "无法" in w or "没认出" in w), "") or \
                ("；".join(f"{SP.SKIP_REASONS.get(k, k)} {len(v)} 行" for k, v in res.skipped.items() if v) or "没有读到交易")
            out.append(Parsed(name, error=f"没认出流水：{why}"[:200]))
            continue
        out.append(Parsed(name, res))
    return out


def _bank(p: Parsed) -> str:
    own = (p.res.meta.get("own_accounts") or [])
    b = next((o["bank"] for o in own if o.get("bank")), "")
    if b:
        return b
    src = SP.detect_source(p.res.meta.get("headers") or [])
    return "" if src.startswith(("未识别", "查控平台")) else src.replace("（", "(").split("(")[0]


def _dt(r: dict) -> str:
    return f"{r['tx_date']} {r['tx_time']}".strip()


# ═══════════════════════════════════════════════════════════
# 一、账户快捷统计
# ═══════════════════════════════════════════════════════════
_CASH = re.compile(r"现金|ATM|atm|取现|存现|取款|存款机|柜面存|柜面取")


@dataclass
class Acct:
    key: str
    account: str = ""
    card: str = ""
    name: str = ""
    bank: str = ""
    currency: str = ""
    files: list = field(default_factory=list)
    rows: list = field(default_factory=list)


def account_stats(files: list[tuple[str, bytes]]) -> dict:
    return stats_from_parsed(parse_all(files))


def stats_from_parsed(parsed: list[Parsed]) -> dict:
    accts: dict[str, Acct] = {}
    for p in parsed:
        if not p.res:
            continue
        own = {o["account"]: o for o in p.res.meta.get("own_accounts") or []}
        for r in p.res.records:
            oa = r.get("own_account") or ""
            key = (oa or f"文件:{p.filename}") + (f"|{r['_fx']}" if r.get("_fx") else "")
            a = accts.get(key)
            if a is None:
                o = own.get(oa) or {}
                a = accts[key] = Acct(key, oa, o.get("card") or r.get("own_card") or "", o.get("name") or "",
                                      o.get("bank") or _bank(p), r.get("_fx") or "")
            if p.filename not in a.files:
                a.files.append(p.filename)
            a.rows.append(r)
    nums = {}
    for a in accts.values():
        for n in (a.account, a.card):
            if n:
                nums[SP._norm_acct(n)] = a.key
    rows, tot = [], defaultdict(Decimal)
    for a in accts.values():
        rs = sorted(a.rows, key=lambda r: (r["tx_date"], r["tx_time"] or "", r["row_no"]))
        s = defaultdict(Decimal)
        cnt = defaultdict(int)
        for r in rs:
            amt = r["amount"]
            d = "in" if amt > 0 else "out"
            s[d] += abs(amt)
            cnt[d] += 1
            if _CASH.search(f"{r.get('channel', '')} {r.get('remark', '')} {r.get('tx_type', '')}"):
                s[f"cash_{d}"] += abs(amt)
                cnt[f"cash_{d}"] += 1
            other = nums.get(SP._norm_acct(r.get("counterpart_account") or ""))
            if other and other != a.key:
                s[f"self_{d}"] += abs(amt)
                cnt[f"self_{d}"] += 1
        bals = [(r["balance_after"], _dt(r)) for r in rs if r.get("balance_after") is not None]
        first = next((r for r in rs if r.get("balance_after") is not None), None)
        opening = (first["balance_after"] - first["amount"]) if first else None
        if opening is not None:          # 第一笔之前的余额也算：期初就是最高 / 最低的情形
            bals = [(opening, "期初")] + bals
        hi = max(bals, key=lambda x: x[0]) if bals else None
        lo = min(bals, key=lambda x: x[0]) if bals else None
        row = {
            "key": a.key, "name": a.name, "bank": a.bank, "account": a.account, "card": a.card,
            "currency": a.currency or "人民币", "files": a.files,
            "first": rs[0]["tx_date"] if rs else "", "last": rs[-1]["tx_date"] if rs else "",
            "count": len(rs), "in_count": cnt["in"], "out_count": cnt["out"],
            "in": _y(s["in"]), "out": _y(s["out"]), "volume": _y(s["in"] + s["out"]), "net": _y(s["in"] - s["out"]),
            "opening": _y(opening), "closing": _y(bals[-1][0]) if bals else "",
            "max_balance": _y(hi[0]) if hi else "", "max_balance_at": hi[1] if hi else "",
            "min_balance": _y(lo[0]) if lo else "", "min_balance_at": lo[1] if lo else "",
            "cash_in": _y(s["cash_in"]), "cash_in_count": cnt["cash_in"],
            "cash_out": _y(s["cash_out"]), "cash_out_count": cnt["cash_out"],
            "self_in": _y(s["self_in"]), "self_out": _y(s["self_out"]),
            "in_ext": _y(s["in"] - s["self_in"]), "out_ext": _y(s["out"] - s["self_out"]),
            "no_balance": not bals,
        }
        rows.append(row)
        if not a.currency:
            for k in ("in", "out", "cash_in", "cash_out", "self_in", "self_out"):
                tot[k] += s[k]
            tot["count"] += len(rs)
            if bals:
                tot["closing"] += bals[-1][0]
    rows.sort(key=lambda r: (r["currency"] != "人民币", r["name"], r["bank"], r["account"]))
    total = {"accounts": sum(1 for r in rows if r["currency"] == "人民币"), "count": int(tot["count"]),
             "in": _y(tot["in"]), "out": _y(tot["out"]), "volume": _y(tot["in"] + tot["out"]),
             "net": _y(tot["in"] - tot["out"]), "closing": _y(tot["closing"]),
             "self_in": _y(tot["self_in"]), "self_out": _y(tot["self_out"]),
             "in_ext": _y(tot["in"] - tot["self_in"]), "out_ext": _y(tot["out"] - tot["self_out"]),
             "cash_in": _y(tot["cash_in"]), "cash_out": _y(tot["cash_out"])}
    return {"accounts": rows, "total": total, "files": _file_report(parsed)}


def _file_report(parsed: list[Parsed]) -> list[dict]:
    out = []
    for p in parsed:
        if not p.res:
            out.append({"file": p.filename, "ok": False, "error": p.error})
            continue
        sk = {SP.SKIP_REASONS.get(k, k): len(v) for k, v in p.res.skipped.items() if v}
        # 开户信息相关的提示（证件号校验位等）与快捷工具无关：这里不写开户信息
        ws = [w for w in p.res.warnings if "开户信息" not in w and "按本方账号拆成多个账户" not in w]
        out.append({"file": p.filename, "ok": True, "rows": len(p.res.records), "skipped": sk,
                    "warnings": ws[:6], "format": SP.detect_source(p.res.meta.get("headers") or [])})
    return out


STAT_COLS = [("name", "户名"), ("bank", "银行"), ("account", "账号"), ("card", "卡号"), ("currency", "币种"),
             ("first", "起始日期"), ("last", "截止日期"), ("count", "笔数"),
             ("in_count", "收入笔数"), ("in", "收入金额"), ("out_count", "支出笔数"), ("out", "支出金额"),
             ("volume", "交易量（收+支）"), ("net", "净额（收-支）"),
             ("opening", "期初余额"), ("closing", "期末余额"), ("max_balance", "最高余额"), ("max_balance_at", "最高余额时间"),
             ("min_balance", "最低余额"), ("cash_in", "存现金额"), ("cash_out", "取现金额"),
             ("self_in", "其中来自所列其他账户"), ("self_out", "其中转往所列其他账户"),
             ("in_ext", "剔除互转后收入"), ("out_ext", "剔除互转后支出")]
_MONEY_KEYS = {"in", "out", "volume", "net", "opening", "closing", "max_balance", "min_balance", "cash_in", "cash_out",
               "self_in", "self_out", "in_ext", "out_ext"}


def stats_xlsx(r: dict) -> bytes:
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "账户统计"
    ws.append([t for _, t in STAT_COLS] + ["来源文件"])
    for a in r["accounts"]:
        ws.append([_cell(a[k], k in _MONEY_KEYS) for k, _ in STAT_COLS] + ["、".join(a["files"])])
    t = r["total"]
    ws.append([])
    ws.append(["人民币合计", "", f"{t['accounts']} 个账户", "", "", "", "", t["count"], "", _cell(t["in"], True), "",
               _cell(t["out"], True), _cell(t["volume"], True), _cell(t["net"], True), "", _cell(t["closing"], True),
               "", "", "", _cell(t["cash_in"], True), _cell(t["cash_out"], True), _cell(t["self_in"], True),
               _cell(t["self_out"], True), _cell(t["in_ext"], True), _cell(t["out_ext"], True)])
    ws.append([])
    ws.append(["说明：金额为流水原样（两位小数，未取整）；期初余额 = 第一笔交易后余额 − 该笔金额；"
               "互转指对方账号是本次所列另一个账户；外币账户单列，不计入人民币合计。"])
    _style(ws, header_row=1, money_cols={i + 1 for i, (k, _) in enumerate(STAT_COLS) if k in _MONEY_KEYS},
           text_cols={3, 4})
    _files_sheet(wb, r["files"])
    return _save(wb)


# ═══════════════════════════════════════════════════════════
# 二、流水快速清洗
# ═══════════════════════════════════════════════════════════
# 已经放进前面标准列的原始字段，不再重复
_STD_FIELDS = {"tx_date", "tx_time", "tx_type", "amount", "income", "expense", "direction", "balance_after", "counterpart",
               "counterpart_account", "counterpart_card", "own_account", "own_card", "own_name", "own_bank", "currency",
               "success", "payer_name", "payer_account", "payee_name", "payee_account"}
# 清洗时直接不要的原始列（证件类型这类每行一样、看流水用不上的；身份证在说明页）
_CLEAN_SKIP = re.compile(r"证件类型|^币种$|交易是否成功|是否成功|^序号$|^行号$")
_KEEP_GROUPS = ("对方银行", "摘要附言", "网点地点", "商户", "柜员终端", "凭证流水", "对方其他", "类型")

CLEAN_HEAD = ["交易时间", "本方户名", "本方账号", "银行", "收付", "金额", "余额", "对方户名", "对方账号", "交易类型"]


def quick_clean(files: list[tuple[str, bytes]]) -> tuple[bytes, dict]:
    parsed = parse_all(files)
    extra_cols: list[str] = []          # 保留的原始列（按出现先后，同名合并）
    col_vals: dict[str, set] = defaultdict(set)
    recs = []
    file_info = []
    for p in parsed:
        if not p.res:
            continue
        mp = p.res.meta.get("mapping") or {}
        own = {o["account"]: o for o in p.res.meta.get("own_accounts") or []}
        bank = _bank(p)
        keep = []
        for h in p.res.meta.get("headers") or []:
            if is_admin(h) or _CLEAN_SKIP.search(_n(h)) or mp.get(h) in _STD_FIELDS:
                continue
            if group_of(h) in ("户名", "账号", "时间", "金额", "余额", "对方户名", "对方账号"):
                continue
            keep.append(h)
        for r in p.res.records:
            raw = r.get("raw") or {}
            o = own.get(r.get("own_account") or "") or {}
            ex = {}
            for h in keep:
                v = str(raw.get(h, "") or "").strip()
                if v:
                    ex[h] = v
                    col_vals[h].add(v)
            recs.append((r, p.filename, o.get("name") or "", r.get("own_account") or o.get("card") or "",
                         o.get("bank") or bank, ex))
        for h in keep:
            if h not in extra_cols:
                extra_cols.append(h)
        file_info.append(p)
    # 全空的列不要；每行都一样的列放到说明页
    const = {h: next(iter(col_vals[h])) for h in extra_cols if len(col_vals[h]) == 1
             and sum(1 for x in recs if h in x[5]) == len(recs) and len(recs) > 1}
    cols = [h for h in extra_cols if col_vals[h] and h not in const]
    order = {g: i for i, g in enumerate(_KEEP_GROUPS)}
    cols.sort(key=lambda h: (order.get(group_of(h), 99), extra_cols.index(h)))
    recs.sort(key=lambda x: (x[0]["tx_date"], x[0]["tx_time"] or "", x[1], x[0]["row_no"]))

    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "清洗后流水"
    ws.append(CLEAN_HEAD + cols + ["来源文件", "原表行号"])
    for r, fn, name, acct, bank, ex in recs:
        amt = r["amount"]
        ws.append([_dt(r), name, acct, bank, "收" if amt > 0 else "付", _num(abs(amt)), _num(r.get("balance_after")),
                   r.get("counterpart") or "", r.get("counterpart_account") or "", r.get("tx_type") or ""]
                  + [ex.get(h, "") for h in cols] + [fn, r["row_no"]])
    n0 = len(CLEAN_HEAD)
    _style(ws, header_row=1, money_cols={6, 7}, text_cols={3, 9} | {n0 + i + 1 for i, h in enumerate(cols)
                                                                   if group_of(h) in ("对方其他", "凭证流水", "柜员终端")},
           wrap_cols={n0 + i + 1 for i, h in enumerate(cols) if group_of(h) == "摘要附言"},
           in_out_col=5)
    # 说明页
    info = wb.create_sheet("说明")
    info.append(["项目", "内容"])
    info.append(["整理方式", "各文件的流水合成一张，按交易日期、时间先后排列；金额为流水原样（未取整），收 / 付单列一栏"])
    info.append(["保留的原始列", "、".join(cols) or "（无）"])
    for h, v in const.items():
        info.append([f"每笔都相同：{h}", v])
    dropped = sorted({h for p in file_info for h in p.res.meta.get("headers") or [] if h not in cols and h not in const})
    info.append(["未放进表里的列", "、".join(dropped) + "（已在前面标准列里、全空、或是查询审批类信息）"])
    for p in parsed:
        if p.res:
            sk = "；".join(f"{SP.SKIP_REASONS.get(k, k)} {len(v)} 行" for k, v in p.res.skipped.items() if v)
            info.append([p.filename, f"{len(p.res.records)} 笔" + (f"；跳过 {sk}" if sk else "")
                         + "".join("；" + w for w in p.res.warnings[:4] if "开户信息" not in w and "按本方账号拆成多个账户" not in w)])
        else:
            info.append([p.filename, f"认不出 —— {p.error}"])
    _style(info, header_row=1, wrap_cols={2}, max_width=100)
    summary = {"rows": len(recs), "columns": CLEAN_HEAD + cols + ["来源文件", "原表行号"], "kept_raw": cols,
               "constant": const, "files": _file_report(parsed),
               "preview": [[(f"{Decimal(str(c.value)):,.2f}" if c.column in (6, 7) and i and isinstance(c.value, (int, float))
                             else c.value) for c in row]
                           for i, row in enumerate(ws.iter_rows(min_row=1, max_row=min(ws.max_row, 21)))]}
    return _save(wb), summary


# ═══════════════════════════════════════════════════════════
# 三、流水整理（保留原表）
# ═══════════════════════════════════════════════════════════
def _tables(b: bytes, filename: str):
    """文件里每个像流水的工作表：(表名, 表头上方的说明行, 表头, 数据行)。"""
    sheets, _ = SP.read_sheets(b, filename)
    out = []
    for name, df in sheets:
        if df.empty:
            continue
        hr, hits = SP.find_header(df)
        if hr < 0 or hits < 2:
            continue
        above = [" ".join(x for x in df.iloc[i].tolist() if x) for i in range(hr)]
        headers = [str(h) or f"列{j + 1}" for j, h in enumerate(df.iloc[hr].tolist())]
        seen = defaultdict(int)
        for j, h in enumerate(headers):
            seen[h] += 1
            if seen[h] > 1:
                headers[j] = f"{h}_{seen[h]}"
        data = [list(df.iloc[i].tolist()) for i in range(hr + 1, len(df))]
        data = [r for r in data if [str(x) for x in r] != headers]          # 分页导出重复的表头行
        out.append((name, above, headers, data))
    return out


def tidy_plan(headers: list[str], data: list[list[str]]) -> dict:
    """每列：保留 / 删除（及原因）、所属分组、新顺序。"""
    cols = []
    for j, h in enumerate(headers):
        filled = sum(1 for r in data if j < len(r) and str(r[j]).strip())
        if is_admin(h):
            why = "查询 / 审批信息"
        elif filled == 0:
            why = "整列没有内容"
        else:
            why = ""
        cols.append({"index": j, "header": h, "group": group_of(h), "filled": filled, "drop": why})
    rank = {g: i for i, g in enumerate(GROUP_NAMES)}
    keep = sorted([c for c in cols if not c["drop"]], key=lambda c: (rank[c["group"]], c["index"]))
    return {"keep": keep, "drop": [c for c in cols if c["drop"]]}


def tidy(files: list[tuple[str, bytes]], drop_mode: str = "delete", sort_time: bool = False) -> tuple[bytes, dict]:
    from openpyxl import Workbook
    wb = Workbook()
    wb.remove(wb.active)
    report = []
    used = set()
    for fname, b in files:
        try:
            tables = _tables(b, fname)
        except Exception as e:  # noqa: BLE001
            report.append({"file": fname, "ok": False, "error": str(e)[:200]})
            continue
        if not tables:
            report.append({"file": fname, "ok": False, "error": "没有认出流水表头"})
            continue
        for sname, above, headers, data in tables:
            plan = tidy_plan(headers, data)
            order = plan["keep"] + (plan["drop"] if drop_mode == "hide" else [])
            title = _sheet_title(fname, sname, len(tables), used)
            ws = wb.create_sheet(title)
            ws.append([c["header"] for c in order])
            tcol = next((k for k, c in enumerate(order) if c["group"] == "时间"), None)
            rows = data
            if sort_time and tcol is not None:
                j = order[tcol]["index"]
                rows = sorted(data, key=lambda r: nice_time(r[j] if j < len(r) else ""))
            money = {k + 1 for k, c in enumerate(order) if c["group"] in ("金额", "余额")}
            for r in rows:
                line = []
                for k, c in enumerate(order):
                    v = str(r[c["index"]]) if c["index"] < len(r) else ""
                    if c["group"] == "时间":
                        v = nice_time(v)
                    elif k + 1 in money and as_decimal(v) is not None:
                        v = _num(as_decimal(v))
                    line.append(v)
                ws.append(line)
            hidden = {k + 1 for k, c in enumerate(order) if c["drop"]}
            _style(ws, header_row=1, money_cols=money,
                   text_cols={k + 1 for k, c in enumerate(order) if c["group"] in ("账号", "对方账号", "凭证流水", "柜员终端", "对方其他")
                              or "证件" in c["header"]},
                   wrap_cols={k + 1 for k, c in enumerate(order) if c["group"] == "摘要附言"},
                   hidden_cols=hidden, key_cols=sum(1 for c in plan["keep"] if c["group"] not in ("其他",) and
                                                    GROUP_NAMES.index(c["group"]) <= GROUP_NAMES.index("摘要附言")))
            if above:
                note = wb.create_sheet(_sheet_title(fname, f"{sname}表头", 2, used))
                for line in above:
                    note.append([line])
            report.append({"file": fname, "ok": True, "sheet": title, "rows": len(data),
                           "front": [c["header"] for c in plan["keep"] if c["group"] != "其他"],
                           "back": [c["header"] for c in plan["keep"] if c["group"] == "其他"],
                           "dropped": [{"header": c["header"], "why": c["drop"]} for c in plan["drop"]],
                           "mode": drop_mode})
    if not wb.sheetnames:
        raise ValueError("所有文件都没有认出流水表：" + "；".join(f"{r['file']}：{r['error']}" for r in report))
    return _save(wb), {"files": report}


def _sheet_title(fname: str, sname: str, n: int, used: set) -> str:
    base = re.sub(r"\.(xlsx|xls|csv|txt|htm|html|et)$", "", fname, flags=re.I)
    t = base if n == 1 else f"{base}-{sname}"
    t = re.sub(r"[\[\]:*?/\\]", "_", t)[:28] or "流水"
    k, out = 1, t
    while out in used:
        k += 1
        out = f"{t[:25]}_{k}"
    used.add(out)
    return out


# ═══════════════════════════════════════════════════════════
# Excel 样式
# ═══════════════════════════════════════════════════════════
def _num(d) -> object:
    """Decimal → Excel 数字单元格（两位小数显示；值本身不取整）。"""
    if d is None or d == "":
        return ""
    d = Decimal(str(d))
    return int(d) if d == d.to_integral_value() and abs(d) < 10 ** 15 else float(d)


def _cell(v, money: bool):
    if money and v not in ("", None):
        return _num(Decimal(v))
    return v


def _style(ws, header_row: int = 1, money_cols: set = frozenset(), text_cols: set = frozenset(),
           wrap_cols: set = frozenset(), hidden_cols: set = frozenset(), key_cols: int = 0,
           in_out_col: Optional[int] = None, max_width: int = 46) -> None:
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter
    thin = Side(style="thin", color="D0D7E2")
    head_fill = PatternFill("solid", fgColor="DCE6F1")
    key_fill = PatternFill("solid", fgColor="C5D9F1")
    widths: dict[int, int] = defaultdict(int)
    for row in ws.iter_rows(min_row=header_row, max_row=min(ws.max_row, header_row + 2000)):
        for c in row:
            if c.value not in (None, ""):
                v = c.value
                s = f"{v:,.2f}" if c.column in money_cols and isinstance(v, (int, float)) else str(v)
                widths[c.column] = max(widths[c.column], _w(s))
    ncol = ws.max_column
    for j in range(1, ncol + 1):
        letter = get_column_letter(j)
        w = min(max(widths[j] + (4 if j in money_cols else 2), 12 if j in money_cols else 8), 30 if j in wrap_cols else max_width)
        ws.column_dimensions[letter].width = w
        if j in hidden_cols:
            ws.column_dimensions[letter].hidden = True
    for c in ws[header_row]:
        c.font = Font(bold=True)
        c.fill = key_fill if c.column <= key_cols else head_fill
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        c.border = Border(top=thin, bottom=thin, left=thin, right=thin)
    ws.row_dimensions[header_row].height = 30
    red, green = Font(color="C00000"), Font(color="00703C")
    for row in ws.iter_rows(min_row=header_row + 1, max_row=ws.max_row):
        lines = 1
        for c in row:
            j = c.column
            if j in money_cols and isinstance(c.value, (int, float)):
                c.number_format = "#,##0.00"
            elif j in text_cols:
                c.number_format = "@"
            if j in wrap_cols and c.value:
                c.alignment = Alignment(wrap_text=True, vertical="top")
                lines = max(lines, min(4, math.ceil(_w(c.value) / max(1, ws.column_dimensions[get_column_letter(j)].width - 1))))
            else:
                c.alignment = Alignment(vertical="top")
            c.border = Border(bottom=Side(style="hair", color="E0E0E0"))
        if in_out_col and row[in_out_col - 1].value in ("收", "付"):
            f = green if row[in_out_col - 1].value == "收" else red
            row[in_out_col - 1].font = f
            if in_out_col < len(row):
                row[in_out_col].font = f
        ws.row_dimensions[row[0].row].height = 16 * lines + 4
    ws.freeze_panes = ws.cell(row=header_row + 1, column=min(3, ncol) if ncol > 3 else 1)
    ws.page_setup.orientation = "landscape"          # 打印：横向，每页都带表头
    ws.print_title_rows = f"{header_row}:{header_row}"
    if ws.max_row > header_row:
        ws.auto_filter.ref = f"A{header_row}:{get_column_letter(ncol)}{ws.max_row}"


def _files_sheet(wb, files: list[dict]) -> None:
    ws = wb.create_sheet("文件情况")
    ws.append(["文件", "结果", "说明"])
    for f in files:
        if f["ok"]:
            sk = "；".join(f"{k} {v} 行" for k, v in f["skipped"].items())
            ws.append([f["file"], f"{f['rows']} 笔", "；".join(filter(None, [f.get("format"), sk and f"跳过 {sk}"] + f["warnings"]))])
        else:
            ws.append([f["file"], "认不出", f["error"]])
    _style(ws, wrap_cols={3}, max_width=90)


def _save(wb) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
