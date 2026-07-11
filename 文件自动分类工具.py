# -*- coding: utf-8 -*-
"""
文件自动分类工具
================
功能:
  1. 自动解压 zip / 7z / rar 压缩包(支持嵌套压缩包)。
  2. 按【文件名】中的关键字(人名、公司名、身份证号等)把文件分类到不同文件夹。
  3. 可选"自动识别身份证号"模式:未命中关键字的文件,按文件名中的18位身份证号自动分类。
  4. 一个文件命中多个关键字时,可选择:只归第一个 / 复制到每个文件夹。
  5. 未命中任何关键字的文件,统一放入"未分类"文件夹。

只按文件名匹配,不读取文件内部内容 —— 快、稳,Excel/Word/PDF 一视同仁。

作者: Claude  |  运行环境: Windows + Python 3.8 及以上
"""

import os
import re
import sys
import shutil
import zipfile
import tempfile
import threading
import traceback

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

# ---------- 可选依赖(缺失时自动降级,不影响 zip 处理) ----------
try:
    import py7zr           # 处理 .7z
    HAS_7Z = True
except Exception:
    HAS_7Z = False

try:
    import rarfile         # 处理 .rar (需系统装 unrar/WinRAR)
    HAS_RAR = True
except Exception:
    HAS_RAR = False


# ---------- 资源路径 & 高分屏 ----------

def resource_path(rel: str) -> str:
    """兼容 PyInstaller 打包:返回资源文件的真实路径。"""
    base = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


# 让 rarfile 使用随程序一起打包的 UnRAR.exe,目标电脑无需安装 WinRAR/unrar。
if HAS_RAR:
    try:
        _bundled_unrar = resource_path('UnRAR.exe')
        if os.path.exists(_bundled_unrar):
            rarfile.UNRAR_TOOL = _bundled_unrar
    except Exception:
        pass


def enable_hidpi():
    """让程序在 Windows 高分屏(缩放 125%/150%/200%)下清晰显示。
    必须在创建 Tk() 窗口之前调用。"""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            # Per-Monitor DPI Aware（Win8.1+),最清晰
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            # 退回到系统级 DPI 感知(旧系统)
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


# ---------- 压缩包密码管理 ----------

class PasswordManager:
    """密码尝试顺序:已验证成功的密码 → 密码本候选(seeds)→ 弹框询问。"""

    def __init__(self, ask_cb, seeds=None):
        # ask_cb(archive_name, attempt) -> str | None(None 表示用户取消)
        self.ask_cb = ask_cb
        self.verified = []       # 已验证成功的密码(优先复用)
        self.seeds = []          # 密码本读取的候选密码
        for s in (seeds or []):
            if s and s not in self.seeds:
                self.seeds.append(s)

    def candidates(self):
        out = list(self.verified)
        for s in self.seeds:
            if s not in out:
                out.append(s)
        return out

    def add(self, pwd):
        if pwd and pwd not in self.verified:
            self.verified.insert(0, pwd)

    def prompt(self, name, attempt):
        return self.ask_cb(name, attempt)


# ---------- 密码本解析 & 删除到回收站 ----------

def parse_password_lines(text: str):
    """从一段文本里提取候选密码。兼容"文件名 密码 / 文件名:密码 / 文件名=密码"等格式。"""
    cands = []

    def _add(v):
        v = v.strip().strip('"').strip("'")
        if v and len(v) <= 128 and v not in cands:
            cands.append(v)

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        _add(line)  # 整行也作为候选(纯密码列表的情况)
        for sep in (':', '：', '=', '\t', '，', ','):
            if sep in line:
                _add(line.split(sep, 1)[1])   # 分隔符右侧
                _add(line.rsplit(sep, 1)[1])
        ws = line.split()
        if len(ws) >= 2:
            _add(ws[-1])                       # 多空格分隔时取最后一段
    return cands


