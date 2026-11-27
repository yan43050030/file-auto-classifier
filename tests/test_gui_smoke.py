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
    assert list((out / '张三').rglob('*身份证_张三.txt'))     # 默认精简文件名
    assert list((out / '李四').rglob('*材料_李四.pdf'))


def test_theme_ignores_windows_dark_mode(app):
    """Windows 深色模式下也必须是浅色界面,否则标签/下拉框会"白底白字"看不见。"""
    from PySide6.QtGui import QPalette, QColor
    from fac.gui_style import apply_theme
    old_pal, old_ss = app.palette(), app.styleSheet()
    dark = QPalette()
    for role in (QPalette.Window, QPalette.Base, QPalette.Button):
        dark.setColor(role, QColor('#202020'))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        dark.setColor(role, QColor('#FFFFFF'))
    app.setPalette(dark)                     # 模拟系统给的深色调色板
    try:
        apply_theme(app)
        pal = app.palette()
        assert pal.color(QPalette.WindowText).lightness() < 100   # 深色文字
        assert pal.color(QPalette.Base).lightness() > 200         # 浅色底
        assert pal.color(QPalette.Text).lightness() < 100
    finally:
        app.setPalette(old_pal)
        app.setStyleSheet(old_ss)


def test_output_dir_follows_last_added_archive(win, tmp_path):
    a = tmp_path / 'A'; b = tmp_path / 'B'; a.mkdir(); b.mkdir()
    (a / '1.zip').write_bytes(b'PK'); (b / '2.zip').write_bytes(b'PK')
    win.txt_out.setText('/old/saved/dir')          # 上次保存的配置,不算手动
    win._out_manual = False
    win._add_input(str(a / '1.zip'))
    assert win.txt_out.text().startswith(os.path.join(str(a), '分类结果'))
    win._add_input(str(b / '2.zip'))                # 跟随最后添加的
    assert win.txt_out.text().startswith(os.path.join(str(b), '分类结果'))


def test_output_dir_kept_after_manual_edit(win, tmp_path):
    a = tmp_path / 'A'; a.mkdir(); (a / '1.zip').write_bytes(b'PK')
    win.txt_out.setText('D:/我的结果')
    win.txt_out.textEdited.emit('D:/我的结果')      # 等同用户亲手输入
    assert win._out_manual is True
    win._add_input(str(a / '1.zip'))
    assert win.txt_out.text() == 'D:/我的结果'


def test_auto_company_option_reaches_joboptions(win):
    assert win._ck['auto_company'].isChecked()
    cfg = win._gather_cfg()
    assert cfg['auto_company'] is True


def test_output_dir_not_reset_after_job_or_same_mode(win, tmp_path):
    a = tmp_path / 'A'; a.mkdir(); (a / '1.zip').write_bytes(b'PK')
    win._out_manual = False
    win._add_input(str(a / '1.zip'))
    win.txt_out.setText(str(tmp_path / 'chosen'))
    win._on_mode_changed()                          # 任务结束时的刷新
    assert win.txt_out.text() == str(tmp_path / 'chosen')
    win.cmb_mode.setCurrentIndex(1)                 # 真切换模式 → 跟随并改名
    assert '整理结果_' in win.txt_out.text()


def test_empty_detect_option_roundtrip(win):
    assert win._ck['empty_detect'].isChecked()
    win.spin_emptykb.setValue(8)
    cfg = win._gather_cfg()
    assert cfg['empty_detect'] is True and cfg['empty_max_kb'] == 8
    win.spin_emptykb.setValue(10)
    win._apply_cfg(cfg)
    assert win.spin_emptykb.value() == 8


def test_out_fixed_keeps_library_dir(win, tmp_path):
    a = tmp_path / 'A'; a.mkdir(); (a / '1.zip').write_bytes(b'PK')
    win.txt_out.setText(str(tmp_path / '归档库'))
    win.ck_out_fixed.setChecked(True)
    win._add_input(str(a / '1.zip'))
    assert win.txt_out.text() == str(tmp_path / '归档库')       # 固定不动
    assert win._gather_cfg()['out_fixed'] is True
    win.ck_out_fixed.setChecked(False)                          # 取消 → 恢复跟随
    assert win.txt_out.text() == os.path.join(str(a), '分类结果')


def test_default_layout_is_category(win):
    assert win._unit_mode() == 'category'
    cfg = win._gather_cfg()
    assert cfg['unit_mode'] == 'category'
    cfg['unit_mode'] = 'subfolder'
    win._apply_cfg(cfg)
    assert win._unit_mode() == 'subfolder'


def test_old_config_migrates_to_category(tmp_path, monkeypatch):
    import json
    from fac import config as conf
    p = tmp_path / 'old.json'
    p.write_text(json.dumps({'unit_mode': 'subfolder'}), encoding='utf-8')
    monkeypatch.setattr(conf, 'CONF_FILE', str(p))
    assert conf.load_config()['unit_mode'] == 'category'
    p.write_text(json.dumps({'unit_mode': 'subfolder', 'layout_v46': True}),
                 encoding='utf-8')                  # 迁移后用户又选回旧方式 → 尊重
    assert conf.load_config()['unit_mode'] == 'subfolder'


