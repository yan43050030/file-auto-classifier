# 文件自动分类工具 (File Auto Classifier)

一个带图形界面的 Windows 小工具:**自动解压压缩包(支持多级嵌套),再按文件名里的关键字(人名 / 公司名 / 身份证号等)把文件分类到不同文件夹。**

只按文件名匹配、不读取文件内部内容 —— 快、稳,Excel / Word / PDF 一视同仁。

## 功能特性

- **多格式解压**:zip / 7z / rar 全支持;内置官方 UnRAR.exe,打包成 exe 后目标电脑无需安装 WinRAR。
- **多级嵌套**:压缩包里套压缩包(最多 5 层)自动递归解压,只对最终解压出的文件分类。
- **关键字分类**:每行一个关键字(人名、公司名、身份证号等),按文件名归类。
- **身份证号自动识别**:未命中关键字的文件,自动识别文件名中的 18 位身份证号建文件夹归类。
- **命中多个关键字**:可选“只归第一个”或“复制到每个命中的文件夹”。
- **加密压缩包**:遇到有密码的包会弹出密码输入框;密码正确会缓存复用。
- **密码本自动尝试**:自动读取输入文件夹里的 `.txt` 作为密码本(兼容 `文件名: 密码` 等格式),加密包先自动逐个尝试,失败再弹框。
- **解压失败归集**:解压失败的包(含嵌套内层)自动收进“解压失败”文件夹,绝不悄悄丢文件。
- **成功后删除(可选)**:分类完成后可把已成功解压的原始压缩包移入回收站(默认关闭,操作前二次确认)。
- **高分屏清晰**:适配 Windows 125% / 150% / 200% 缩放。
- **原文件安全**:分类是“复制”,不改动原始压缩包;同名文件自动加 `(1)(2)` 区分。

## 直接运行(需 Python 3.8+)

```bash
# Windows 自带 tkinter,无需额外安装
pip install py7zr rarfile send2trash   # 可选:支持 7z/rar 与回收站删除
python 文件自动分类工具.py
```

## 打包成免安装 EXE

```bash
pip install pyinstaller py7zr rarfile send2trash

pyinstaller --onefile --windowed --name 文件自动分类工具V1.2 ^
  --icon app.ico --add-data "app.ico;." --add-binary "UnRAR.exe;." ^
  --collect-submodules py7zr --collect-submodules rarfile --collect-submodules send2trash ^
  --hidden-import multivolumefile --hidden-import inflate64 --hidden-import pybcj ^
  --hidden-import pyppmd --hidden-import brotli ^
  文件自动分类工具.py
```

生成的 `dist/文件自动分类工具V1.2.exe` 拷到任意 Windows 电脑双击即用,无需安装 Python 或 WinRAR。

## 生成图标

```bash
pip install pillow
python make_icon.py   # 生成 app.ico / app.png
```

## 文件说明

| 文件 | 说明 |
| --- | --- |
| `文件自动分类工具.py` | 主程序(GUI + 全部逻辑) |
| `使用说明.md` | 面向普通用户的详细使用说明 |
| `make_icon.py` | 用 Pillow 生成软件图标 |
| `app.ico` / `app.png` | 软件图标 |
| `UnRAR.exe` | RARLAB 官方免费解压器,用于 rar 支持 |

## 许可

本项目代码采用 [MIT 许可](LICENSE)。

附带的 `UnRAR.exe` 由 RARLAB 提供,遵循其[自身许可](https://www.rarlab.com/license.htm)(禁止用于重建 RAR 压缩算法),不受本项目 MIT 许可覆盖。
