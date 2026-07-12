# -*- coding: utf-8 -*-
"""
文件自动分类工具
================
功能:
  1. 自动解压 zip(含 AES 加密)/ 7z / rar / tar / gz 压缩包(支持嵌套与分卷)。
  2. 按人员名单(姓名 + 身份证号 + 曾用名,任一命中归同一文件夹)分类文件。
  3. 来源单位标注(子文件夹或文件名前缀),自动生成"人员 × 单位"反馈核对表。
  4. 可选:内容级匹配(Excel/Word/PDF)、Excel 按人拆分、内容去重、试运行预览。
  5. 双击运行打开图形界面;带命令行参数运行则为无界面批处理模式(-h 查看用法)。

代码按模块拆分在 fac/ 包中:
  extract  解压    roster  人员名单    pipeline  主流程
  idcard   身份证  password 密码管理   report    核对表
  content_match 内容匹配  excel_split Excel拆分
  gui 图形界面  cli 命令行  config 配置持久化

作者: Claude  |  运行环境: Windows + Python 3.8 及以上
"""

import os
import sys

# 双击运行时保证能找到同目录下的 fac 包
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fac.main import main

if __name__ == '__main__':
    main()