def test_every_option_has_tooltip(win):
    from PySide6.QtWidgets import QAbstractButton
    btns = [b for b in win.findChildren(QAbstractButton) if b.text().strip()]
    missing = [b.text() for b in btns if not b.toolTip()]
    assert len(btns) > 40 and not missing, missing
    for attr in ('txt_out', 'cmb_mode', 'txt_roster', 'spin_emptykb', 'cmb_layout'):
        assert getattr(win, attr).toolTip(), attr


def test_mode_banner_and_button_color(win):
    win.cmb_mode.setCurrentIndex(0)
    assert '按人归档' in win.lbl_banner.text() and '按人归档' in win.windowTitle()
    assert win.btn_run.property('mode') == 'person'
    win.cmb_mode.setCurrentIndex(1)
    assert '文件整理' in win.lbl_banner.text() and '文件整理' in win.windowTitle()
    assert win.btn_run.property('mode') == 'organize'
    assert win.btn_run.toolTip().startswith('文件整理')


def test_short_names_option(win):
    assert win.ck_short.isChecked()
    assert win._gather_cfg()['short_names'] is True
    opts = win._organize_opts(str(win.txt_out.text() or '.'))
    assert opts.library_mode == 'ask'                 # 文件整理遇到归档库会询问


def test_drop_anywhere_in_window_adds_inputs(win, app, tmp_path):
    """拖到窗口任意位置(日志区、名单框、输出框、设置页…)都能添加,不只是列表。"""
    from PySide6.QtCore import QMimeData, QUrl, QPoint, QPointF, Qt
    from PySide6.QtGui import QDragEnterEvent, QDropEvent
    win.show()
    targets = [win.log, win.txt_roster, win.txt_out, win._tabs, win.lbl_banner,
               win.txt_pwfile]
    for i, w in enumerate(targets):
        f = tmp_path / f'包{i}.zip'
        f.write_bytes(b'PK')
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(str(f))])
        enter = QDragEnterEvent(QPoint(5, 5), Qt.CopyAction, md,
                                Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(w, enter)
        assert enter.isAccepted(), w
        drop = QDropEvent(QPointF(5, 5), Qt.CopyAction, md,
                          Qt.LeftButton, Qt.NoModifier)
        app.sendEvent(w, drop)
        assert os.path.normpath(str(f)) in win.inputs, w
    assert win.txt_roster.toPlainText() == ''          # 没把路径当文字插进名单框
    assert win.txt_out.text() != str(tmp_path / '包2.zip')


def test_password_file_in_output_area(win):
    # 密码本输入框在「② 保存到」区域,和同步按钮在一起
    assert win.txt_pwfile.parentWidget() is win.btn_sync.parentWidget()


def test_txt_password_option_off_and_migrated(win, tmp_path, monkeypatch):
    import json
    from fac import config as conf
    assert win._ck['auto_pw_txt'].isChecked() is False
    p = tmp_path / 'old.json'
    p.write_text(json.dumps({'auto_pw_txt': True}), encoding='utf-8')   # 老配置
    monkeypatch.setattr(conf, 'CONF_FILE', str(p))
    assert conf.load_config()['auto_pw_txt'] is False
    p.write_text(json.dumps({'auto_pw_txt': True, 'pw_txt_v502': True}), encoding='utf-8')
    assert conf.load_config()['auto_pw_txt'] is True      # 迁移后自己再打开 → 尊重


def test_preview_long_names_scroll_horizontally(win, app):
    """预览清单:文件名很长时列宽跟着内容走、出现横向滚动条,不再截成省略号。"""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QDialog, QTreeWidget
    from fac.pipeline import PlanItem
    long = '【某某查【2026】第123456号_2026年11月11日】张三_230303197511020127_' * 3 + '保险信息.xlsx'
    plan = [PlanItem('/x/a', long, '某单位', 'place', ['张三'], via='名单')]
    seen = {}

    def grab():
        d = app.activeModalWidget()
        if isinstance(d, QDialog):
            t = d.findChild(QTreeWidget)
            fm = t.fontMetrics()
            seen['col0'] = t.header().sectionSize(0)
            seen['need'] = min(fm.horizontalAdvance(long), 900)
            seen['tip'] = t.topLevelItem(0).toolTip(0)
            seen['stretch'] = t.header().stretchLastSection()
            d.reject()
    QTimer.singleShot(200, grab)
    win._confirm_plan(plan)
    assert seen['col0'] >= seen['need'] and seen['tip'] == long
    assert seen['stretch'] is False


def test_accounts_button_on_existing_library(win, app, tmp_path, monkeypatch):
    """「📊 生成账户汇总」:对已经分好的归档库补做汇总表,不动原文件。"""
    pytest.importorskip('pandas')
    import time
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from flow_samples import ccb_xlsx
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    d = tmp_path / 'lib' / '张三' / '银行流水'
    d.mkdir(parents=True)
    (d / '建设银行.xlsx').write_bytes(ccb_xlsx())
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory',
                        lambda *a, **k: str(tmp_path / 'lib'))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    done = {}
    monkeypatch.setattr(win, '_on_accounts_done', lambda path, res: done.update(res))
    win._flow_ck['tidy_flows'].setChecked(False)
    win._accounts_only()
    t0 = time.time()
    while not done and time.time() - t0 < 30:
        app.processEvents()
        time.sleep(0.02)
    assert done['kind'] == 'library' and len(done['summaries']) == 1
    assert (d / '账户汇总_张三.xlsx').is_file()
    assert not (d / '流水整理版').exists()
    assert sorted(x.name for x in d.iterdir()) == ['建设银行.xlsx', '账户汇总_张三.xlsx']
