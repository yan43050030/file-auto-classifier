# -*- coding: utf-8 -*-
"""解压模块:zip(含 AES)/7z/rar/tar/gz,多级嵌套,分卷识别,路径穿越防护,长路径。"""

import os
import re
import gzip
import shutil
import zipfile
import tarfile

from .util import long_path, resource_path

# ---------- 可选依赖(缺失时自动降级) ----------
try:
    import pyzipper                    # zip AES 加密支持
    _ZipOpen = pyzipper.AESZipFile
    HAS_AES = True
except Exception:
    _ZipOpen = zipfile.ZipFile
    HAS_AES = False

try:
    import py7zr
    HAS_7Z = True
except Exception:
    HAS_7Z = False

try:
    import multivolumefile             # .7z.001 分卷
    HAS_MV = True
except Exception:
    HAS_MV = False

try:
    import rarfile
    HAS_RAR = True
except Exception:
    HAS_RAR = False

# 让 rarfile 使用随程序一起打包的 UnRAR.exe,目标电脑无需安装 WinRAR/unrar。
if HAS_RAR:
    try:
        _bundled_unrar = resource_path('UnRAR.exe')
        if os.path.exists(_bundled_unrar):
            rarfile.UNRAR_TOOL = _bundled_unrar
    except Exception:
        pass


_TAR_EXTS = ('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')
_PART_RAR_RE = re.compile(r'\.part(\d+)\.rar$', re.I)
_7Z_VOL_RE = re.compile(r'\.7z\.(\d{3})$', re.I)
_ZIP_VOL_RE = re.compile(r'\.zip\.(\d{3})$', re.I)
_OLD_VOL_RE = re.compile(r'\.[rz]\d{2}$', re.I)   # .r00 / .z01 老式分卷


def archive_kind(fname: str):
    """识别文件是什么压缩包。
    返回: 'zip'/'7z'/'rar'/'tar'/'gz'/'7z-vol'(7z 首卷)
          'volume-later'(分卷的后续卷,跳过即可)
          'volume-unsupported'(不支持的分卷格式)
          None(不是压缩包)"""
    low = fname.lower()
    m = _PART_RAR_RE.search(low)
    if m:
        return 'rar' if int(m.group(1)) == 1 else 'volume-later'
    m = _7Z_VOL_RE.search(low)
    if m:
        return '7z-vol' if int(m.group(1)) == 1 else 'volume-later'
    if _ZIP_VOL_RE.search(low):
        return 'volume-unsupported'
    if _OLD_VOL_RE.search(low):
        return 'volume-later'
    if low.endswith('.zip'):
        return 'zip'
    if low.endswith('.7z'):
        return '7z'
    if low.endswith('.rar'):
        return 'rar'
    if low.endswith(_TAR_EXTS):
        return 'tar'
    if low.endswith('.gz'):
        return 'gz'
    return None


def is_archive(fname: str) -> bool:
    return archive_kind(fname) is not None


def unit_name(archive_path: str) -> str:
    """从顶层压缩包名推出"来源单位"名:去扩展名、去分卷序号。"""
    base = os.path.basename(archive_path)
    for pat in (_PART_RAR_RE, _7Z_VOL_RE, _ZIP_VOL_RE):
        m = pat.search(base)
        if m:
            return base[:m.start()]
    stem = base
    low = base.lower()
    for ext in _TAR_EXTS + ('.zip', '.7z', '.rar', '.gz'):
        if low.endswith(ext):
            stem = base[:len(base) - len(ext)]
            break
    return stem or base


def safe_target(dest_dir: str, member_name: str):
    """把压缩包成员名安全地映射到目标目录内的路径。
    越界(绝对路径 / ..)返回 None —— 防 zip slip 路径穿越。"""
    name = str(member_name).replace('\\', '/')
    name = re.sub(r'^[A-Za-z]:', '', name).lstrip('/')
    dest_abs = os.path.abspath(dest_dir)
    target = os.path.normpath(os.path.join(dest_abs, name))
    if target != dest_abs and not target.startswith(dest_abs + os.sep):
        return None
    return target


def _find_password(name, pm, log, test):
    """按 已验证→密码本→询问用户 的顺序找可用密码。
    test(pwd:str)->bool 只验证一个最小文件,避免整包试错。
    返回密码字符串;用户取消或超次数返回 False。"""
    for c in pm.candidates():
        if test(c):
            pm.add(c)
            return c
    for attempt in range(1, 4):
        pwd = pm.prompt(name, attempt)
        if pwd is None:
            return False
        if test(pwd):
            pm.add(pwd)
            return pwd
        log(f'  [提示] 密码错误: {name}')
    log(f'  [跳过] 密码尝试次数过多: {name}')
    return False


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


# ---------- zip ----------

