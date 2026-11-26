# -*- coding: utf-8 -*-
"""图形界面无头冒烟测试:窗口能建起来、两种模式的设置能读出正确的参数对象。

不做像素级验证,只保证界面代码路径可执行、控件与核心逻辑接线正确 ——
这类错误过去只能等到 Windows 上手工点才发现。
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
pytest.importorskip('PySide6')


@pytest.fixture(scope='module')
def app():
    from PySide6.QtWidgets import QApplication
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture
def win(app, tmp_path, monkeypatch):
    # 隔离配置文件,避免读到开发机上的真实配置
    from fac import config as conf
    monkeypatch.setattr(conf, 'CONF_FILE', str(tmp_path / 'cfg.json'))
    from fac.gui import MainWindow
    w = MainWindow()
    yield w
    w.close()


def test_window_builds(win):
    assert win.windowTitle()
    assert win.cmb_mode.count() == 2
    assert win.cmb_mode.currentData() == 'person'      # 默认按人归档
    assert win.btn_run.text().endswith('开始分类')


def test_mode_switch_updates_button(win):
    win.cmb_mode.setCurrentIndex(1)
    assert win._mode() == 'organize'
    assert win.btn_run.text().endswith('开始整理')
    win.cmb_mode.setCurrentIndex(0)
    assert win.btn_run.text().endswith('开始分类')


def test_organize_options_from_ui(win, tmp_path):
    win.cmb_mode.setCurrentIndex(1)
    win._ckg['org_dup'].setChecked(True)
    win._ckg['org_junk'].setChecked(False)
    win._ckg['org_large'].setChecked(True)
    win.spin_large.setValue(250)
    win._rg_op.button(1).setChecked(True)             # 复制
    opts = win._organize_opts(str(tmp_path / 'out'))
    assert opts.op_mode == 'copy'
    assert opts.find_dup and not opts.find_junk
    assert opts.separate_large
    assert opts.large_threshold == 250 * 1024 * 1024
    assert '{类别}' in opts.layout or '{年}' in opts.layout


def test_layout_presets_selectable(win):
    from fac.organize import LAYOUT_PRESETS, render_layout
    win.cmb_mode.setCurrentIndex(1)
    for i in range(win.cmb_layout.count()):
        win.cmb_layout.setCurrentIndex(i)
        tpl = win._organize_opts('/tmp/x').layout
        assert tpl == LAYOUT_PRESETS[i][0]
        assert render_layout(tpl, 'a.docx', 1700000000)   # 模板可渲染


def test_custom_layout_text(win):
    win.cmb_mode.setCurrentIndex(1)
    win.cmb_layout.setEditText('{年}/{来源}')
    assert win._organize_opts('/tmp/x').layout == '{年}/{来源}'


def test_person_mode_still_builds_joboptions(win, tmp_path):
    from fac.roster import Roster
    win.cmb_mode.setCurrentIndex(0)
    win.txt_roster.setPlainText('张三\n')
    r = Roster.from_text(win.txt_roster.toPlainText())
    assert len(r) == 1
    assert win._ck['auto_id'].isChecked() in (True, False)
    assert win._get_rules() == [] or isinstance(win._get_rules(), list)


def test_config_roundtrip_includes_organize(win, tmp_path):
    win.cmb_mode.setCurrentIndex(1)
    win.spin_large.setValue(321)
    win._ckg['org_versions'].setChecked(False)
    cfg = win._gather_cfg()
    assert cfg['work_mode'] == 'organize'
    assert cfg['org_large_mb'] == 321
    assert cfg['org_versions'] is False
    # 回填后应保持一致
    win.spin_large.setValue(100)
    win._apply_cfg(cfg)
    assert win.spin_large.value() == 321
    assert win._ckg['org_versions'].isChecked() is False
    assert win._mode() == 'organize'


def test_undo_without_journal_warns(win, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: shown.append(a[-1]))
    monkeypatch.setattr(QMessageBox, 'warning',
                        lambda *a, **k: shown.append(a[-1]))
    out = tmp_path / 'empty_out'
    out.mkdir()
    win.txt_out.setText(str(out))
    win._undo_last()
    assert shown and '台账' in shown[-1]


def test_organize_new_options_from_ui(win, tmp_path):
    """V4.2 新增选项能正确读进 OrganizeOptions。"""
    win.cmb_mode.setCurrentIndex(1)
    win._ckg['org_keep_proj'].setChecked(True)
    win._ckg['org_hidden'].setChecked(True)
    win.spin_mindup.setValue(256)
    opts = win._organize_opts(str(tmp_path / 'out'))
    assert opts.keep_projects is True
    assert opts.skip_hidden is False          # 勾了"包含隐藏文件"
    assert opts.min_dup_size == 256 * 1024

    win._ckg['org_keep_proj'].setChecked(False)
    win._ckg['org_hidden'].setChecked(False)
    win.spin_mindup.setValue(0)
    opts = win._organize_opts(str(tmp_path / 'out'))
    assert opts.keep_projects is False
    assert opts.skip_hidden is True
    assert opts.min_dup_size == 0             # 0 = 不限


def test_min_dup_config_roundtrip(win):
    win.cmb_mode.setCurrentIndex(1)
    win.spin_mindup.setValue(64)
    win._ckg['org_keep_proj'].setChecked(False)
    cfg = win._gather_cfg()
    assert cfg['org_min_dup_kb'] == 64
    assert cfg['org_keep_proj'] is False
    win.spin_mindup.setValue(10)
    win._apply_cfg(cfg)
    assert win.spin_mindup.value() == 64
    assert win._ckg['org_keep_proj'].isChecked() is False


def test_purge_ignores_user_files_in_bucket(win, tmp_path, monkeypatch):
    """一键清理只看台账:输出目录里只有用户自己放的「重复文件」时,提示无可删。"""
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: shown.append(a[-1]))
    out = tmp_path / 'out'
    (out / '重复文件').mkdir(parents=True)
    (out / '重复文件' / '我的.txt').write_text('mine')
    win.txt_out.setText(str(out))
    win._purge_now()
    assert shown and '没有' in shown[-1]
    assert (out / '重复文件' / '我的.txt').exists()


# ---------- V4.3.1:后台线程不得直接碰界面(Windows 上会闪退) ----------

def _pump(app, cond, timeout=20):
    import time
    t0 = time.time()
    while not cond() and time.time() - t0 < timeout:
        app.processEvents()
        time.sleep(0.01)
    return cond()


def test_log_and_progress_from_worker_thread(win, app):
    import threading
    def work():
        for i in range(500):
            win._log(f'第{i}行')
            win._on_progress('place', i, 500)
    t = threading.Thread(target=work)
    t.start(); t.join()
    assert win.log.toPlainText() == ''            # 后台线程没有直接改控件
    assert _pump(app, lambda: '第499行' in win.log.toPlainText())


def test_call_sync_runs_on_main_thread(win, app):
    import threading
    seen = []

    def job():
        seen.append(threading.current_thread() is threading.main_thread())
        return 42

    box = []
    t = threading.Thread(target=lambda: box.append(win._bridge.call_sync(job)))
    t.start()
    assert _pump(app, lambda: box)
    t.join()
    assert box == [42] and seen == [True]


def test_drop_files_adds_inputs(win, tmp_path):
    from PySide6.QtCore import QMimeData, QUrl
    f = tmp_path / '单位A.zip'
    f.write_bytes(b'PK')
    md = QMimeData()
    md.setUrls([QUrl.fromLocalFile(str(f)), QUrl.fromLocalFile(str(tmp_path))])

    class Ev:
        accepted = False
        def mimeData(self): return md
        def acceptProposedAction(self): self.accepted = True
        def ignore(self): pass

    for handler in (win.dragEnterEvent, win.dragMoveEvent):
        e = Ev(); handler(e); assert e.accepted
    e = Ev(); win.lst_inputs.dropEvent(e)      # 拖到列表上
    assert e.accepted
    assert os.path.normpath(str(f)) in win.inputs
    assert os.path.normpath(str(tmp_path)) in win.inputs
    assert win.lst_inputs.count() == 2


def test_classify_nested_archive_end_to_end(win, app, tmp_path, monkeypatch):
    """压缩包套压缩包 + 预览确认:整个流程在后台线程跑完且不闪退。"""
    import io
    import zipfile
    from PySide6.QtWidgets import QMessageBox, QDialog
    done = []
    monkeypatch.setattr(QMessageBox, 'information',
                        lambda *a, **k: done.append(a[-1]))
    monkeypatch.setattr(QMessageBox, 'question',
                        lambda *a, **k: QMessageBox.Yes)
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, 'w') as z:
        z.writestr('李四_材料.pdf', 'y')
    mid = io.BytesIO()
    with zipfile.ZipFile(mid, 'w') as z:
        z.writestr('第三层.zip', inner.getvalue())
        z.writestr('张三_身份证.txt', 'x')
    outer = tmp_path / '单位A.zip'
    with zipfile.ZipFile(outer, 'w') as z:
        z.writestr('第二层.zip', mid.getvalue())
    out = tmp_path / 'out'
    win.inputs = [str(outer)]
    win.txt_out.setText(str(out))
    win.txt_roster.setPlainText('张三\n李四')
    win._ck['preview'].setChecked(True)

    def accept_preview():
        d = app.activeModalWidget()
        if isinstance(d, QDialog):
            d._ok = True
            d.accept()

    from PySide6.QtCore import QTimer
    tm = QTimer()                 # 预览框自带事件循环,用定时器去点「确认」
    tm.timeout.connect(accept_preview)
    tm.start(50)
    win._start()
    assert _pump(app, lambda: bool(done), timeout=30)
    tm.stop()
    assert list((out / '张三').rglob('张三_身份证.txt'))
    assert list((out / '李四').rglob('李四_材料.pdf'))