def load_password_candidates(paths, log, max_count=300):
    """从若干 txt 文件读取候选密码(自动尝试多种中文编码)。"""
    cands = []
    for p in paths:
        raw = None
        for enc in ('utf-8-sig', 'gbk', 'utf-16', 'utf-8'):
            try:
                with open(p, 'r', encoding=enc) as f:
                    raw = f.read()
                break
            except Exception:
                continue
        if raw is None:
            log(f'  [提示] 密码本读取失败(编码不识别): {os.path.basename(p)}')
            continue
        for c in parse_password_lines(raw):
            if c not in cands:
                cands.append(c)
                if len(cands) >= max_count:
                    return cands
    return cands


def delete_to_trash(path: str):
    """把文件移入回收站;失败时退回永久删除。返回描述用的方式字符串。"""
    try:
        from send2trash import send2trash
        send2trash(os.path.abspath(path))
        return '回收站'
    except Exception:
        os.remove(path)
        return '永久删除'


# ==================== 核心逻辑 ====================

# 18位身份证正则:17位数字 + 最后一位数字或 X
ID_PATTERN = re.compile(r'(?<!\d)(\d{17}[\dXx])(?!\d)')

ARCHIVE_EXTS = ('.zip', '.7z', '.rar')


def safe_folder_name(name: str) -> str:
    """把关键字转成合法的文件夹名,去掉 Windows 不允许的字符。"""
    name = name.strip()
    for ch in r'\/:*?"<>|':
        name = name.replace(ch, '_')
    return name.strip(' .') or '未命名'


def _fix_zip_name(info) -> str:
    """修复 zip 中文文件名乱码(老式 zip 可能用 cp437/gbk 编码)。"""
    raw = info.filename
    if info.flag_bits & 0x800:      # 已标记 UTF-8
        return raw
    try:
        return raw.encode('cp437').decode('gbk')
    except Exception:
        try:
            return raw.encode('cp437').decode('utf-8')
        except Exception:
            return raw


def _resolve_zip_password(zf, infos, pm, name, log):
    """为加密 zip 找到可用密码。返回密码 bytes;无需密码返回 None;取消/失败返回 False。"""
    enc = next((i for i in infos if (i.flag_bits & 0x1) and not i.is_dir()), None)
    if enc is None:
        return None

    def test(pwd):
        try:
            with zf.open(enc, pwd=pwd.encode('utf-8')) as fp:
                fp.read(1)
            return True
        except Exception:
            return False

    for c in pm.candidates():
        if test(c):
            return c.encode('utf-8')
    for attempt in range(1, 4):
        pwd = pm.prompt(name, attempt)
        if pwd is None:
            return False
        if test(pwd):
            pm.add(pwd)
            return pwd.encode('utf-8')
        log(f'  [提示] 密码错误: {name}')
    log(f'  [跳过] 密码尝试次数过多: {name}')
    return False


