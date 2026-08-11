# -*- coding: utf-8 -*-
"""文件日期判定 —— 决定「按年/年月整理」时该用哪个日期。

修改时间(mtime)常常不是文件的"真实日期":照片从手机/相机拷到硬盘后,
mtime 往往变成拷贝当天;下载的文件 mtime 是下载时间。
优先级:EXIF 拍摄时间 → 文件名里的日期 → 修改时间。
"""

import os
import re
import datetime

try:
    from PIL import Image                 # 读 EXIF(可选依赖)
    HAS_PIL = True
except Exception:
    HAS_PIL = False

# EXIF 标签号
_EXIF_ORIGINAL = 36867      # DateTimeOriginal(拍摄时间,最准)
_EXIF_DIGITIZED = 36868     # DateTimeDigitized
_EXIF_DATETIME = 306        # DateTime(可能是修改时间)

_EXIF_EXTS = ('.jpg', '.jpeg', '.tif', '.tiff', '.heic', '.heif', '.png', '.webp')

_MIN_YEAR, _MAX_YEAR = 1990, datetime.date.today().year + 1

# 文件名中的日期:要求两侧不是数字,避免从身份证号/流水号里截出假日期
_NAME_DATE_PATTERNS = [
    # 2018-07-12 / 2018_07_12 / 2018.07.12 / 2018年7月12日
    re.compile(r'(?<!\d)(\d{4})[-_./年](\d{1,2})[-_./月](\d{1,2})(?!\d)'),
    # 20230815120000(微信/QQ 的 14 位时间戳)、202308151200(12 位)
    re.compile(r'(?<!\d)(\d{4})(\d{2})(\d{2})\d{6}(?!\d)'),
    re.compile(r'(?<!\d)(\d{4})(\d{2})(\d{2})\d{4}(?!\d)'),
    # 20180712_153000 / 20180712
    re.compile(r'(?<!\d)(\d{4})(\d{2})(\d{2})(?!\d)'),
]


def _plausible(y, m, d):
    if not (_MIN_YEAR <= y <= _MAX_YEAR and 1 <= m <= 12 and 1 <= d <= 31):
        return False
    try:
        datetime.date(y, m, d)
        return True
    except ValueError:
        return False


def parse_date_from_name(fname: str):
    """从文件名里解析日期,返回时间戳;解析不出返回 None。

    支持 IMG_20180712_153000、微信图片_20230815120000、2024-01-15、
    20240115、2024年1月15日 等常见命名。"""
    stem = os.path.splitext(str(fname))[0]
    for pat in _NAME_DATE_PATTERNS:
        for m in pat.finditer(stem):
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if _plausible(y, mo, d):
                try:
                    return datetime.datetime(y, mo, d).timestamp()
                except (ValueError, OverflowError, OSError):
                    continue
    return None


def exif_date(path: str):
    """读图片 EXIF 的拍摄时间,返回时间戳;读不到返回 None。"""
    if not HAS_PIL or not str(path).lower().endswith(_EXIF_EXTS):
        return None
    try:
        with Image.open(path) as im:
            exif = im.getexif()
            if not exif:
                return None
            for tag in (_EXIF_ORIGINAL, _EXIF_DIGITIZED, _EXIF_DATETIME):
                raw = exif.get(tag)
                if not raw:
                    continue
                txt = str(raw).strip().strip('\x00')
                # 标准格式 "2018:07:12 15:30:00",也兼容用 - / 分隔
                m = re.match(r'^(\d{4})[:\-/](\d{1,2})[:\-/](\d{1,2})', txt)
                if not m:
                    continue
                y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if _plausible(y, mo, d):
                    return datetime.datetime(y, mo, d).timestamp()
    except Exception:
        return None
    return None


def best_date(path: str, fname: str, mtime: float, mode: str = 'auto'):
    """判定文件的"真实日期"。返回 (时间戳, 依据说明)。

    mode='auto' : EXIF → 文件名日期 → 修改时间
    mode='mtime': 只用修改时间
    """
    if mode != 'auto':
        return mtime, '修改时间'
    ts = exif_date(path)
    if ts:
        return ts, '拍摄时间'
    ts = parse_date_from_name(fname)
    if ts:
        return ts, '文件名日期'
    return mtime, '修改时间'
