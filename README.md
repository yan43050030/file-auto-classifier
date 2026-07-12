# 文件自动分类工具 (File Auto Classifier)

一个带图形界面的 Windows 小工具:**自动解压压缩包(支持多级嵌套、分卷、AES 加密),再按人员名单(姓名 / 身份证号 / 曾用名任一命中)把文件按人归档,并生成"人员 × 来源单位"反馈核对表。**

典型场景:向多个单位查询多名人员的信息,各单位以压缩包反馈;本工具一键把所有反馈按"一人一个文件夹"归档,同时标注每份材料来自哪个单位,并列出哪些单位对哪些人还没有反馈。

## 功能特性

### 解压
- **多格式**:zip(含 **AES 加密**,通过 pyzipper)/ 7z / rar / tar / tar.gz / gz;内置官方 UnRAR.exe,打包成 exe 后目标电脑无需安装 WinRAR。
- **多级嵌套**:压缩包里套压缩包(最多 5 层)自动递归解压。
- **分卷识别**:`.part1.rar` 自动带出后续卷、`.7z.001` 分卷直接支持,后续卷不再误报失败。
- **加密压缩包**:密码本自动尝试(输入文件夹里的 txt 自动识别,兼容 `文件名: 密码` 等格式),失败再弹框;验证密码只解压包内最小的一个文件,大包不再整包试错。
- **安全**:防 zip slip 路径穿越;Windows 超长路径(>260 字符)自动处理;解压失败的包收进"解压失败"文件夹,绝不悄悄丢文件。

### 分类
- **人员名单**:每行一个人 `姓名,身份证号,曾用名…`,任一标识命中都归入同一文件夹 —— 不同单位有的按姓名、有的按证号命名文件也不会"分家";支持从 Excel 导入名单;同名人员自动用证号后 4 位区分文件夹。
- **最长匹配优先**:名单同时有"张三"和"张三丰"时,张三丰的文件不会误归给张三。
- **身份证号识别**:未命中名单的文件,按文件名中的身份证号自动归类;18 位号码做 **GB 11643 校验位验证**(订单号等 18 位数字不再误判),支持 15 位老号码并自动与 18 位互认。
- **来源单位标注**:以压缩包文件名为"来源单位",可选人员文件夹下按单位建子文件夹、或文件名加【单位】前缀。
- **反馈核对表**:自动生成"人员 × 单位"矩阵(CSV + xlsx,空格标黄),哪个单位没反馈哪个人一目了然。
- **内容匹配(可选)**:文件名未命中时,读取 Excel / Word / PDF / 文本内容查找名单中的人。
- **Excel 按人拆分(可选)**:一个表里有多个人的行时,按行拆成每人一份,原表保留在"原始反馈"。
- **内容去重(可选)**:同一人员文件夹内,多个单位反馈的相同文件只留一份。

### 易用性
- **试运行预览**:先列出"哪个文件 → 哪个文件夹"清单,确认后再执行。
- **进度条 + 可取消**;日志同时写入输出目录 `分类日志_时间.txt`。
- **拖拽添加**(装 tkinterdnd2 后)压缩包 / 文件夹。
- **配置记忆**:输出目录、名单、选项自动保存;支持保存 / 加载任务模板(同一批人查多轮直接复用)。
- **命令行模式**:带参数运行即无界面批处理,可配合计划任务自动处理固定收件目录(`-h` 查看用法)。
- **高分屏清晰**:适配 Windows 125% / 150% / 200% 缩放;装 ttkbootstrap 后界面自动换现代主题。

## 直接运行(需 Python 3.8+)

```bash
# Windows 自带 tkinter;所有第三方依赖都是可选的,缺什么降级什么
pip install -r requirements.txt
python 文件自动分类工具.py            # 图形界面
python 文件自动分类工具.py -h         # 命令行用法
```

命令行示例:

```bash
python 文件自动分类工具.py -i 收件目录 -o 结果目录 --roster 名单.xlsx --content-match
python 文件自动分类工具.py -i a.zip b.rar -o out --kw 张三 --kw "李四,110101199003078515"
```

## 打包成免安装 EXE

```bash
pip install pyinstaller -r requirements.txt

pyinstaller --onefile --windowed --name 文件自动分类工具V2.0 ^
  --icon app.ico --add-data "app.ico;." --add-binary "UnRAR.exe;." ^
  --collect-submodules py7zr --collect-submodules rarfile --collect-submodules pyzipper ^
  --collect-submodules send2trash --collect-submodules openpyxl ^
  --collect-all ttkbootstrap --collect-all tkinterdnd2 ^
  --hidden-import multivolumefile --hidden-import inflate64 --hidden-import pybcj ^
  --hidden-import pyppmd --hidden-import brotli ^
  文件自动分类工具.py
```

生成的 `dist/文件自动分类工具V2.0.exe` 拷到任意 Windows 电脑双击即用,无需安装 Python 或 WinRAR。
(如不需要 Word/PDF 内容匹配,可不装 python-docx / pdfplumber,体积更小。)

## 代码结构

| 位置 | 说明 |
| --- | --- |
| `文件自动分类工具.py` | 入口:双击开界面,带参数走命令行 |
| `fac/extract.py` | 解压(多格式 / 嵌套 / 分卷 / 密码 / 防穿越) |
| `fac/roster.py` | 人员名单(多标识合并、最长匹配、Excel 导入) |
| `fac/pipeline.py` | 主流程调度(预览 / 进度 / 取消 / 去重 / 单位标注) |
| `fac/idcard.py` | 身份证号校验(18 位校验位 / 15 位 / 互转) |
| `fac/password.py` | 密码管理与密码本解析 |
| `fac/content_match.py` | Excel/Word/PDF/文本 内容匹配 |
| `fac/excel_split.py` | Excel 按人拆分 |
| `fac/report.py` | 人员 × 单位 反馈核对表 |
| `fac/gui.py` / `fac/cli.py` | 图形界面 / 命令行 |
| `fac/config.py` | 配置记忆与任务模板 |
| `tests/` | 单元测试(`python -m pytest tests/`) |
| `使用说明.md` | 面向普通用户的详细使用说明 |
| `评估与升级计划.md` | V1.2 评估报告与本次升级的规划 |
| `UnRAR.exe` | RARLAB 官方免费解压器,用于 rar 支持 |

## 隐私说明

本工具处理的往往是公民个人信息:全程本地运行、不联网、不上传任何数据;密码不写入日志;临时文件在任务结束后自动清理。

## 许可

本项目代码采用 [MIT 许可](LICENSE)。

附带的 `UnRAR.exe` 由 RARLAB 提供,遵循其[自身许可](https://www.rarlab.com/license.htm)(禁止用于重建 RAR 压缩算法),不受本项目 MIT 许可覆盖。
