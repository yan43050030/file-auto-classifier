# -*- coding: utf-8 -*-
"""从 Case Intel 仓库同步流水识别核心到 fac/flowcore/。

文件自动分类工具的「账户汇总」「流水整理」用的是 Case Intel 同一套流水识别代码
(各银行格式、借贷方向、余额、本方账号……),这里原样拷过来,只改 import 路径,
并把依赖数据库的部分换成从源文件里摘出的纯函数。Case Intel 改了识别规则后,
在本仓库根目录运行:

    python scripts/sync_flowcore.py /path/to/case-intel

会重新生成 fac/flowcore/ 下的文件,并把来源提交号写进 SOURCE.txt。
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "fac" / "flowcore"
HEADER = "# -*- coding: utf-8 -*-\n# 本文件由 scripts/sync_flowcore.py 从 Case Intel 同步生成,请勿手改;\n# 需要改识别规则请改 Case Intel 再同步。\n"


def _extract(src: str, start_pat: str, end_pat: str) -> str:
    s = re.search(start_pat, src, re.M)
    e = re.search(end_pat, src[s.start():], re.M)
    return src[s.start(): s.start() + e.start()] if e else src[s.start():]


def main(ci: Path) -> None:
    svc = ci / "backend" / "services"
    DST.mkdir(parents=True, exist_ok=True)

    sp = (svc / "statement_parser.py").read_text("utf-8")
    sp = sp.replace("from backend.services import acct_norm as _acct_norm",
                    "from . import acct_norm as _acct_norm")
    sp = sp.replace("from backend.services.branch_lib import canonical_bank",
                    "from .bankname import canonical_bank")
    sp = sp.replace("from backend.services.fund_review import rules as R",
                    "from . import names as R")
    assert "backend." not in sp, "statement_parser 里还有未替换的 backend 依赖"
    (DST / "statement_parser.py").write_text(HEADER + sp, "utf-8")

    an = (svc / "acct_norm.py").read_text("utf-8")
    assert "backend." not in an
    (DST / "acct_norm.py").write_text(HEADER + an, "utf-8")

    bl = (svc / "branch_lib.py").read_text("utf-8")
    part = _extract(bl, r"^_BANKS = \[", r"^def norm_name")
    (DST / "bankname.py").write_text(
        HEADER + '"""银行名称归一(摘自 Case Intel branch_lib.canonical_bank,不含数据库部分)。"""\n'
        "from __future__ import annotations\n\nimport re\nimport unicodedata\nfrom typing import Optional\n\n"
        + part.rstrip() + "\n", "utf-8")

    rl = (svc / "fund_review" / "rules.py").read_text("utf-8")
    part = _extract(rl, r"^_ORG_WORDS = ", r"^# 企业名称")
    (DST / "names.py").write_text(
        HEADER + '"""人名 / 单位名判断(摘自 Case Intel fund_review.rules)。"""\n'
        "from __future__ import annotations\n\nimport re\n\n" + part.rstrip() + "\n", "utf-8")

    qt = (svc / "quick_tools.py").read_text("utf-8")
    qt = qt.replace("from backend.services import statement_parser as SP",
                    "from . import statement_parser as SP")
    # 拆出 stats_from_parsed:本工具自己读文件、跨文件去重后再统计
    a = ("def account_stats(files: list[tuple[str, bytes]]) -> dict:\n"
         "    parsed = parse_all(files)\n")
    assert a in qt, "quick_tools.account_stats 的开头变了,请更新 sync_flowcore.py"
    qt = qt.replace(a, "def account_stats(files: list[tuple[str, bytes]]) -> dict:\n"
                       "    return stats_from_parsed(parse_all(files))\n\n\n"
                       "def stats_from_parsed(parsed: list[Parsed]) -> dict:\n")
    assert "backend." not in qt
    (DST / "quick_tools.py").write_text(HEADER + qt, "utf-8")

    (DST / "__init__.py").write_text(
        '# -*- coding: utf-8 -*-\n"""Case Intel 的流水识别核心(同步副本,见 scripts/sync_flowcore.py)。"""\n', "utf-8")
    try:
        rev = subprocess.check_output(["git", "-C", str(ci), "rev-parse", "HEAD"], text=True).strip()
    except Exception:
        rev = "unknown"
    (DST / "SOURCE.txt").write_text(f"case-intel {rev}\n", "utf-8")
    print(f"已同步到 {DST}(case-intel {rev[:7]})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("用法: python scripts/sync_flowcore.py /path/to/case-intel")
    main(Path(sys.argv[1]))
