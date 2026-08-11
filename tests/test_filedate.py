# -*- coding: utf-8 -*-
"""文件真实日期判定:EXIF 拍摄时间 / 文件名日期 / 修改时间。"""
import os
import sys
import datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from fac.filedate import parse_date_from_name, best_date, exif_date


def d(ts):
    return datetime.date.fromtimestamp(ts).isoformat() if ts else None


def test_parse_common_camera_names():
    assert d(parse_date_from_name('IMG_20180712_153000.jpg')) == '2018-07-12'
    assert d(parse_date_from_name('DSC_20200101.JPG')) == '2020-01-01'
    assert d(parse_date_from_name('PXL_20211130_083000123.jpg')) == '2021-11-30'


def test_parse_im_timestamps():
    # 微信/QQ 的 14 位时间戳
    assert d(parse_date_from_name('微信图片_20230815120000.jpg')) == '2023-08-15'
    assert d(parse_date_from_name('QQ图片20240115143022.png')) == '2024-01-15'


def test_parse_separated_dates():
    assert d(parse_date_from_name('2024-01-15会议纪要.docx')) == '2024-01-15'
    assert d(parse_date_from_name('2024_03_02汇报.pptx')) == '2024-03-02'
    assert d(parse_date_from_name('2024年1月15日纪要.docx')) == '2024-01-15'
    assert d(parse_date_from_name('Screenshot_2024-03-02.png')) == '2024-03-02'


def test_reject_non_dates():
    # 身份证号里的出生日期不能被当成文件日期
    assert parse_date_from_name('110101199003078515_流水.xlsx') is None
    assert parse_date_from_name('订单1234567890123.pdf') is None
    assert parse_date_from_name('13812345678.txt') is None
    assert parse_date_from_name('报告2023.docx') is None       # 只有年份不算
    assert parse_date_from_name('普通文件.txt') is None
    assert parse_date_from_name('20241332.pdf') is None        # 13月32日,非法


def test_reject_out_of_range_year():
    assert parse_date_from_name('18500101.txt') is None        # 太早
    assert parse_date_from_name('29990101.txt') is None        # 太晚


def test_best_date_prefers_name_over_mtime():
    mtime = datetime.datetime(2026, 5, 1).timestamp()
    ts, src = best_date('/nonexistent/IMG_20180712_153000.jpg',
                        'IMG_20180712_153000.jpg', mtime)
    assert d(ts) == '2018-07-12' and src == '文件名日期'


def test_best_date_mtime_mode():
    mtime = datetime.datetime(2026, 5, 1).timestamp()
    ts, src = best_date('/x/IMG_20180712_153000.jpg',
                        'IMG_20180712_153000.jpg', mtime, mode='mtime')
    assert ts == mtime and src == '修改时间'


def test_best_date_falls_back_to_mtime():
    mtime = datetime.datetime(2022, 9, 9).timestamp()
    ts, src = best_date('/x/随手记.txt', '随手记.txt', mtime)
    assert ts == mtime and src == '修改时间'


def test_exif_date_real_image(tmp_path):
    PIL = pytest.importorskip('PIL')
    from PIL import Image
    img = tmp_path / 'photo.jpg'
    im = Image.new('RGB', (8, 8), 'red')
    exif = im.getexif()
    exif[36867] = '2015:06:20 11:22:33'      # DateTimeOriginal
    im.save(img, exif=exif)
    assert d(exif_date(str(img))) == '2015-06-20'
    # EXIF 优先于文件名和修改时间
    mtime = datetime.datetime(2026, 1, 1).timestamp()
    ts, src = best_date(str(img), 'photo.jpg', mtime)
    assert d(ts) == '2015-06-20' and src == '拍摄时间'


def test_exif_missing_returns_none(tmp_path):
    pytest.importorskip('PIL')
    from PIL import Image
    img = tmp_path / 'plain.jpg'
    Image.new('RGB', (8, 8), 'blue').save(img)
    assert exif_date(str(img)) is None


def test_exif_ignored_for_non_images():
    assert exif_date('/x/report.docx') is None
