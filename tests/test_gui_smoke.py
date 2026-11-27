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
    assert win.btn_run.text().endswith('开始归档')


def test_mode_switch_updates_button(win):
    win.cmb_mode.setCurrentIndex(1)
    assert win._mode() == 'organize'
    assert win.btn_run.text().endswith('开始整理')
    win.cmb_mode.setCurrentIndex(0)
    assert win.btn_run.text().endswith('开始归档')
    win.btn_mode_org.click()                         # 顶部大按钮切换
    assert win._mode() == 'organize' and win.btn_mode_org.isChecked()
    win.btn_mode_person.click()
    assert win._mode() == 'person' and not win.btn_mode_org.isChecked()


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


def test_library_dir_chosen_is_remembered(win, tmp_path, monkeypatch):
    """归档库「更换…」选过之后一直记住;清空路径 = 恢复跟随最后添加的材料。"""
    from PySide6.QtWidgets import QFileDialog
    a = tmp_path / 'A'; a.mkdir(); (a / '1.zip').write_bytes(b'PK')
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory',
                        lambda *x, **k: str(tmp_path / '归档库'))
    win._choose_out('person')
    win._add_input(str(a / '1.zip'))
    assert win.txt_lib.text() == str(tmp_path / '归档库')        # 固定不动
    cfg = win._gather_cfg()
    assert cfg['out_fixed'] is True and cfg['out_dir'] == str(tmp_path / '归档库')
    win.txt_lib.setText('')
    win.txt_lib.textEdited.emit('')                               # 用户清空
    assert win.txt_lib.text() == os.path.join(str(a), '分类结果')


def test_paths_are_separate_per_mode(win, tmp_path):
    """归档库和整理结果分开记,切换模式不会互相覆盖。"""
    a = tmp_path / 'A'; a.mkdir()
    win.txt_lib.setText(str(tmp_path / '归档库')); win._manual['person'] = True
    win._add_input(str(a))
    assert win.txt_out is win.txt_lib
    win.cmb_mode.setCurrentIndex(1)
    assert win.txt_out is win.txt_org and '整理结果_' in win.txt_org.text()
    win.txt_org.setText(str(tmp_path / '整理到这'))
    win.txt_org.textEdited.emit(str(tmp_path / '整理到这'))
    win.cmb_mode.setCurrentIndex(0)
    assert win.txt_out.text() == str(tmp_path / '归档库')
    cfg = win._gather_cfg()
    assert cfg['org_out_dir'] == str(tmp_path / '整理到这') and cfg['org_out_fixed'] is True
    win.txt_lib.setText(''); win.txt_org.setText('')
    win._apply_cfg(cfg)
    assert win.txt_lib.text() == str(tmp_path / '归档库')
    assert win.txt_org.text() == str(tmp_path / '整理到这')


def test_old_config_out_dir_goes_to_matching_mode(win, tmp_path):
    """旧配置只有一个 out_dir:按人归档时就是归档库;上次在文件整理模式则给整理结果。"""
    win._apply_cfg({'out_dir': 'D:/lib', 'work_mode': 'person'})
    assert win.txt_lib.text() == 'D:/lib' and win.txt_org.text() == ''
    win.txt_lib.setText('')
    win._apply_cfg({'out_dir': 'E:/org', 'work_mode': 'organize'})
    assert win.txt_org.text() == 'E:/org'


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


def test_mode_cards_and_button_color(win):
    win.cmb_mode.setCurrentIndex(0)
    assert win.btn_mode_person.isChecked() and '按人归档' in win.windowTitle()
    assert win.btn_run.property('mode') == 'person'
    assert win._stack_out.currentIndex() == 0 and win._stack_settings.currentIndex() == 0
    assert win.btn_sync.isVisibleTo(win) and win.btn_add_archives.isVisibleTo(win)
    win.cmb_mode.setCurrentIndex(1)
    assert win.btn_mode_org.isChecked() and '文件整理' in win.windowTitle()
    assert win.btn_run.property('mode') == 'organize'
    assert win.btn_run.toolTip().startswith('文件整理')
    # 只显示文件整理用得到的
    assert win._stack_out.currentIndex() == 1 and win._stack_settings.currentIndex() == 1
    assert not win.btn_add_archives.isVisibleTo(win) and not win.btn_pw.isVisibleTo(win)
    assert win.btn_undo.isVisibleTo(win) and not win.btn_sync.isVisibleTo(win)


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
    targets = [win.log, win.txt_roster, win.txt_out, win._stack_settings,
               win.btn_mode_person, win.txt_pwfile, win.lbl_result]
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


