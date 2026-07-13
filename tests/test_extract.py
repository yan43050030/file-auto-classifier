# -*- coding: utf-8 -*-
import os
import sys
import zipfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac import extract as ex
from fac.password import PasswordManager


def log(msg):
    pass


def pm(seeds=None, ask=None):
    return PasswordManager(ask or (lambda n, a: None), seeds=seeds)


# ---------- 格式与分卷识别 ----------

def test_archive_kind():
    assert ex.archive_kind('a.zip') == 'zip'
    assert ex.archive_kind('a.7z') == '7z'
    assert ex.archive_kind('a.rar') == 'rar'
    assert ex.archive_kind('a.tar.gz') == 'tar'
    assert ex.archive_kind('a.gz') == 'gz'
    assert ex.archive_kind('a.txt') is None


def test_volume_detection():
    assert ex.archive_kind('a.part1.rar') == 'rar'
    assert ex.archive_kind('a.part2.rar') == 'volume-later'
    assert ex.archive_kind('a.7z.001') == '7z-vol'
    assert ex.archive_kind('a.7z.002') == 'volume-later'
    assert ex.archive_kind('a.z01') == 'volume-later'
    assert ex.archive_kind('a.r00') == 'volume-later'
    assert ex.archive_kind('a.zip.001') == 'volume-unsupported'


def test_unit_name():
    assert ex.unit_name('/x/公安局反馈.zip') == '公安局反馈'
    assert ex.unit_name('税务局.part1.rar') == '税务局'
    assert ex.unit_name('银行.7z.001') == '银行'
    assert ex.unit_name('档案.tar.gz') == '档案'


# ---------- 路径穿越防护 ----------

def test_safe_target_blocks_escape(tmp_path):
    d = str(tmp_path)
    assert ex.safe_target(d, '../../evil.txt') is None
    assert ex.safe_target(d, 'a/../../evil.txt') is None
    # 绝对路径剥掉根/盘符后落回目录内(与 tar 的安全处理一致)
    assert ex.safe_target(d, '/etc/passwd') == os.path.join(d, 'etc', 'passwd')
    assert ex.safe_target(d, 'C:\\Windows\\evil.txt') == os.path.join(d, 'Windows', 'evil.txt')
    assert ex.safe_target(d, 'a/b.txt') == os.path.join(d, 'a', 'b.txt')


def test_zip_slip_blocked(tmp_path):
    evil = tmp_path / 'evil.zip'
    with zipfile.ZipFile(evil, 'w') as z:
        z.writestr('../../escaped.txt', 'pwned')
        z.writestr('ok.txt', 'fine')
    dest = tmp_path / 'deep' / 'out'
    dest.mkdir(parents=True)
    assert ex.extract_archive(str(evil), str(dest), log, pm())
    assert (dest / 'ok.txt').exists()
    assert not (tmp_path / 'escaped.txt').exists()


# ---------- zip:普通 / 中文 / AES 加密 ----------

def test_plain_zip(tmp_path):
    a = tmp_path / 'a.zip'
    with zipfile.ZipFile(a, 'w') as z:
        z.writestr('张三_报告.txt', 'data')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm())
    assert (dest / '张三_报告.txt').read_text() == 'data'


def test_aes_zip_with_seed_password(tmp_path):
    pyzipper = pytest.importorskip('pyzipper')
    a = tmp_path / 'aes.zip'
    with pyzipper.AESZipFile(str(a), 'w', encryption=pyzipper.WZ_AES) as z:
        z.setpassword(b'sec123')
        z.writestr('李四_身份.txt', 'secret')
    dest = tmp_path / 'out'
    dest.mkdir()
    # 密码在密码本候选中,应自动成功 —— 旧版此场景 100% 失败
    assert ex.extract_archive(str(a), str(dest), log,
                              pm(seeds=['错的', 'sec123']))
    assert (dest / '李四_身份.txt').read_text() == 'secret'


