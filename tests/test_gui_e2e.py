# -*- coding: utf-8 -*-
"""端到端:通过真实主窗口把各项功能完整走一遍(对话框自动应答),检查输出结果。

覆盖:拖拽添加、按人归档(多层嵌套 / AES 加密 + 密码本 / 7z / 身份证号 / 曾用名 /
最长匹配 / Word+文本内容匹配 / Excel 按人拆分 / 来源单位 / 核对表 / 日志)、
文件整理(只体检 / 类型+年份 / 文件名日期 / 重复 / 旧版本 / 垃圾 / 项目保护 /
查历史 / 一键清理 / 撤销)。全程在后台线程运行,验证不会闪退。
"""
import os
import sys
import io
import time
import zipfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
pytest.importorskip('PySide6')
pyzipper = pytest.importorskip('pyzipper')
py7zr = pytest.importorskip('py7zr')
openpyxl = pytest.importorskip('openpyxl')
docx = pytest.importorskip('docx')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


def test_all_features_through_main_window(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox, QDialog, QInputDialog
    from PySide6.QtCore import QTimer
    import fac.gui as g
    from fac import config as conf
    mp = monkeypatch
    T = str(tmp_path)
    mp.setattr(conf, 'CONF_FILE', os.path.join(T, 'cfg.json'))
    msgs = []; answers = {}
    mp.setattr(QMessageBox, 'information', lambda *a, **k: msgs.append(('info', a[-1])))
    mp.setattr(QMessageBox, 'warning', lambda *a, **k: msgs.append(('warn', a[-1])))
    mp.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    mp.setattr(QInputDialog, 'getItem', lambda parent, title, label, items, *a, **k: (answers.get('item', lambda it: it[0])(items), True))
    mp.setattr(QInputDialog, 'getText', lambda *a, **k: (answers.get('text', ''), True))
    results = []
    def check(name, ok, detail=''):
        results.append((name, bool(ok), detail)); print(('✅' if ok else '❌'), name, detail, flush=True)

    def accept_dialogs():
        d = app.activeModalWidget()
        if isinstance(d, QDialog) and not isinstance(d, (QMessageBox, QInputDialog)):
            d._ok = True; d.accept()
    tm = QTimer(); tm.timeout.connect(accept_dialogs); tm.start(50)

    def wait_done(n_before, timeout=60):
        t0 = time.time()
        while len(msgs) == n_before and time.time() - t0 < timeout:
            app.processEvents(); time.sleep(0.01)
        return msgs[-1] if len(msgs) > n_before else None

    w = g.MainWindow(); w.show()
    ID_Z = '110101199003078515'
    # ---------- 准备「按人归档」测试数据 ----------
    src = os.path.join(T, 'in'); os.makedirs(src)
    # 单位A: zip 套 zip 套 AES 加密 zip(密码在密码本 txt 里)
    enc = io.BytesIO()
    with pyzipper.AESZipFile(enc, 'w', encryption=pyzipper.WZ_AES) as z:
        z.setpassword(b'Pw2024!'); z.writestr('王五_加密材料.txt', 'secret')
    mid = io.BytesIO()
    with zipfile.ZipFile(mid, 'w') as z:
        z.writestr('机密.zip', enc.getvalue()); z.writestr(f'{ID_Z}_户籍.txt', 'id')
    with zipfile.ZipFile(os.path.join(src, '单位A.zip'), 'w') as z:
        z.writestr('内层.zip', mid.getvalue()); z.writestr('张三_银行流水.txt', 'a')
        z.writestr('小张_曾用名材料.txt', 'b')   # 曾用名
        z.writestr('回执001.txt', '经查,张三丰名下无车辆。')   # 只能靠内容匹配
    open(os.path.join(src, '密码.txt'), 'w', encoding='utf-8').write('机密.zip: Pw2024!\n')
    # 单位B: 7z,内含 Excel(多人表) + Word
    wb = openpyxl.Workbook(); ws = wb.active; ws.append(['姓名', '账号'])
    ws.append(['张三', '6222']); ws.append(['王五', '6333'])
    xl = os.path.join(T, '查询结果.xlsx'); wb.save(xl)
    d = docx.Document(); d.add_paragraph('关于王五的说明'); dx = os.path.join(T, '说明.docx'); d.save(dx)
    with py7zr.SevenZipFile(os.path.join(src, '单位B.7z'), 'w') as z:
        z.write(xl, '查询结果.xlsx'); z.write(dx, '说明.docx')
    out = os.path.join(T, 'out')

    # 拖拽添加
    from PySide6.QtCore import QMimeData, QUrl
    md = QMimeData(); md.setUrls([QUrl.fromLocalFile(src)])
    class Ev:
        def mimeData(self): return md
        def acceptProposedAction(self): pass
        def ignore(self): pass
    w.lst_inputs.dropEvent(Ev())
    check('拖拽添加文件夹', w.inputs == [src])
    w.txt_out.setText(out)
    w.txt_roster.setPlainText(f'张三,,小张\n王五\n张三丰\n李四,{ID_Z}')
    # 本用例的样例文件都只有几个字节,关掉疑似空值以检查常规归档路径
    # (疑似空值另有 tests/test_emptyfile.py 专门覆盖)
    for k, v in dict(empty_detect=False, preview=True, content_match=True, split_excel=True, auto_pw_txt=True,
                     intelligent=False, dedup=False, delete_ok=False, auto_id=True).items():
        w._ck[k].setChecked(v)
    n = len(msgs); w._start(); m = wait_done(n)
    check('按人归档:运行完成不闪退', m and '分类完成' in m[1], (m or ('', ''))[1].split('\n')[0])
    def has(person, pat):
        return any(pat in f for r, _d, fs in os.walk(os.path.join(out, person)) for f in fs)
    check('多层嵌套 + AES 加密(密码本自动解)', has('王五', '加密材料'))
    check('身份证号命中名单 → 归入李四', has('李四_'+ID_Z, ID_Z))
    check('曾用名 小张 → 归入张三', has('张三', '小张_曾用名材料'))
    check('最长匹配:张三丰 不误归张三', not has('张三', '回执001') )
    check('内容匹配:回执001 → 张三丰', has('张三丰', '回执001'))
    check('7z 解压 + Word 内容匹配 → 王五', has('王五', '说明'))
    check('Excel 按人拆分', has('张三', '查询结果') and has('王五', '查询结果'))
    check('按资料类型分 + 【单位】前缀',
              os.path.isfile(os.path.join(out, '张三', '其他数据', '【单位A】张三_银行流水.txt'))
              or any(f.startswith('【单位A】') for f in os.listdir(os.path.join(out, '张三', '其他数据'))))
    check('文件名含流水 → 张三/银行流水 + 精简名「信息_姓名」',
          '【单位A】银行流水_张三.txt' in os.listdir(os.path.join(out, '张三', '银行流水')))
    check('反馈核对表 xlsx', os.path.exists(os.path.join(out, '反馈核对表.xlsx')))
    check('日志文件写入输出目录', any(f.startswith('分类日志_') for f in os.listdir(out)))
    check('界面日志有内容', '分类完成' in w.log.toPlainText())

    # ---------- 文件整理 ----------
    w.cmb_mode.setCurrentIndex(1)
    org_in = os.path.join(T, 'org_in'); os.makedirs(os.path.join(org_in, 'sub'))
    def mk(p, b, mt=None):
        p = os.path.join(org_in, p); os.makedirs(os.path.dirname(p), exist_ok=True)
        open(p, 'wb').write(b)
        if mt: os.utime(p, (mt, mt))
    # 显式给出先后时间:Windows 上连续写入的两个文件修改时间可能完全相同
    now = time.time()
    mk('报告.docx', b'R' * 20000, now - 86400); mk('报告(1).docx', b'R2' * 10000, now)
    mk('照片.jpg', b'J' * 30000); mk('sub/照片副本.jpg', b'J' * 30000)
    mk('Thumbs.db', b'x'); mk('IMG_20180712_153000.jpg', b'P' * 15000)
    mk('proj/package.json', b'{}'); mk('proj/src/a.js', b'1')
    org_out = os.path.join(T, 'org_out')
    w.inputs = []; w.lst_inputs.clear(); w._add_input(org_in); w.txt_out.setText(org_out)
    w._ckg['org_scan_only'].setChecked(True); w._ckg['org_preview'].setChecked(True)
    n = len(msgs); w._start(); m = wait_done(n)
    print('   ', (m or ('',''))[1].split(chr(10))[:2]); check('只体检:完成且不动文件', m and '体检完成' in m[1] and os.path.exists(os.path.join(org_in, 'Thumbs.db')))
    w._ckg['org_scan_only'].setChecked(False)
    n = len(msgs); w._start(); m = wait_done(n)
    check('文件整理:运行完成', m and '整理完成' in m[1], (m or ('', ''))[1].split('\n')[0])
    ex = lambda *p: os.path.exists(os.path.join(org_out, *p))
    check('按类型+年份归类', ex('文档') and ex('图片'))
    check('文件名日期 → 2018', ex('图片', '2018', 'IMG_20180712_153000.jpg'))
    check('重复文件挑出', any('照片' in f for _r, _d, fs in os.walk(os.path.join(org_out, '重复文件')) for f in fs))
    check('旧版本挑出', ex('旧版本'))
    check('垃圾文件挑出', ex('可清理'))
    check('代码项目整体保留', any(os.path.exists(os.path.join(r, 'proj', 'src', 'a.js')) for r, _d, _f in os.walk(org_out)))
    answers['text'] = '照片'
    n = len(msgs)
    # 查整理历史会弹 QDialog(被自动关闭),不产生 information;检查无异常即可
    try:
        w._search_history(); check('查整理历史', True)
    except Exception as e:
        check('查整理历史', False, repr(e))
    answers['item'] = lambda items: items[-1]       # 选「全部」
    n = len(msgs); w._purge_now(); m = wait_done(n)
    check('一键清理到回收站', m and '移入回收站' in m[1] and not ex('可清理'), (m or ('', ''))[1])
    answers['item'] = lambda items: items[0]        # 最新台账
    n = len(msgs); w._undo_last(); m = wait_done(n)
    check('撤销:文件回到原位', m and '已还原' in m[1] and os.path.exists(os.path.join(org_in, '报告(1).docx')) and os.path.exists(os.path.join(org_in, 'sub', '照片副本.jpg')) is False and os.path.exists(os.path.join(org_in, '照片.jpg')), (m or ('', ''))[1].replace('\n', ' '))
    check('撤销:提示已清理文件在回收站', m and '回收站' in m[1])
    check('撤销:不留空分类文件夹', not ex('文档') and not ex('图片'))
    w.close()
    tm.stop()
    bad = [f'{n} {d}' for n, ok, d in results if not ok]
    assert not bad, '未通过: ' + '; '.join(bad)
    assert len(results) == 27