def test_password_button_shows_file(win, tmp_path):
    # 密码本按钮在「① 材料」区,上面直接显示用的是哪个文件
    assert win.btn_pw.isVisibleTo(win)
    win.txt_pwfile.setText(str(tmp_path / '密码.txt'))
    assert '密码.txt' in win.btn_pw.text()
    win.txt_pwfile.setText('')
    assert win.btn_pw.text() == '🔑 密码本…'


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
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    win.txt_lib.setText(str(tmp_path / 'lib'))       # 直接用上面显示的归档库,不再另选
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


def _wait(app, cond, sec=30):
    import time
    t0 = time.time()
    while not cond() and time.time() - t0 < sec:
        app.processEvents()
        time.sleep(0.02)


def test_accounts_menu_other_folder(win, app, tmp_path, monkeypatch):
    """按钮右边小箭头 →「其他放流水的文件夹…」。"""
    pytest.importorskip('pandas')
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from flow_samples import icbc_csv
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    d = tmp_path / '流水资料'; d.mkdir()
    (d / '工商银行.csv').write_bytes(icbc_csv())
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *a, **k: str(d))
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    done = {}
    monkeypatch.setattr(win, '_on_accounts_done', lambda path, res: done.update(res))
    acts = [a.text() for a in win.btn_accounts.menu().actions()]
    assert acts == ['整个归档库', '只做某个人…', '其他放流水的文件夹…']
    win.btn_accounts.menu().actions()[2].trigger()
    _wait(app, lambda: done)
    assert done['kind'] == 'plain' and (d / '账户汇总_流水资料.xlsx').is_file()


def test_accounts_without_library_explains(win, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: shown.append(a[-1]))
    win.txt_lib.setText('')
    win._accounts_only()
    assert shown and '归档库还不存在' in shown[-1]


def test_every_checkbox_reaches_joboptions(win, tmp_path, monkeypatch):
    """界面上(含对话框里)每个按人归档的勾选、数值都真正传到了 JobOptions。"""
    import fac.gui as G
    seen = {}

    def fake_run_job(opts, *a, **k):
        seen['opts'] = opts
    monkeypatch.setattr(G, 'run_job', fake_run_job)
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, 'question', lambda *a, **k: QMessageBox.Yes)
    (tmp_path / 'a.zip').write_bytes(b'PK')
    win._add_input(str(tmp_path / 'a.zip'))
    win.txt_lib.setText(str(tmp_path / 'lib'))
    flips = {k: not cb.isChecked() for k, cb in win._ck.items()}
    for k, v in flips.items():
        win._ck[k].setChecked(v)
    win._set_unit_mode('category')
    win.spin_emptykb.setValue(23)
    win.spin_minfreq.setValue(7)
    win.txt_iexclude.setText('甲专案,乙工程')
    win._rb_multi.button(1).setChecked(True)
    win.ck_short.setChecked(False)
    win.txt_roster.setPlainText('张三\n李四,李小四\n')
    win._start()
    import threading, time
    t0 = time.time()
    while 'opts' not in seen and time.time() - t0 < 5:
        time.sleep(0.02)
    o = seen['opts']
    for k, v in flips.items():
        assert getattr(o, k) is v, k
    assert o.empty_max_kb == 23 and o.intelligent_min_freq == 7
    assert o.intelligent_exclude == ['甲专案', '乙工程']
    assert o.copy_to_each is True and o.short_names is False
    assert len(o.roster) == 2 and o.unit_mode == 'category'
    assert o.out_dir == str(tmp_path / 'lib')


def test_unit_mode_disables_flow_options(win):
    win._set_unit_mode('subfolder')
    assert not win._flow_ck['account_summary'].isEnabled()
    win._set_unit_mode('category')
    assert win._flow_ck['account_summary'].isEnabled()


