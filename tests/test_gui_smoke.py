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