def _extract_zip(archive_path, dest_dir, log, pm):
    """返回 'ok' | 'skip_pw' | 'fail'。"""
    name = os.path.basename(archive_path)
    with _ZipOpen(archive_path) as zf:
        infos = zf.infolist()
        enc_infos = [i for i in infos if (i.flag_bits & 0x1) and not i.is_dir()]
        pwd = None
        if enc_infos:
            if not HAS_AES:
                log(f'  [提示] 未安装 pyzipper,若 {name} 为 AES 加密将无法解压')
            smallest = min(enc_infos, key=lambda i: i.file_size)

            def test(p):
                try:
                    with zf.open(smallest, pwd=p.encode('utf-8')) as fp:
                        fp.read(1)
                    return True
                except Exception:
                    return False

            got = _find_password(name, pm, log, test)
            if got is False:
                log(f'  [跳过] 未提供正确密码: {name}')
                return 'skip_pw'
            pwd = got.encode('utf-8')
        for info in infos:
            fname = _fix_zip_name(info)
            target = safe_target(dest_dir, fname)
            if target is None:
                log(f'  [安全] 跳过越界路径: {fname}')
                continue
            if info.is_dir():
                os.makedirs(long_path(target), exist_ok=True)
                continue
            os.makedirs(long_path(os.path.dirname(target)), exist_ok=True)
            with zf.open(info, pwd=pwd) as src, open(long_path(target), 'wb') as out:
                shutil.copyfileobj(src, out)
    return 'ok'


# ---------- 7z ----------

def _open_7z(archive_path, pwd=None):
    """打开 7z(支持 .7z.001 分卷)。返回 (SevenZipFile, 需一并关闭的分卷句柄或 None)。"""
    if _7Z_VOL_RE.search(archive_path.lower()):
        if not HAS_MV:
            raise RuntimeError('缺少 multivolumefile,无法处理 .7z.001 分卷')
        base = archive_path[:-4]      # 去掉 .001
        mv = multivolumefile.open(base, mode='rb')
        try:
            return py7zr.SevenZipFile(mv, mode='r', password=pwd), mv
        except Exception:
            mv.close()
            raise
    return py7zr.SevenZipFile(archive_path, mode='r', password=pwd), None


def _7z_needs_password(archive_path):
    try:
        z, mv = _open_7z(archive_path)
        try:
            return z.needs_password()
        finally:
            z.close()
            if mv:
                mv.close()
    except Exception:
        return True      # 打开即失败,通常是加密头


def _test_7z_password(archive_path, pwd):
    """只解压其中最小的一个文件到临时目录验证密码,避免大包整体试错。"""
    import tempfile
    try:
        z, mv = _open_7z(archive_path, pwd)
        try:
            files = [f for f in z.list() if not f.is_directory]
            if files:
                smallest = min(files, key=lambda f: f.uncompressed or 0)
                with tempfile.TemporaryDirectory(prefix='pwtest_') as td:
                    z.extract(path=td, targets=[smallest.filename])
        finally:
            z.close()
            if mv:
                mv.close()
        return True
    except Exception:
        return False


def _7z_extract_all(archive_path, dest_dir, pwd, log):
    z, mv = _open_7z(archive_path, pwd)
    try:
        good = []
        for f in z.list():
            if f.is_directory:
                continue     # 目录由文件条目自动带出,且 '.' 之类条目会让 extract 报错
            if safe_target(dest_dir, f.filename) is None:
                log(f'  [安全] 跳过越界路径: {f.filename}')
            else:
                good.append(f.filename)
        z.extract(path=long_path(dest_dir), targets=good)
    finally:
        z.close()
        if mv:
            mv.close()


def _extract_7z(archive_path, dest_dir, log, pm):
    """返回 'ok' | 'skip_pw' | 'fail'。"""
    name = os.path.basename(archive_path)
    if not _7z_needs_password(archive_path):
        try:
            _7z_extract_all(archive_path, dest_dir, None, log)
            return 'ok'
        except Exception:
            pass  # 少数加密头的包 needs_password 误报 False,落入密码流程

    got = _find_password(name, pm, log,
                         lambda p: _test_7z_password(archive_path, p))
    if got is False:
        log(f'  [跳过] 未提供正确密码: {name}')
        return 'skip_pw'
    _7z_extract_all(archive_path, dest_dir, got, log)
    return 'ok'


# ---------- rar ----------

def _test_rar_password(archive_path, pwd):
    """只读取其中最小的一个文件验证密码。"""
    try:
        rf = rarfile.RarFile(archive_path)
        rf.setpassword(pwd)
        infos = [i for i in rf.infolist() if not i.isdir()]
        if infos:
            smallest = min(infos, key=lambda i: i.file_size or 0)
            with rf.open(smallest) as f:
                f.read(16)
        return True
    except Exception:
        return False


def _rar_extract_all(archive_path, dest_dir, pwd, log):
    rf = rarfile.RarFile(archive_path)
    if pwd:
        rf.setpassword(pwd)
    good = []
    for i in rf.infolist():
        if safe_target(dest_dir, i.filename) is None:
            log(f'  [安全] 跳过越界路径: {i.filename}')
        else:
            good.append(i)
    rf.extractall(path=long_path(dest_dir), members=good)