def test_roster_summary_counts_library_people(win, tmp_path):
    from fac.library import LEDGER_NAME
    lib = tmp_path / 'lib'; lib.mkdir()
    (lib / LEDGER_NAME).write_text('', encoding='utf-8')
    for n in ('张三_110101199003078515', '某某科技有限公司', '未分类'):
        (lib / n).mkdir()
    win.txt_lib.setText(str(lib))
    win._refresh_lib_info()
    assert '2 个人员/企业' in win.lbl_lib_info.text()
    assert '归档库已有 <b>2</b> 人' in win.lbl_roster_sum.text()
    win.txt_roster.setPlainText('王五,王小五\n')
    assert '名单 <b>1</b> 人' in win.lbl_roster_sum.text()
    win.txt_roster.setPlainText('王五,王小五\n张三\n')         # 名单里也有的不重复算
    assert '归档库已有 <b>1</b> 人' in win.lbl_roster_sum.text()
    assert win.lbl_roster_names.text().count('张三') == 1
    win.txt_roster.setPlainText('王五,王小五\n')
    assert '王五(王小五)' in win.lbl_roster_names.text()
    win._ck['lib_roster'].setChecked(False)
    assert '归档库已有' not in win.lbl_roster_sum.text()


def test_dialogs_hold_their_controls(win):
    """名单 / 更多设置 / 规则都在对话框里,控件照常存在。"""
    assert win.txt_roster.window() is win._dlg_roster
    assert win.txt_pwfile.window() is win._dlg_more
    assert win.spin_emptykb.window() is win._dlg_more
    assert win._ck['content_match'].window() is win._dlg_more
    assert win.spin_mindup.window() is win._dlg_more_org
    assert win._rule_area.window() is win._dlg_rules


def test_rules_roundtrip_and_count(win):
    win._add_rule()
    _ck, cmb, val, tgt = win._rule_rows[-1]
    cmb.setCurrentIndex(cmb.findData('ext')); val.setText('pdf'); tgt.setText('PDF')
    win._refresh_rule_buttons()
    assert all('1 条' in b.text() for b in win._rule_btns)
    cfg = win._gather_cfg()
    win._apply_cfg(cfg)
    win._apply_cfg(cfg)                    # 加载两次也不叠加
    assert len(win._get_rules()) == 1 and win._get_rules()[0].value == 'pdf'


def test_result_bar_after_person_job(win, tmp_path):
    (tmp_path / '未分类').mkdir()
    rep = tmp_path / '反馈核对表.xlsx'; rep.write_bytes(b'x')
    win.txt_lib.setText(str(tmp_path))
    from PySide6.QtWidgets import QMessageBox
    import unittest.mock as um
    with um.patch.object(QMessageBox, 'information'):
        win._on_done({'files': 126, 'reimport_skipped': 0, 'empty': 14,
                      'stats': {'张三': 3, '李四': 2, '未分类': 3},
                      'account_summaries': ['a', 'b'], 'reports': [str(rep)]})
    t = win.lbl_result.text()
    assert '126' in t and '2</b> 人/企业' in t and '3</b> 未分类' in t and '2</b> 份账户汇总' in t
    assert win.btn_res_unclassified.isVisibleTo(win) and win.btn_res_report.isVisibleTo(win)


def test_log_toggle(win):
    assert not win.log.isVisibleTo(win)
    win.btn_log.setChecked(True)
    assert win.log.isVisibleTo(win) and win._gather_cfg()['log_open'] is True


def test_sync_button_on_library(win, app, tmp_path, monkeypatch):
    """「🔄 同步归档记录」作用于上面显示的归档库。"""
    import zipfile
    from fac.pipeline import JobOptions, run_job
    from fac.roster import Roster
    src = tmp_path / 'in'; src.mkdir()
    with zipfile.ZipFile(src / '建设银行.zip', 'w') as z:
        z.writestr('张三_流水.xlsx', 'a')
    lib = tmp_path / 'lib'
    run_job(JobOptions([str(src)], str(lib), Roster.from_text('张三'), intelligent=False,
                       unit_mode='category'), lambda m: None, lambda *a: None, lambda *a: None)
    f = next(lib.rglob('*张三_流水.xlsx'))
    f.rename(f.with_name('张三_流水_已看.xlsx'))                # 手动改名
    from PySide6.QtWidgets import QMessageBox
    shown = []
    monkeypatch.setattr(QMessageBox, 'information', lambda *a, **k: shown.append(a[-1]))
    win.txt_lib.setText(str(lib))
    win._sync_library()
    _wait(app, lambda: shown)
    assert shown and '改名过的 1 个' in shown[-1]
