# -*- coding: utf-8 -*-
"""文件类型/来源/垃圾/副本标记识别。"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fac.filetypes import (categorize, detect_source, junk_reason,
                           strip_copy_markers, is_copy_like, OTHER_CATEGORY)


def test_categorize_common():
    assert categorize('报告.docx') == '文档'
    assert categorize('旧报告.doc') == '文档'
    assert categorize('账目.xlsx') == '表格'
    assert categorize('汇报.pptx') == '演示'
    assert categorize('说明.pdf') == 'PDF'
    assert categorize('照片.JPG') == '图片'
    assert categorize('电影.mkv') == '视频'
    assert categorize('歌曲.flac') == '音频'
    assert categorize('备份.zip') == '压缩包'
    assert categorize('系统.iso') == '光盘镜像'
    assert categorize('安装包.exe') == '安装程序'
    assert categorize('小说.epub') == '电子书'
    assert categorize('脚本.py') == '代码脚本'
    assert categorize('设计.psd') == '设计源文件'
    assert categorize('字体.ttf') == '字体'


def test_categorize_unknown():
    assert categorize('神秘文件.xyzzy') == OTHER_CATEGORY
    assert categorize('无扩展名') == OTHER_CATEGORY


def test_detect_source():
    assert detect_source('微信图片_20240115143022.jpg') == '微信文件'
    assert detect_source('mmexport1705300000000.jpg') == '微信文件'
    assert detect_source('QQ图片20240115143022.png') == 'QQ文件'
    assert detect_source('Screenshot_20240115_143022.png') == '截图'
    assert detect_source('屏幕截图 2024-01-15 143022.png') == '截图'
    assert detect_source('IMG_20240115_143022.jpg') == '相机照片'
    assert detect_source('DSC01234.JPG') == '相机照片'
    assert detect_source('大文件.zip.crdownload') == '未完成下载'
    assert detect_source('工作报告.docx') is None


def test_junk_reason():
    assert junk_reason('Thumbs.db') == '系统缓存文件'
    assert junk_reason('.DS_Store') == '系统缓存文件'
    assert junk_reason('desktop.ini') == '系统缓存文件'
    assert junk_reason('~$报告.docx') == 'Office 临时文件'
    assert junk_reason('数据.tmp') == '临时/备份文件'
    assert junk_reason('片子.mp4.crdownload') == '未完成的下载'
    assert junk_reason('正常文件.docx', 1024) is None
    assert junk_reason('空文件.docx', 0) == '空文件(0 字节)'


def test_strip_copy_markers():
    assert strip_copy_markers('报告(1)') == ('报告', 1)
    assert strip_copy_markers('报告（2）') == ('报告', 1)
    assert strip_copy_markers('报告 - 副本') == ('报告', 1)
    assert strip_copy_markers('报告-副本2') == ('报告', 1)
    assert strip_copy_markers('报告的副本') == ('报告', 1)
    assert strip_copy_markers('report - Copy') == ('report', 1)
    assert strip_copy_markers('方案-最终版') == ('方案', 1)
    assert strip_copy_markers('方案_v2') == ('方案', 1)
    assert strip_copy_markers('方案第3版') == ('方案', 1)
    # 多层标记
    base, n = strip_copy_markers('方案-最终版 - 副本(1)')
    assert base == '方案' and n == 3


def test_strip_keeps_plain_names():
    # 裸数字结尾不算副本(会议纪要2 可能是另一次会议)
    assert strip_copy_markers('会议纪要2') == ('会议纪要2', 0)
    assert strip_copy_markers('工作报告') == ('工作报告', 0)
    assert strip_copy_markers('2024年总结') == ('2024年总结', 0)


def test_is_copy_like():
    assert is_copy_like('报告(1).docx')
    assert is_copy_like('报告 - 副本.docx')
    assert not is_copy_like('报告.docx')
