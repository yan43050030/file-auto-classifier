# -*- coding: utf-8 -*-
"""PySide6 Qt 图形界面——简洁现代风格。

设计原则:白底 + 蓝色强调 + 卡片式分区 + 引导式流程。
所有核心逻辑(fac/extract, pipeline, roster, intelligent 等)原样复用。
"""

import os
import sys
import datetime
import threading

from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtGui import QFont, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QLineEdit, QTabWidget, QPlainTextEdit, QTextEdit, QProgressBar,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QFileDialog,
    QMessageBox, QInputDialog, QSplitter, QFrame, QSizePolicy, QMenu,
    QScrollArea, QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView,
)

from . import VERSION, APP_NAME
from .util import resource_path
from .roster import Roster
from .pipeline import JobOptions, run_job
from .rules import Rule
from . import config as conf
from . import extract as ex

# ---------- 样式常量 ----------
PRIMARY = '#2563EB'
PRIMARY_HOVER = '#1D4ED8'
DANGER = '#EF4444'
BG = '#F1F5F9'
CARD_BG = '#FFFFFF'
BORDER = '#E2E8F0'
TEXT = '#1E293B'
TEXT_SEC = '#64748B'
SUCCESS = '#10B981'
RADIUS = '8px'

QSS = f"""
QMainWindow {{ background: {BG}; }}
QGroupBox {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS};
    margin-top: 16px; padding: 16px; padding-top: 24px;
    font-size: 13px; font-weight: 600; color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 16px; top: 4px;
    color: {TEXT};
}}
QPushButton {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px 16px;
    background: {CARD_BG}; color: {TEXT}; font-size: 12px;
}}
QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QPushButton#btnRun {{
    background: {PRIMARY}; color: white; border: none; font-size: 14px;
    font-weight: 600; padding: 10px 32px;
}}
QPushButton#btnRun:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#btnRun:disabled {{ background: #94A3B8; }}
QPushButton#btnCancel {{
    background: {DANGER}; color: white; border: none; font-size: 13px;
    padding: 8px 20px;
}}
QPushButton#btnCancel:hover {{ background: #DC2626; }}
QPushButton#btnCancel:disabled {{ background: #FCA5A5; }}
QLineEdit, QPlainTextEdit, QTextEdit {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px;
    background: white; color: {TEXT}; font-size: 12px;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {PRIMARY};
}}
QListWidget {{
    border: 1px dashed {BORDER}; border-radius: 6px; background: #F8FAFC;
    font-size: 12px; padding: 4px;
}}
QListWidget::item {{ padding: 4px 8px; }}
QListWidget::item:selected {{ background: {PRIMARY}; color: white; border-radius: 4px; }}
QComboBox {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px;
    background: white; font-size: 12px;
}}
QCheckBox, QRadioButton {{ font-size: 12px; color: {TEXT}; spacing: 6px; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; }}
QTabBar::tab {{
    padding: 8px 20px; border: 1px solid transparent; font-size: 12px;
    color: {TEXT_SEC};
}}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {PRIMARY}; }}
QProgressBar {{
    border: none; border-radius: 4px; background: {BORDER}; height: 6px;
    text-align: center; font-size: 10px;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}
QScrollArea {{ border: none; background: transparent; }}
QTreeWidget {{
    border: 1px solid {BORDER}; border-radius: 6px;
    font-size: 12px; alternate-background-color: #F8FAFC;
}}
QTreeWidget::item:selected {{ background: {PRIMARY}; color: white; }}
QHeaderView::section {{
    background: #F1F5F9; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 10px; font-size: 12px; font-weight: 600;
}}
"""

