# -*- coding: utf-8 -*-
"""程序入口:带命令行参数走 CLI,否则打开图形界面。"""

import sys


def main():
    if len(sys.argv) > 1:
        from .cli import main as cli_main
        cli_main()
    else:
        from .gui import main as gui_main
        gui_main()