def _extract_zip(archive_path, dest_dir, log, pm):
    name = os.path.basename(archive_path)
    with zipfile.ZipFile(archive_path) as zf:
        infos = zf.infolist()
        encrypted = any(i.flag_bits & 0x1 for i in infos)
        pwd = None
        if encrypted:
            pwd = _resolve_zip_password(zf, infos, pm, name, log)
            if pwd is False:
                log(f'  [跳过] 未提供正确密码: {name}')
                return False
        for info in infos:
            target = os.path.join(dest_dir, _fix_zip_name(info))
            if info.is_dir():
                os.makedirs(target, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with zf.open(info, pwd=pwd) as src, open(target, 'wb') as out:
                    shutil.copyfileobj(src, out)
    return True


def _extract_7z(archive_path, dest_dir, log, pm):
    name = os.path.basename(archive_path)
    # 先判断是否需要密码
    need = False
    try:
        with py7zr.SevenZipFile(archive_path, mode='r') as z:
            need = z.needs_password()
        if not need:
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                z.extractall(path=dest_dir)
            return True
    except Exception:
        need = True  # 打开就失败,通常是加密头

    def extract_with(pwd):
        try:
            with py7zr.SevenZipFile(archive_path, mode='r', password=pwd) as z:
                z.extractall(path=dest_dir)
            return True
        except Exception:
            return False

    for c in pm.candidates():
        if extract_with(c):
            return True
    for attempt in range(1, 4):
        pwd = pm.prompt(name, attempt)
        if pwd is None:
            log(f'  [跳过] 未提供密码: {name}')
            return False
        if extract_with(pwd):
            pm.add(pwd)
            return True
        log(f'  [提示] 密码错误: {name}')
    log(f'  [跳过] 密码尝试次数过多: {name}')
    return False


def _extract_rar(archive_path, dest_dir, log, pm):
    name = os.path.basename(archive_path)
    rf = rarfile.RarFile(archive_path)
    if not rf.needs_password():
        rf.extractall(path=dest_dir)
        return True

    def extract_with(pwd):
        try:
            rf.setpassword(pwd)
            rf.extractall(path=dest_dir)
            return True
        except Exception:
            return False

    for c in pm.candidates():
        if extract_with(c):
            return True
    for attempt in range(1, 4):
        pwd = pm.prompt(name, attempt)
        if pwd is None:
            log(f'  [跳过] 未提供密码: {name}')
            return False
        if extract_with(pwd):
            pm.add(pwd)
            return True
        log(f'  [提示] 密码错误: {name}')
    log(f'  [跳过] 密码尝试次数过多: {name}')
    return False


def extract_archive(archive_path: str, dest_dir: str, log, pm):
    """把一个压缩包解压到 dest_dir。返回是否成功。pm 为密码管理器。"""
    ext = os.path.splitext(archive_path)[1].lower()
    try:
        if ext == '.zip':
            return _extract_zip(archive_path, dest_dir, log, pm)
        elif ext == '.7z':
            if not HAS_7Z:
                log(f'  [跳过] 未安装 py7zr,无法解压 7z: {os.path.basename(archive_path)}')
                return False
            return _extract_7z(archive_path, dest_dir, log, pm)
        elif ext == '.rar':
            if not HAS_RAR:
                log(f'  [跳过] 未安装 rarfile/unrar,无法解压 rar: {os.path.basename(archive_path)}')
                return False
            return _extract_rar(archive_path, dest_dir, log, pm)
        else:
            return False
    except Exception as e:
        log(f'  [错误] 解压失败 {os.path.basename(archive_path)}: {e}')
        return False


def extract_all_recursive(archive_path: str, dest_dir: str, log, pm, failures, depth=0):
    """递归解压:一个压缩包里若还有压缩包,继续解压(最多 5 层防死循环)。
    解压失败的压缩包(含嵌套)路径会追加到 failures 列表。返回顶层是否成功。"""
    if depth > 5:
        log(f'  [提示] 嵌套层数过深,停止: {os.path.basename(archive_path)}')
        return False
    ok = extract_archive(archive_path, dest_dir, log, pm)
    if not ok:
        failures.append(archive_path)
        return False
    # 查找解压出来的嵌套压缩包,继续递归解压
    for root, _, files in os.walk(dest_dir):
        for f in files:
            if f.lower().endswith(ARCHIVE_EXTS):
                nested = os.path.join(root, f)
                sub = nested + '_解压'
                os.makedirs(sub, exist_ok=True)
                extract_all_recursive(nested, sub, log, pm, failures, depth + 1)
    return True


def unique_path(dst_folder: str, filename: str) -> str:
    """避免同名覆盖:若已存在则加 (1)(2)…"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dst_folder, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dst_folder, f'{base}({i}){ext}')
        i += 1
    return candidate


def classify_file(filepath: str, keywords, out_dir: str,
                  copy_to_each: bool, auto_id: bool, log,
                  stats: dict):
    """对单个文件按文件名分类。"""
    fname = os.path.basename(filepath)

    # 1) 关键字匹配(按输入顺序)
    matched = [kw for kw in keywords if kw and kw in fname]

    targets = []  # 要放入的文件夹名列表
    if matched:
        if copy_to_each:
            targets = [safe_folder_name(kw) for kw in matched]
        else:
            targets = [safe_folder_name(matched[0])]
    else:
        # 2) 未命中关键字,尝试自动识别身份证号
        if auto_id:
            m = ID_PATTERN.search(fname)
            if m:
                targets = [safe_folder_name(m.group(1))]
        if not targets:
            targets = ['未分类']

    # 3) 复制到目标文件夹
    for t in targets:
        folder = os.path.join(out_dir, t)
        os.makedirs(folder, exist_ok=True)
        dst = unique_path(folder, fname)
        shutil.copy2(filepath, dst)
        stats[t] = stats.get(t, 0) + 1


def run_job(inputs, out_dir, keywords, copy_to_each, auto_id, log, done_cb,
            ask_password, pw_files, auto_pw_txt, delete_ok):
    """主流程(在后台线程运行)。inputs 是压缩包或文件夹路径的列表。"""
    stats = {}
    try:
        with tempfile.TemporaryDirectory(prefix='分类_') as tmp:
            # ---- 收集压缩包,同时收集可作密码本的 txt ----
            archives = []
            txt_paths = list(pw_files)      # 用户手动指定的密码本
            txt_dirs = set()                # 待扫描 txt 的目录
            for p in inputs:
                if os.path.isdir(p):
                    for root, _, files in os.walk(p):
                        for f in files:
                            low = f.lower()
                            if low.endswith(ARCHIVE_EXTS):
                                archives.append(os.path.join(root, f))
                            elif auto_pw_txt and low.endswith('.txt'):
                                txt_paths.append(os.path.join(root, f))
                elif p.lower().endswith(ARCHIVE_EXTS):
                    archives.append(p)
                    if auto_pw_txt:
                        txt_dirs.add(os.path.dirname(p))
            # 扫描单独选中的压缩包所在目录里的 txt
            for d in txt_dirs:
                try:
                    for f in os.listdir(d):
                        if f.lower().endswith('.txt'):
                            txt_paths.append(os.path.join(d, f))
                except Exception:
                    pass
            # 去重
            seen = set()
            txt_paths = [x for x in txt_paths if not (x in seen or seen.add(x))]

            if not archives:
                log('未找到任何压缩包(zip/7z/rar)。请检查所选路径。')
                done_cb(stats)
                return

            # ---- 读取密码本作为自动尝试的候选密码 ----
            seeds = load_password_candidates(txt_paths, log) if txt_paths else []
            if seeds:
                log(f'已从 {len(txt_paths)} 个 txt 读取 {len(seeds)} 个候选密码,遇到加密包将自动尝试。')
            pm = PasswordManager(ask_password, seeds=seeds)

            failed_dir = os.path.join(out_dir, '解压失败')

            def stash_failed(arc_path):
                """把解压失败的压缩包复制到「解压失败」文件夹。"""
                os.makedirs(failed_dir, exist_ok=True)
                dst = unique_path(failed_dir, os.path.basename(arc_path))
                try:
                    shutil.copy2(arc_path, dst)
                except Exception as e:
                    log(f'  [提示] 复制失败包出错 {os.path.basename(arc_path)}: {e}')

            log(f'共发现 {len(archives)} 个压缩包,开始解压(支持多级嵌套)...')
            success_archives = []   # 完全成功、可安全删除的顶层原始压缩包
            failed_count = 0
            for i, arc in enumerate(archives, 1):
                log(f'[{i}/{len(archives)}] 解压: {os.path.basename(arc)}')
                sub = os.path.join(tmp, f'arc_{i}')
                os.makedirs(sub, exist_ok=True)
                failures = []
                ok = extract_all_recursive(arc, sub, log, pm, failures)
                if ok and not failures:
                    success_archives.append(arc)
                for fa in failures:
                    stash_failed(fa)
                    failed_count += 1

            # ---- 遍历解压出的所有文件进行分类(只处理最终文件,跳过压缩包) ----
            log('解压完成,开始按文件名分类...')
            file_count = 0
            for root, _, files in os.walk(tmp):
                for f in files:
                    if f.lower().endswith(ARCHIVE_EXTS):
                        continue  # 跳过压缩包本身,只分类最终解压出来的文件
                    fp = os.path.join(root, f)
                    classify_file(fp, keywords, out_dir,
                                  copy_to_each, auto_id, log, stats)
                    file_count += 1

            log(f'\n分类完成!共处理 {file_count} 个文件。')
            if failed_count:
                log(f'有 {failed_count} 个压缩包解压失败,已放入「解压失败」文件夹。')
            log('各文件夹文件数:')
            for k in sorted(stats):
                log(f'  {k} : {stats[k]} 个')

            # ---- 可选:删除已成功解压的原始压缩包 ----
            if delete_ok and success_archives:
                log(f'\n开始删除 {len(success_archives)} 个已成功解压的压缩包...')
                for arc in success_archives:
                    try:
                        way = delete_to_trash(arc)
                        log(f'  已删除({way}): {os.path.basename(arc)}')
                    except Exception as e:
                        log(f'  [提示] 删除失败 {os.path.basename(arc)}: {e}')
    except Exception:
        log('运行出错:\n' + traceback.format_exc())
    finally:
        done_cb(stats)


# ==================== 图形界面 ====================

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('文件自动分类工具  V1.2')
        self._setup_dpi_scaling()
        self._set_icon()
        self.inputs = []
        self.build_ui()

    def _setup_dpi_scaling(self):
        """根据屏幕 DPI 调整 Tk 缩放与字体、窗口大小,保证高分屏清晰不糊。"""
        try:
            dpi = self.winfo_fpixels('1i')   # 每英寸像素:96=100%,144=150%
        except Exception:
            dpi = 96.0
        try:
            self.tk.call('tk', 'scaling', dpi / 72.0)
        except Exception:
            pass
        # 用点(pt)为单位设置默认字体,随缩放自动放大,清晰锐利
        try:
            import tkinter.font as tkfont
            for fname in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont',
                          'TkHeadingFont', 'TkFixedFont'):
                try:
                    f = tkfont.nametofont(fname)
                    f.configure(family='Microsoft YaHei UI', size=10)
                except Exception:
                    pass
        except Exception:
            pass
        # 窗口大小按缩放比例放大,避免高分屏下界面被挤压
        scale = dpi / 96.0
        w, h = int(820 * scale), int(720 * scale)
        self.geometry(f'{w}x{h}')
        self.minsize(int(660 * scale), int(580 * scale))

    def _set_icon(self):
        """设置窗口图标。"""
        try:
            self.iconbitmap(resource_path('app.ico'))
        except Exception:
            pass

    def build_ui(self):
        pad = {'padx': 8, 'pady': 4}

        # --- 1. 选择压缩包 ---
        f1 = ttk.LabelFrame(self, text='第一步:选择压缩包(可多选)或含压缩包的文件夹')
        f1.pack(fill='x', **pad)
        self.lb_inputs = tk.Listbox(f1, height=4)
        self.lb_inputs.pack(side='left', fill='x', expand=True, padx=6, pady=6)
        b1 = ttk.Frame(f1); b1.pack(side='right', padx=6)
        ttk.Button(b1, text='添加压缩包', command=self.add_files).pack(fill='x', pady=2)
        ttk.Button(b1, text='添加文件夹', command=self.add_folder).pack(fill='x', pady=2)
        ttk.Button(b1, text='清空', command=self.clear_inputs).pack(fill='x', pady=2)

        # --- 2. 输出目录 ---
        f2 = ttk.LabelFrame(self, text='第二步:选择分类结果保存到哪里')
        f2.pack(fill='x', **pad)
        self.var_out = tk.StringVar()
        ttk.Entry(f2, textvariable=self.var_out).pack(side='left', fill='x', expand=True, padx=6, pady=6)
        ttk.Button(f2, text='浏览...', command=self.choose_out).pack(side='right', padx=6)

        # --- 3. 关键字 ---
        f3 = ttk.LabelFrame(self, text='第三步:输入关键字(人名/公司名/身份证号等),每行一个')
        f3.pack(fill='both', expand=True, **pad)
        self.txt_kw = scrolledtext.ScrolledText(f3, height=6)
        self.txt_kw.pack(fill='both', expand=True, padx=6, pady=6)
        self.txt_kw.insert('1.0', '# 示例(以#开头的行会被忽略):\n张三\n李四\n某某有限公司\n')

        # --- 4. 选项 ---
        f4 = ttk.LabelFrame(self, text='第四步:分类选项')
        f4.pack(fill='x', **pad)
        self.var_multi = tk.StringVar(value='first')
        ttk.Radiobutton(f4, text='一个文件命中多个关键字 → 只归入第一个命中的',
                        variable=self.var_multi, value='first').pack(anchor='w', padx=8)
        ttk.Radiobutton(f4, text='一个文件命中多个关键字 → 复制到每个命中的文件夹',
                        variable=self.var_multi, value='each').pack(anchor='w', padx=8)
        self.var_autoid = tk.BooleanVar(value=True)
        ttk.Checkbutton(f4, text='自动识别身份证号:未命中关键字的文件,按文件名中的18位身份证号分类',
                        variable=self.var_autoid).pack(anchor='w', padx=8, pady=(4, 2))

        # 密码本:自动读取输入文件夹里的 txt 作为候选密码
        self.var_pwtxt = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f4, text='自动把输入文件夹里的 .txt 当密码本:加密压缩包先自动尝试里面的密码,失败再弹框',
            variable=self.var_pwtxt).pack(anchor='w', padx=8, pady=2)
        pf = ttk.Frame(f4); pf.pack(fill='x', padx=8, pady=2)
        ttk.Label(pf, text='额外密码本(可选):').pack(side='left')
        self.var_pwfile = tk.StringVar()
        ttk.Entry(pf, textvariable=self.var_pwfile).pack(side='left', fill='x', expand=True, padx=4)
        ttk.Button(pf, text='选择...', command=self.choose_pwfile).pack(side='left')

        # 删除已成功解压的压缩包(破坏性,默认关闭)
        self.var_delok = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            f4, text='⚠ 分类完成后,删除已成功解压的压缩包(移入回收站;失败的不删)',
            variable=self.var_delok).pack(anchor='w', padx=8, pady=(2, 6))

        # --- 5. 运行 + 日志 ---
        f5 = ttk.Frame(self)
        f5.pack(fill='x', **pad)
        self.btn_run = ttk.Button(f5, text='开始分类', command=self.start)
        self.btn_run.pack(side='left')
        ttk.Button(f5, text='打开结果文件夹', command=self.open_out).pack(side='left', padx=8)
        rar_txt = 'rar√(内置UnRAR)' if HAS_RAR else 'rar✗'
        fmt = 'zip√  ' + ('7z√  ' if HAS_7Z else '7z✗  ') + rar_txt
        ttk.Label(f5, text='支持格式: ' + fmt, foreground='#666').pack(side='right')

        self.log_box = scrolledtext.ScrolledText(self, height=8, state='disabled')
        self.log_box.pack(fill='both', expand=True, **pad)

    # ---------- 界面操作 ----------
    def add_files(self):
        files = filedialog.askopenfilenames(
            title='选择压缩包',
            filetypes=[('压缩包', '*.zip *.7z *.rar'), ('所有文件', '*.*')])
        for f in files:
            if f not in self.inputs:
                self.inputs.append(f)
                self.lb_inputs.insert('end', f)

    def add_folder(self):
        d = filedialog.askdirectory(title='选择含压缩包的文件夹')
        if d and d not in self.inputs:
            self.inputs.append(d)
            self.lb_inputs.insert('end', d + '  (文件夹)')

    def clear_inputs(self):
        self.inputs = []
        self.lb_inputs.delete(0, 'end')

    def choose_out(self):
        d = filedialog.askdirectory(title='选择输出目录')
        if d:
            self.var_out.set(d)

    def choose_pwfile(self):
        f = filedialog.askopenfilename(
            title='选择密码本 txt',
            filetypes=[('文本文件', '*.txt'), ('所有文件', '*.*')])
        if f:
            self.var_pwfile.set(f)

    def open_out(self):
        out = self.var_out.get().strip()
        if out and os.path.isdir(out):
            try:
                os.startfile(out)  # 仅 Windows
            except Exception:
                messagebox.showinfo('提示', f'结果目录:\n{out}')
        else:
            messagebox.showwarning('提示', '请先选择有效的输出目录。')

    def log(self, msg):
        def _append():
            self.log_box.configure(state='normal')
            self.log_box.insert('end', msg + '\n')
            self.log_box.see('end')
            self.log_box.configure(state='disabled')
        self.after(0, _append)

    def get_keywords(self):
        raw = self.txt_kw.get('1.0', 'end').splitlines()
        kws = []
        for line in raw:
            line = line.strip()
            if line and not line.startswith('#'):
                kws.append(line)
        return kws

    def ask_password(self, archive_name, attempt):
        """在主线程弹出密码输入框,供后台线程调用(阻塞等待用户输入)。
        返回用户输入的密码字符串;用户取消时返回 None。"""
        result = {}
        ev = threading.Event()

        def _prompt():
            from tkinter import simpledialog
            if attempt > 1:
                msg = f'密码错误,请重新输入。\n\n压缩包「{archive_name}」需要解压密码:'
            else:
                msg = f'该压缩包有密码。\n\n压缩包「{archive_name}」需要解压密码:'
            pwd = simpledialog.askstring('需要解压密码', msg, show='*', parent=self)
            result['pwd'] = pwd
            ev.set()

        self.after(0, _prompt)
        ev.wait()
        return result.get('pwd')

    def start(self):
        if not self.inputs:
            messagebox.showwarning('提示', '请先添加压缩包或文件夹。')
            return
        out = self.var_out.get().strip()
        if not out:
            messagebox.showwarning('提示', '请先选择输出目录。')
            return
        os.makedirs(out, exist_ok=True)
        keywords = self.get_keywords()
        auto_id = self.var_autoid.get()
        if not keywords and not auto_id:
            messagebox.showwarning('提示', '请至少输入关键字,或勾选"自动识别身份证号"。')
            return

        # 收集密码本与删除选项
        auto_pw_txt = self.var_pwtxt.get()
        pw_files = []
        pwf = self.var_pwfile.get().strip()
        if pwf:
            if os.path.isfile(pwf):
                pw_files.append(pwf)
            else:
                messagebox.showwarning('提示', '指定的密码本文件不存在,已忽略。')
        delete_ok = self.var_delok.get()
        if delete_ok:
            if not messagebox.askyesno(
                    '确认删除',
                    '分类完成后,将把【已成功解压】的原始压缩包移入回收站。\n'
                    '解压失败的压缩包不会删除。\n\n确定要继续吗?'):
                return

        self.btn_run.configure(state='disabled', text='正在处理...')
        self.log_box.configure(state='normal')
        self.log_box.delete('1.0', 'end')
        self.log_box.configure(state='disabled')

        copy_to_each = (self.var_multi.get() == 'each')

        def done(stats):
            self.after(0, lambda: self.btn_run.configure(state='normal', text='开始分类'))
            self.after(0, lambda: messagebox.showinfo('完成', '分类完成!结果已保存到输出目录。'))

        t = threading.Thread(
            target=run_job,
            args=(list(self.inputs), out, keywords, copy_to_each, auto_id,
                  self.log, done, self.ask_password,
                  pw_files, auto_pw_txt, delete_ok),
            daemon=True)
        t.start()


if __name__ == '__main__':
    enable_hidpi()
    App().mainloop()