def _extract_rar(archive_path, dest_dir, log, pm):
    """返回 'ok' | 'skip_pw' | 'fail'。"""
    name = os.path.basename(archive_path)
    try:
        needs = rarfile.RarFile(archive_path).needs_password()
    except Exception:
        needs = True
    if not needs:
        _rar_extract_all(archive_path, dest_dir, None, log)
        return 'ok'

    got = _find_password(name, pm, log,
                         lambda p: _test_rar_password(archive_path, p))
    if got is False:
        log(f'  [跳过] 未提供正确密码: {name}')
        return 'skip_pw'
    _rar_extract_all(archive_path, dest_dir, got, log)
    return 'ok'


# ---------- tar / gz ----------

def _extract_tar(archive_path, dest_dir, log, pm):
    """返回 'ok' (tar 无密码,始终返回 ok 或 raise)。"""
    with tarfile.open(archive_path) as tf:
        for m in tf:
            if not m.isreg():
                continue          # 跳过符号链接/设备文件等
            target = safe_target(dest_dir, m.name)
            if target is None:
                log(f'  [安全] 跳过越界路径: {m.name}')
                continue
            os.makedirs(long_path(os.path.dirname(target)), exist_ok=True)
            src = tf.extractfile(m)
            if src is None:
                continue
            with src, open(long_path(target), 'wb') as out:
                shutil.copyfileobj(src, out)
    return 'ok'


def _extract_gz(archive_path, dest_dir, log, pm):
    """返回 'ok'。"""
    out_name = os.path.basename(archive_path)[:-3] or 'gz解压文件'
    target = safe_target(dest_dir, out_name)
    os.makedirs(long_path(dest_dir), exist_ok=True)
    with gzip.open(archive_path, 'rb') as src, open(long_path(target), 'wb') as out:
        shutil.copyfileobj(src, out)
    return 'ok'


# ---------- 统一入口 ----------

def extract_archive(archive_path: str, dest_dir: str, log, pm) -> str:
    """解压一个压缩包到 dest_dir。
    返回 'ok' | 'skip_pw' | 'fail'。pm 为密码管理器。"""
    kind = archive_kind(os.path.basename(archive_path))
    name = os.path.basename(archive_path)
    try:
        if kind == 'zip':
            return _extract_zip(archive_path, dest_dir, log, pm)
        if kind in ('7z', '7z-vol'):
            if not HAS_7Z:
                log(f'  [跳过] 未安装 py7zr,无法解压 7z: {name}')
                return 'fail'
            if kind == '7z-vol' and not HAS_MV:
                log(f'  [跳过] 未安装 multivolumefile,无法解压 7z 分卷: {name}')
                return 'fail'
            return _extract_7z(archive_path, dest_dir, log, pm)
        if kind == 'rar':
            if not HAS_RAR:
                log(f'  [跳过] 未安装 rarfile/unrar,无法解压 rar: {name}')
                return 'fail'
            return _extract_rar(archive_path, dest_dir, log, pm)
        if kind == 'tar':
            return _extract_tar(archive_path, dest_dir, log, pm)
        if kind == 'gz':
            return _extract_gz(archive_path, dest_dir, log, pm)
        if kind == 'volume-unsupported':
            log(f'  [跳过] 暂不支持 .zip.001 型分卷,请先用 7-Zip 合并: {name}')
            return 'fail'
        return 'fail'
    except Exception as e:
        log(f'  [错误] 解压失败 {name}: {e}')
        return 'fail'


def extract_all_recursive(archive_path: str, dest_dir: str, log, pm,
                          failures, skip_pws, depth=0, cancel=None):
    """递归解压(最多 5 层)。
    解压失败追加到 failures,因密码未提供而跳过的追加到 skip_pws。
    返回 'ok' | 'skip_pw' | 'fail'。"""
    if cancel is not None and cancel.is_set():
        return 'fail'
    if depth > 5:
        log(f'  [提示] 嵌套层数过深,停止: {os.path.basename(archive_path)}')
        return 'fail'
    result = extract_archive(archive_path, dest_dir, log, pm)
    if result == 'skip_pw':
        skip_pws.append(archive_path)
        return 'skip_pw'
    if result != 'ok':
        failures.append(archive_path)
        return 'fail'
    # 先快照收集本层解压出的嵌套压缩包,再逐个递归
    nested = []
    for root, _, files in os.walk(dest_dir):
        for f in files:
            kind = archive_kind(f)
            if kind and kind != 'volume-later':
                nested.append(os.path.join(root, f))
    for n in nested:
        sub = n + '_解压'
        os.makedirs(long_path(sub), exist_ok=True)
        extract_all_recursive(n, sub, log, pm, failures, skip_pws, depth + 1, cancel)
    return 'ok'