def test_aes_zip_ask_user(tmp_path):
    pyzipper = pytest.importorskip('pyzipper')
    a = tmp_path / 'aes2.zip'
    with pyzipper.AESZipFile(str(a), 'w', encryption=pyzipper.WZ_AES) as z:
        z.setpassword(b'pw9')
        z.writestr('f.txt', 'x')
    dest = tmp_path / 'out'
    dest.mkdir()
    asked = []

    def ask(name, attempt):
        asked.append(attempt)
        return 'pw9' if attempt == 2 else 'wrong'

    assert ex.extract_archive(str(a), str(dest), log, pm(ask=ask))
    assert asked == [1, 2]


def test_encrypted_zip_cancel(tmp_path):
    pyzipper = pytest.importorskip('pyzipper')
    a = tmp_path / 'aes3.zip'
    with pyzipper.AESZipFile(str(a), 'w', encryption=pyzipper.WZ_AES) as z:
        z.setpassword(b'pw')
        z.writestr('f.txt', 'x')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm()) == 'skip_pw'  # ask 返回 None


# ---------- 7z ----------

def test_7z_roundtrip(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    a = tmp_path / 'a.7z'
    src = tmp_path / 'src'
    src.mkdir()
    (src / '王五_流水.txt').write_text('x')
    with py7zr.SevenZipFile(str(a), 'w') as z:
        z.writeall(str(src), arcname='.')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm())
    assert (dest / '王五_流水.txt').exists()


def test_7z_password(tmp_path):
    py7zr = pytest.importorskip('py7zr')
    a = tmp_path / 'p.7z'
    src = tmp_path / 'src2'
    src.mkdir()
    (src / 'f.txt').write_text('x')
    with py7zr.SevenZipFile(str(a), 'w', password='abc') as z:
        z.writeall(str(src), arcname='.')
    dest = tmp_path / 'out2'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm(seeds=['abc']))
    assert (dest / 'f.txt').exists()


# ---------- tar / gz ----------

def test_tar_gz(tmp_path):
    import tarfile
    a = tmp_path / 'a.tar.gz'
    src = tmp_path / 'f.txt'
    src.write_text('hello')
    with tarfile.open(a, 'w:gz') as t:
        t.add(str(src), arcname='sub/f.txt')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm())
    assert (dest / 'sub' / 'f.txt').read_text() == 'hello'


def test_bare_gz(tmp_path):
    import gzip
    a = tmp_path / '数据.txt.gz'
    with gzip.open(a, 'wt') as f:
        f.write('gz-data')
    dest = tmp_path / 'out'
    dest.mkdir()
    assert ex.extract_archive(str(a), str(dest), log, pm())
    assert (dest / '数据.txt').read_text() == 'gz-data'


# ---------- 嵌套递归 ----------

def test_nested_extraction(tmp_path):
    lvl3 = tmp_path / 'l3.zip'
    with zipfile.ZipFile(lvl3, 'w') as z:
        z.writestr('最里层.txt', 'deep')
    lvl2 = tmp_path / 'l2.zip'
    with zipfile.ZipFile(lvl2, 'w') as z:
        z.write(lvl3, 'l3.zip')
    lvl1 = tmp_path / 'l1.zip'
    with zipfile.ZipFile(lvl1, 'w') as z:
        z.write(lvl2, 'l2.zip')
    dest = tmp_path / 'out'
    dest.mkdir()
    failures = []
    assert ex.extract_all_recursive(str(lvl1), str(dest), log, pm(), failures, [])
    assert not failures
    found = [f for _r, _d, fs in os.walk(dest) for f in fs if f == '最里层.txt']
    assert len(found) == 1


def test_nested_failure_collected(tmp_path):
    bad = tmp_path / 'bad.zip'
    bad.write_bytes(b'not a zip at all')
    outer = tmp_path / 'outer.zip'
    with zipfile.ZipFile(outer, 'w') as z:
        z.write(bad, 'bad.zip')
        z.writestr('good.txt', 'ok')
    dest = tmp_path / 'out'
    dest.mkdir()
    failures = []
    assert ex.extract_all_recursive(str(outer), str(dest), log, pm(), failures, [])
    assert len(failures) == 1 and failures[0].endswith('bad.zip')