# ---------- 主窗口 ----------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} {VERSION}')
        self.inputs = []
        self._cancel = threading.Event()
        self._rule_rows = []
        self._setup_ui()
        self._apply_cfg(conf.load_config())
        self._set_icon()

    def _set_icon(self):
        try:
            self.setWindowIcon(QIcon(resource_path('app.ico')))
        except Exception:
            pass

    # ---------- UI 搭建 ----------

    def _setup_ui(self):
        cw = QWidget()
        self.setCentralWidget(cw)
        main = QVBoxLayout(cw)
        main.setContentsMargins(12, 8, 12, 8)
        main.setSpacing(8)

        # ── 用 QSplitter 让各部分可拖拽调整大小 ──
        splitter = QSplitter(Qt.Vertical)

        # 上半区:输入 + 输出(水平排)
        top_w = QWidget()
        top_row = QHBoxLayout(top_w); top_row.setSpacing(12); top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addWidget(self._build_input_card(), 3)
        top_row.addWidget(self._build_output_card(), 2)
        splitter.addWidget(top_w)

        # 中区:设置(名单/选项/高级)
        splitter.addWidget(self._build_settings_card())

        # 下半区:操作按钮 + 进度 + 日志
        bottom_w = QWidget()
        bl = QVBoxLayout(bottom_w); bl.setSpacing(6); bl.setContentsMargins(0, 0, 0, 0)

        btn_row = QHBoxLayout(); btn_row.setSpacing(12)
        self.btn_run = QPushButton('▶  开始分类')
        self.btn_run.setObjectName('btnRun')
        self.btn_run.setMinimumHeight(44)
        self.btn_run.clicked.connect(self._start)
        btn_row.addWidget(self.btn_run)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.setObjectName('btnCancel')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_job)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch()
        self.btn_open = QPushButton('📂 打开结果文件夹')
        self.btn_open.clicked.connect(self._open_out)
        btn_row.addWidget(self.btn_open)
        bl.addLayout(btn_row)

        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        bl.addWidget(self.progress)
        self.lbl_prog = QLabel('')
        self.lbl_prog.setStyleSheet(f'color:{TEXT_SEC};font-size:11px;')
        self.lbl_prog.setVisible(False)
        bl.addWidget(self.lbl_prog)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(
            f'QTextEdit{{font-family:Consolas,"Microsoft YaHei UI";'
            f'font-size:11px;background:{CARD_BG};border:1px solid {BORDER};'
            f'border-radius:6px;padding:8px;}}')
        self.log.setMaximumHeight(140)
        bl.addWidget(self.log)
        splitter.addWidget(bottom_w)

        # 初始比例:上 1.5 : 中 4 : 下 1.5
        splitter.setSizes([150, 400, 150])

        main.addWidget(splitter)

        self.resize(1000, 750)
        self.setMinimumSize(800, 600)

    def _build_input_card(self):
        gb = QGroupBox('①  选择压缩包 / 文件夹 / 文件')
        gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(gb); lay.setSpacing(8)
        self.lst_inputs = QListWidget()
        self.lst_inputs.setAlternatingRowColors(True)
        self.lst_inputs.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst_inputs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst_inputs.customContextMenuRequested.connect(self._input_menu)
        lay.addWidget(self.lst_inputs)
        br = QHBoxLayout(); br.setSpacing(6)
        for txt, slot in [('添加压缩包', self._add_archives),
                          ('添加文件夹', self._add_folder),
                          ('添加文件', self._add_files)]:
            b = QPushButton(txt); b.setFixedHeight(30); b.clicked.connect(slot)
            br.addWidget(b)
        b = QPushButton('移除选中'); b.setFixedHeight(30); b.clicked.connect(self._rm_inputs)
        br.addWidget(b)
        b = QPushButton('清空'); b.setFixedHeight(30); b.clicked.connect(self._clr_inputs)
        br.addWidget(b)
        br.addStretch()
        lay.addLayout(br)
        lbl = QLabel('💡 支持拖拽文件/文件夹到上方列表')
        lbl.setStyleSheet(f'color:{TEXT_SEC};font-size:11px;')
        lay.addWidget(lbl)
        self._setup_drop()
        return gb

    def _build_output_card(self):
        gb = QGroupBox('②  保存到')
        lay = QVBoxLayout(gb); lay.setSpacing(8)
        r = QHBoxLayout(); r.setSpacing(6)
        self.txt_out = QLineEdit()
        self.txt_out.setPlaceholderText('自动填入,可手动改...')
        r.addWidget(self.txt_out)
        b = QPushButton('浏览'); b.setFixedHeight(32); b.clicked.connect(self._choose_out)
        r.addWidget(b)
        lay.addLayout(r)
        lay.addStretch()
        return gb

    def _build_settings_card(self):
        gb = QGroupBox('③  分类设置')
        lay = QVBoxLayout(gb); lay.setSpacing(0); lay.setContentsMargins(0, 20, 0, 0)
        tabs = QTabWidget()

        # ── 名单 tab ──
        tr = QWidget()
        tl = QVBoxLayout(tr); tl.setSpacing(6); tl.setContentsMargins(12, 12, 12, 12)
        rb = QHBoxLayout()
        for txt, slot in [('从 Excel 导入...', self._import_roster),
                          ('保存模板...', self._save_tpl),
                          ('加载模板...', self._load_tpl)]:
            b = QPushButton(txt); b.setFixedHeight(30); b.clicked.connect(slot)
            rb.addWidget(b)
        rb.addStretch()
        self.lbl_roster = QLabel('')
        self.lbl_roster.setStyleSheet(f'color:{TEXT_SEC};font-size:11px;')
        rb.addWidget(self.lbl_roster)
        tl.addLayout(rb)
        self.txt_roster = QPlainTextEdit()
        self.txt_roster.setPlaceholderText(
            '# 每行一个人:姓名,身份证号,曾用名…\n'
            '# 同一个人的姓名、证号、曾用名任一命中,文件都归入 TA 的文件夹。\n'
            '# 公司名等普通关键字也直接写一行\n'
            '# 示例(去掉开头的#即生效):\n张三\n李四,110101199003078515\n王五,王小五,老王')
        tl.addWidget(self.txt_roster)
        tabs.addTab(tr, '📋 人员名单')

        # ── 选项 tab ──
        to = QWidget()
        ol = QVBoxLayout(to); ol.setSpacing(8); ol.setContentsMargins(12, 16, 12, 12)
        self._rb_multi = QButtonGroup(self)
        r1 = QRadioButton('命中多人 → 归入最匹配的(最长关键字优先)')
        r1.setChecked(True)
        self._rb_multi.addButton(r1, 0)
        ol.addWidget(r1)
        r2 = QRadioButton('命中多人 → 复制到每个文件夹')
        self._rb_multi.addButton(r2, 1)
        ol.addWidget(r2)
        ol.addWidget(self._sep())
        ol.addWidget(QLabel('来源单位标注(单位=压缩包名):'))
        self._rg_unit = QButtonGroup(self)
        u1 = QRadioButton('人员下按单位建子文件夹(推荐)'); u1.setChecked(True)
        self._rg_unit.addButton(u1, 0)
        ol.addWidget(u1)
        u2 = QRadioButton('文件名加【单位】前缀')
        self._rg_unit.addButton(u2, 1)
        ol.addWidget(u2)
        u3 = QRadioButton('不标注来源')
        self._rg_unit.addButton(u3, 2)
        ol.addWidget(u3)
        ol.addStretch()
        tabs.addTab(to, '⚙ 分类选项')

        # ── 高级 tab ──
        ta = QWidget()
        al = QVBoxLayout(ta); al.setSpacing(6); al.setContentsMargins(12, 12, 12, 12)
        # 统一用 dict 管理所有 checkbox,key=配置键名,value=(QCheckBox, 默认值)
        self._ck = {}
        for ck_key, ck_label, ck_default, ck_tab in [
            ('auto_id', '自动识别身份证号(18/15位,带校验码)', True, 'options'),
            ('preview', '试运行预览:先看清单,确认后再执行', True, 'options'),
            ('content_match', '内容匹配:读 Excel/Word/PDF/文本内容查人', False, 'advanced'),
            ('split_excel', 'Excel 按人拆分:多人的表按行拆每人一份(原表保留)', False, 'advanced'),
            ('dedup', '内容去重:同文件夹内相同文件只留一份', False, 'advanced'),
            ('intelligent', '智能识别:自动发现 10+ 文件中重复出现的人名,'
                           '并从文件名推测姓名↔身份证号对应关系', True, 'advanced'),
            ('auto_pw_txt', '自动把输入文件夹的 .txt 当密码本', True, 'advanced'),
            ('delete_ok', '⚠ 成功后删除已解压压缩包(移入回收站)', False, 'advanced'),
        ]:
            cb = QCheckBox(ck_label)
            cb.setChecked(ck_default)
            self._ck[ck_key] = cb
            if ck_tab == 'options':
                ol.insertWidget(ol.count() - 1, cb)    # 插在 stretch 之前
            else:
                al.addWidget(cb)
        # 在高级 tab 中智能识别后加分隔线
        al.insertWidget(al.indexOf(self._ck['auto_pw_txt']), self._sep())
        al.addWidget(QLabel('高级分类规则(名单/智能未命中时按匹配):'))
        self._rule_area = QScrollArea()
        self._rule_area.setWidgetResizable(True)
        self._rule_inner = QWidget()
        self._rule_layout = QVBoxLayout(self._rule_inner)
        self._rule_layout.setSpacing(2); self._rule_layout.setContentsMargins(0, 0, 0, 0)
        self._rule_layout.addStretch()
        self._rule_area.setWidget(self._rule_inner)
        self._rule_area.setMinimumHeight(80)
        al.addWidget(self._rule_area, 1)    # stretch=1,随窗口缩放自动扩展
        rb2 = QHBoxLayout()
        b = QPushButton('+ 添加规则'); b.clicked.connect(self._add_rule); rb2.addWidget(b)
        b = QPushButton('- 移除此规则'); b.clicked.connect(self._del_rule); rb2.addWidget(b)
        rb2.addStretch()
        al.addLayout(rb2)
        al.addWidget(self._sep())
        pwf = QHBoxLayout(); pwf.setSpacing(6)
        pwf.addWidget(QLabel('额外密码本:'))
        self.txt_pwfile = QLineEdit()
        pwf.addWidget(self.txt_pwfile)
        b = QPushButton('选择'); b.setFixedHeight(30); b.clicked.connect(self._choose_pw)
        pwf.addWidget(b)
        al.addLayout(pwf)
        al.addStretch()
        tabs.addTab(ta, '🔧 高级功能')

        lay.addWidget(tabs)
        return gb

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f'QFrame{{color:{BORDER};}}')
        f.setFixedHeight(1)
        return f

    # ---------- 输入操作 ----------

    def _add_input(self, path):
        path = path.strip()
        if not path or path in self.inputs:
            return
        if os.path.isdir(path):
            self.inputs.append(path)
            self.lst_inputs.addItem(f'📁 {path}')
        elif os.path.isfile(path):
            self.inputs.append(path)
            self.lst_inputs.addItem(f'📄 {path}')
        # 首次添加自动填输出目录
        if len(self.inputs) == 1 and not self.txt_out.text().strip():
            base = path if os.path.isdir(path) else os.path.dirname(path)
            self.txt_out.setText(os.path.join(base, f'分类结果_{datetime.datetime.now():%Y%m%d}'))

    def _add_archives(self):
        fs, _ = QFileDialog.getOpenFileNames(
            self, '选择压缩包', '',
            '压缩包 (*.zip *.7z *.rar *.tar *.gz *.tgz *.001);;所有文件 (*.*)')
        for f in fs:
            self._add_input(f)

    def _add_folder(self):
        d = QFileDialog.getExistingDirectory(self, '选择文件夹')
        if d:
            self._add_input(d)

    def _add_files(self):
        fs, _ = QFileDialog.getOpenFileNames(self, '选择文件', '', '所有文件 (*.*)')
        for f in fs:
            self._add_input(f)

    def _rm_inputs(self):
        for item in self.lst_inputs.selectedItems():
            row = self.lst_inputs.row(item)
            if row < len(self.inputs):
                del self.inputs[row]
            self.lst_inputs.takeItem(row)

    def _clr_inputs(self):
        self.inputs.clear()
        self.lst_inputs.clear()

    def _input_menu(self, pos):
        item = self.lst_inputs.itemAt(pos)
        if item:
            self.lst_inputs.setCurrentItem(item)
        menu = QMenu(self)
        menu.addAction('移除选中', self._rm_inputs)
        menu.addAction('清空全部', self._clr_inputs)
        menu.exec(self.lst_inputs.viewport().mapToGlobal(pos))

    def _setup_drop(self):
        self.lst_inputs.setAcceptDrops(True)
        self.setAcceptDrops(True)

        class DropList(QListWidget):
            def __init__(self, parent, cb):
                super().__init__(parent)
                self._cb = cb

            def dragEnterEvent(self, e):
                if e.mimeData().hasUrls():
                    e.acceptProposedAction()

            def dropEvent(self, e):
                for url in e.mimeData().urls():
                    self._cb(url.toLocalFile())
        # 替换 list widget 为支持拖拽的版本
        old = self.lst_inputs
        new = DropList(old.parentWidget(), self._add_input)
        new.setAlternatingRowColors(True)
        new.setSelectionMode(QListWidget.ExtendedSelection)
        new.setContextMenuPolicy(Qt.CustomContextMenu)
        new.customContextMenuRequested.connect(self._input_menu)
        # 复制原有 layout 位置
        parent_layout = old.parentWidget().layout()
        if parent_layout:
            idx = parent_layout.indexOf(old)
            parent_layout.insertWidget(idx, new)
            parent_layout.removeWidget(old)
        old.deleteLater()
        self.lst_inputs = new

    def _choose_out(self):
        d = QFileDialog.getExistingDirectory(self, '选择输出目录')
        if d:
            self.txt_out.setText(d)

    def _choose_pw(self):
        f, _ = QFileDialog.getOpenFileName(
            self, '选择密码本 txt', '', '文本 (*.txt);;所有文件 (*.*)')
        if f:
            self.txt_pwfile.setText(f)

    def _open_out(self):
        out = self.txt_out.text().strip()
        if out and os.path.isdir(out):
            try:
                os.startfile(out)
            except Exception:
                QMessageBox.information(self, '提示', f'结果目录:\n{out}')
        else:
            QMessageBox.warning(self, '提示', '请先选择有效的输出目录。')

    # ---------- 名单导入 ----------

    def _import_roster(self):
        f, _ = QFileDialog.getOpenFileName(
            self, '选择名单 Excel', '',
            'Excel (*.xlsx *.xlsm);;所有文件 (*.*)')
        if not f:
            return
        try:
            roster = Roster.from_excel(f)
        except ImportError:
            QMessageBox.critical(self, '缺少依赖', '需安装 openpyxl:\npip install openpyxl')
            return
        except Exception as e:
            QMessageBox.critical(self, '导入失败', str(e))
            return
        if not roster.persons:
            QMessageBox.warning(self, '提示', '未识别到人员。')
            return
        lines = []
        for p in roster.persons:
            parts = [p.name] + p.ids + p.aliases
            lines.append(','.join(parts))
        self.txt_roster.appendPlainText('\n'.join(lines))
        self.lbl_roster.setText(f'已导入 {len(roster.persons)} 人')

    def _save_tpl(self):
        f, _ = QFileDialog.getSaveFileName(
            self, '保存任务模板', conf.template_dir(), '任务模板 (*.json)')
        if f:
            try:
                conf.save_template(f, self._gather_cfg())
            except Exception as e:
                QMessageBox.critical(self, '保存失败', str(e))

    def _load_tpl(self):
        f, _ = QFileDialog.getOpenFileName(
            self, '加载任务模板', conf.template_dir(),
            '任务模板 (*.json);;所有文件 (*.*)')
        if f:
            try:
                self._apply_cfg(conf.load_template(f))
            except Exception as e:
                QMessageBox.critical(self, '加载失败', str(e))

    # ---------- 高级规则 ----------

    def _add_rule(self):
        row_ct = len(self._rule_rows)
        row_w = QWidget()
        hl = QHBoxLayout(row_w); hl.setSpacing(6); hl.setContentsMargins(0, 2, 0, 2)
        ck = QCheckBox(); ck.setChecked(True); hl.addWidget(ck)
        cmb = QComboBox(); cmb.setFixedWidth(150)
        for v, label in [('ext', '扩展名'), ('size_gt', '文件大于'),
                          ('size_lt', '文件小于'), ('date_before', '修改早于'),
                          ('date_after', '修改晚于'), ('contains', '包含文字'),
                          ('regex', '正则匹配')]:
            cmb.addItem(label, v)
        hl.addWidget(cmb)
        hl.addWidget(QLabel('值'))
        val = QLineEdit(); val.setPlaceholderText('如 pdf / 10MB'); val.setFixedWidth(120)
        hl.addWidget(val)
        hl.addWidget(QLabel('归入'))
        tgt = QLineEdit(); tgt.setFixedWidth(100)
        hl.addWidget(tgt)
        hl.addStretch()
        self._rule_rows.append((ck, cmb, val, tgt))
        # 插入到 stretch 前
        self._rule_layout.insertWidget(self._rule_layout.count() - 1, row_w)

    def _del_rule(self):
        for i, (ck, _cmb, _val, _tgt) in enumerate(self._rule_rows):
            if ck.isChecked():
                row_w = ck.parentWidget()
                self._rule_layout.removeWidget(row_w)
                row_w.deleteLater()
                del self._rule_rows[i]
                self._del_rule()  # 递归删除所有选中的
                return

    def _get_rules(self):
        rules = []
        for _ck, cmb, val, tgt in self._rule_rows:
            t = cmb.currentData()
            v = val.text().strip()
            if t and v:
                rules.append(Rule(t, v, tgt.text().strip(),
                                  cmb.parentWidget().findChild(QCheckBox).isChecked()))
        return rules

    # ---------- 配置 ----------

    def _gather_cfg(self):
        cfg = {
            'out_dir': self.txt_out.text().strip(),
            'roster_text': self.txt_roster.toPlainText().rstrip('\n'),
            'multi_hit': 'first' if self._rb_multi.checkedId() == 0 else 'each',
            'unit_mode': ['subfolder', 'prefix', 'none'][self._rg_unit.checkedId()],
            'pw_file': self.txt_pwfile.text().strip(),
            'rules': [r.to_dict() for r in self._get_rules()],
        }
        for ck_key, cb in self._ck.items():
            cfg[ck_key] = cb.isChecked()
        return cfg

    def _apply_cfg(self, cfg):
        try:
            if cfg.get('out_dir'):
                self.txt_out.setText(cfg['out_dir'])
            if cfg.get('roster_text'):
                self.txt_roster.setPlainText(cfg['roster_text'] + '\n')
            self._rb_multi.button(0).setChecked(cfg.get('multi_hit','first')=='first')
            self._rb_multi.button(1).setChecked(cfg.get('multi_hit','first')=='each')
            um = cfg.get('unit_mode', 'subfolder')
            self._rg_unit.button(0).setChecked(um == 'subfolder')
            self._rg_unit.button(1).setChecked(um == 'prefix')
            self._rg_unit.button(2).setChecked(um == 'none')
            self.txt_pwfile.setText(cfg.get('pw_file', ''))
            # 所有 checkbox 统一迭代设置
            for ck_key, cb in self._ck.items():
                cb.setChecked(bool(cfg.get(ck_key, cb.isChecked())))
            # 加载规则
            for d in cfg.get('rules', []):
                self._add_rule()
                _ck, cmb, val, tgt = self._rule_rows[-1]
                idx = cmb.findData(d.get('rule_type', 'ext'))
                if idx >= 0:
                    cmb.setCurrentIndex(idx)
                val.setText(d.get('value', ''))
                tgt.setText(d.get('target', ''))
                cmb.parentWidget().findChild(QCheckBox).setChecked(
                    bool(d.get('enabled', True)))
        except Exception:
            pass

    # ---------- 日志 / 进度 ----------

    def _log(self, msg):
        self.log.append(msg)
        sb = self.log.verticalScrollBar()
        sb.setValue(sb.maximum())

    _PHASES = {'extract': ('解压', 0, 0.5), 'classify': ('匹配', 0.5, 0.2),
               'place': ('归档', 0.7, 0.3)}

    def _on_progress(self, phase, cur, total):
        name, base, span = self._PHASES.get(phase, (phase, 0, 1))
        pct = int((base + cur / total * span if total else base) * 100)
        self.progress.setVisible(True)
        self.progress.setValue(pct)
        self.lbl_prog.setVisible(True)
        self.lbl_prog.setText(f'{name} {cur}/{total}')

    # ---------- 后台交互 ----------

    def _ask_password(self, archive_name, attempt):
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        result = [None]

        def _prompt():
            if attempt > 1:
                msg = f'密码错误,请重新输入。\n\n'
            else:
                msg = f'该压缩包有密码。\n\n'
            msg += f'「{archive_name}」需要解压密码:\n(取消→放入"暂未解压")'
            pwd, ok = QInputDialog.getText(
                self, '需要解压密码', msg,
                QLineEdit.Password, '')
            result[0] = pwd if ok else None
            loop.quit()

        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _prompt)
        loop.exec()
        return result[0]

    def _confirm_plan(self, plan):
        from PySide6.QtCore import QEventLoop
        loop = QEventLoop()
        result = [False]
        QTimer = __import__('PySide6.QtCore', fromlist=['QTimer']).QTimer

        def _show():
            dlg = QDialog(self)
            dlg.setWindowTitle(f'预览归档计划(共 {len(plan)} 个文件)')
            dlg.resize(820, 480)
            lay = QVBoxLayout(dlg)
            tree = QTreeWidget()
            tree.setHeaderLabels(['文件名', '来源单位', '归入文件夹', '命中方式'])
            tree.setAlternatingRowColors(True)
            tree.setRootIsDecorated(False)
            for item in plan:
                QTreeWidgetItem(tree, [item.fname, item.unit,
                                       item.display_target(), item.via])
            for i, w in enumerate([300, 140, 200, 80]):
                tree.header().resizeSection(i, w)
            lay.addWidget(tree)
            btn_box = QDialogButtonBox()
            btn_ok = btn_box.addButton('确认执行', QDialogButtonBox.AcceptRole)
            btn_no = btn_box.addButton('取消', QDialogButtonBox.RejectRole)
            n_un = sum(1 for i in plan if i.targets == ['未分类'])
            lbl = QLabel(f'未分类: {n_un} 个')
            lbl.setStyleSheet(f'color:{TEXT_SEC};')
            btn_box.layout().insertWidget(0, lbl)
            btn_box.accepted.connect(lambda: (setattr(dlg, '_ok', True), dlg.accept()))
            btn_box.rejected.connect(lambda: (setattr(dlg, '_ok', False), dlg.reject()))
            lay.addWidget(btn_box)
            dlg._ok = False
            dlg.exec()
            result[0] = dlg._ok
            loop.quit()

        from PySide6.QtCore import QTimer as _QTimer
        _QTimer.singleShot(0, _show)
        loop.exec()
        return result[0]

    # ---------- 运行 ----------

    def _cancel_job(self):
        self._cancel.set()
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText('正在取消...')

    def _start(self):
        if not self.inputs:
            QMessageBox.warning(self, '提示', '请先添加压缩包/文件夹/文件。')
            return
        out = self.txt_out.text().strip()
        if not out:
            QMessageBox.warning(self, '提示', '请先选择输出目录。')
            return
        os.makedirs(out, exist_ok=True)
        roster = Roster.from_text(self.txt_roster.toPlainText())
        if len(roster) == 0 and not self._ck['auto_id'].isChecked():
            QMessageBox.warning(self, '提示', '请至少输入名单,或勾选"自动识别身份证号"。')
            return

        pw_files = []
        pf = self.txt_pwfile.text().strip()
        if pf:
            if os.path.isfile(pf):
                pw_files.append(pf)
            else:
                QMessageBox.warning(self, '提示', '密码本文件不存在,已忽略。')
        if self._ck['delete_ok'].isChecked():
            r = QMessageBox.question(
                self, '确认删除',
                '分类完成后将把【已成功解压】的压缩包移入回收站。\n确定继续?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return

        conf.save_config(self._gather_cfg())
        opts = JobOptions(
            inputs=list(self.inputs), out_dir=out, roster=roster,
            copy_to_each=(self._rb_multi.checkedId() == 1),
            unit_mode=['subfolder','prefix','none'][self._rg_unit.checkedId()],
            pw_files=pw_files,
            rules=self._get_rules(),
            **{k: cb.isChecked() for k, cb in self._ck.items()})

        self.btn_run.setEnabled(False)
        self.btn_run.setText('处理中...')
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText('取消')
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_prog.setVisible(True)
        self.log.clear()
        self._cancel.clear()

        summary = {}

        def done(s):
            summary.update(s)
            self._ui_call(lambda: self._on_done(summary))

        t = threading.Thread(
            target=run_job,
            args=(opts, self._log, self._on_progress, self._ask_password,
                  self._confirm_plan, self._cancel, done),
            daemon=True)
        t.start()

    def _on_done(self, summary):
        self.btn_run.setEnabled(True)
        self.btn_run.setText('▶  开始分类')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText('取消')
        self.progress.setValue(0 if summary.get('cancelled') else 100)
        self.lbl_prog.setText('已取消' if summary.get('cancelled') else '完成')
        if summary.get('cancelled'):
            return
        msg = f'分类完成!共处理 {summary.get("files", 0)} 个文件。'
        if summary.get('skipped_pw'):
            msg += f'\n{summary["skipped_pw"]} 个加密包未解压,见「暂未解压」。'
        if summary.get('failed'):
            msg += f'\n{summary["failed"]} 个包解压失败,见「解压失败」。'
        if summary.get('reports'):
            msg += '\n已生成反馈核对表。'
        QMessageBox.information(self, '完成', msg)

    def _ui_call(self, fn):
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, fn)

    def closeEvent(self, event):
        conf.save_config(self._gather_cfg())
        event.accept()


# ---------- HIDPI + 入口 ----------

def _enable_hidpi():
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


def main():
    _enable_hidpi()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    font = QFont('Microsoft YaHei UI', 10)
    app.setFont(font)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
