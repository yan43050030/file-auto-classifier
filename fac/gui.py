# -*- coding: utf-8 -*-
"""PySide6 Qt 图形界面——简洁现代风格。

设计原则:白底 + 蓝色强调 + 卡片式分区 + 引导式流程。
所有核心逻辑(fac/extract, pipeline, roster, intelligent 等)原样复用。
"""

import os
import re
import sys
import datetime
import threading

from PySide6.QtCore import Qt, Signal, QThread, QSize
from PySide6.QtGui import QFont, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QScrollBar,
    QLineEdit, QTabWidget, QPlainTextEdit, QTextEdit, QProgressBar,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QFileDialog,
    QMessageBox, QInputDialog, QSplitter, QFrame, QSizePolicy, QMenu,
    QScrollArea, QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSpinBox,
)

from . import VERSION, APP_NAME
from .util import resource_path, safe_rel_path
from .roster import Roster
from .pipeline import JobOptions, run_job
from .organize import OrganizeOptions, run_organize, LAYOUT_PRESETS
from . import undo as undo_mod
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
QScrollBar:vertical {{
    background: transparent; width: 8px; margin: 0;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1; border-radius: 4px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #94A3B8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 8px;
}}
QScrollBar::handle:horizontal {{
    background: #CBD5E1; border-radius: 4px; min-width: 30px;
}}
QScrollBar::handle:horizontal:hover {{ background: #94A3B8; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
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
        self.log.setMinimumHeight(80)
        bl.addWidget(self.log, 1)    # stretch=1 随窗口缩放
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
        gb = QGroupBox('②  保存到 / 工作模式')
        lay = QVBoxLayout(gb); lay.setSpacing(8)
        mr = QHBoxLayout(); mr.setSpacing(6)
        mr.addWidget(QLabel('工作模式:'))
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem('按人归档(查询反馈 / 办案材料)', 'person')
        self.cmb_mode.addItem('文件整理(下载目录 / 移动硬盘)', 'organize')
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        mr.addWidget(self.cmb_mode, 1)
        lay.addLayout(mr)
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
        ol = QVBoxLayout(to); ol.setSpacing(10); ol.setContentsMargins(16, 16, 16, 12)
        self._rb_multi = QButtonGroup(self)
        r1 = QRadioButton('命中多人→归入最匹配的(最长关键字优先)')
        r1.setChecked(True)
        self._rb_multi.addButton(r1, 0)
        ol.addWidget(r1)
        r2 = QRadioButton('命中多人→复制到每个文件夹')
        self._rb_multi.addButton(r2, 1)
        ol.addWidget(r2)
        ol.addWidget(self._sep())
        ol.addWidget(QLabel('来源单位标注(单位=压缩包名):'))
        self._rg_unit = QButtonGroup(self)
        u1 = QRadioButton('按单位建子文件夹(推荐)'); u1.setChecked(True)
        self._rg_unit.addButton(u1, 0); ol.addWidget(u1)
        u2 = QRadioButton('文件名加【单位】前缀')
        self._rg_unit.addButton(u2, 1); ol.addWidget(u2)
        u3 = QRadioButton('不标注来源')
        self._rg_unit.addButton(u3, 2); ol.addWidget(u3)
        ol.addStretch()
        tabs.addTab(to, '⚙ 分类选项')

        # ── 高级 tab(双列网格) ──
        ta = QWidget()
        al = QVBoxLayout(ta); al.setSpacing(8); al.setContentsMargins(16, 12, 16, 12)
        self._ck = {}
        grid = QGridLayout(); grid.setSpacing(8)
        ck_specs = [
            ('auto_id', '自动识别身份证号(18/15位,带校验码)', True),
            ('preview', '试运行预览:先看清单,确认后再执行', True),
            ('content_match', '内容匹配:读 Excel/Word/PDF/文本查人', False),
            ('split_excel', 'Excel 按人拆分:多人表按行拆每人一份(原表保留)', False),
            ('dedup', '内容去重:同文件夹内文件只留一份', False),
            ('intelligent', '智能识别:自动发现人名(排除机构/地名/职务),推测姓名↔证号', True),
            ('auto_pw_txt', '自动把 .txt 当密码本', True),
            ('delete_ok', '⚠ 成功后删除压缩包(移入回收站)', False),
        ]
        for idx, (key, label, default) in enumerate(ck_specs):
            cb = QCheckBox(label); cb.setChecked(default); self._ck[key] = cb
            grid.addWidget(cb, idx // 2, idx % 2)
        al.addLayout(grid)

        ir = QHBoxLayout(); ir.setSpacing(6)
        ir.addWidget(QLabel('智能识别:同一姓名出现于'))
        self.spin_minfreq = QSpinBox()
        self.spin_minfreq.setRange(2, 999)
        self.spin_minfreq.setValue(10)
        self.spin_minfreq.setFixedWidth(64)
        ir.addWidget(self.spin_minfreq)
        ir.addWidget(QLabel('个以上文件才算人名;额外排除词:'))
        self.txt_iexclude = QLineEdit()
        self.txt_iexclude.setPlaceholderText('逗号分隔,如:某某专案,某某工程(常见机构/地名已内置排除)')
        ir.addWidget(self.txt_iexclude, 1)
        al.addLayout(ir)
        al.addWidget(self._sep())

        al.addWidget(QLabel('高级分类规则(名单/智能未命中时按规则从上到下依次匹配):'))
        self._rule_area = QScrollArea()
        self._rule_area.setWidgetResizable(True)
        self._rule_inner = QWidget()
        self._rule_layout = QVBoxLayout(self._rule_inner)
        self._rule_layout.setSpacing(2); self._rule_layout.setContentsMargins(0, 2, 0, 2)
        self._rule_layout.addStretch()
        self._rule_area.setWidget(self._rule_inner)
        self._rule_area.setMinimumHeight(100)
        al.addWidget(self._rule_area, 1)

        rb2 = QHBoxLayout(); rb2.setSpacing(8)
        for txt, slot in [('+ 添加规则', self._add_rule), ('- 移除此规则', self._del_rule)]:
            b = QPushButton(txt); b.setFixedHeight(30); b.clicked.connect(slot)
            rb2.addWidget(b)
        rb2.addStretch(); al.addLayout(rb2)
        al.addWidget(self._sep())

        pwf = QHBoxLayout(); pwf.setSpacing(6)
        pwf.addWidget(QLabel('额外密码本:'))
        self.txt_pwfile = QLineEdit()
        pwf.addWidget(self.txt_pwfile)
        b = QPushButton('选择'); b.setFixedHeight(30); b.clicked.connect(self._choose_pw)
        pwf.addWidget(b)
        al.addLayout(pwf)
        tabs.addTab(ta, '🔧 高级功能')

        # ── 文件整理 tab ──
        tg = QWidget()
        gl = QVBoxLayout(tg); gl.setSpacing(8); gl.setContentsMargins(16, 12, 16, 12)
        hint = QLabel('把下载目录/移动硬盘里积攒的杂乱文件按类型+时间整理好,'
                      '同时挑出重复、旧版本和垃圾文件。\n'
                      '全过程记入台账,随时可一键撤销还原。')
        hint.setStyleSheet(f'color:{TEXT_SEC};')
        hint.setWordWrap(True)
        gl.addWidget(hint)

        lr = QHBoxLayout(); lr.setSpacing(6)
        lr.addWidget(QLabel('目录布局:'))
        self.cmb_layout = QComboBox()
        self.cmb_layout.setEditable(True)
        for tpl, desc in LAYOUT_PRESETS:
            self.cmb_layout.addItem(f'{tpl}      — {desc}', tpl)
        self.cmb_layout.setCurrentIndex(1)
        lr.addWidget(self.cmb_layout, 1)
        gl.addLayout(lr)
        ph = QLabel('可用占位符: {类别} {年} {年月} {来源} {扩展名}(可直接编辑组合)')
        ph.setStyleSheet(f'color:{TEXT_SEC}; font-size:11px;')
        gl.addWidget(ph)
        gl.addWidget(self._sep())

        opr = QHBoxLayout(); opr.setSpacing(12)
        opr.addWidget(QLabel('处理方式:'))
        self._rg_op = QButtonGroup(self)
        rb_mv = QRadioButton('移动(推荐:整理硬盘不占额外空间)'); rb_mv.setChecked(True)
        self._rg_op.addButton(rb_mv, 0); opr.addWidget(rb_mv)
        rb_cp = QRadioButton('复制(保留原件,需双倍空间)')
        self._rg_op.addButton(rb_cp, 1); opr.addWidget(rb_cp)
        opr.addStretch()
        gl.addLayout(opr)

        self._ckg = {}
        ggrid = QGridLayout(); ggrid.setSpacing(8)
        g_specs = [
            ('org_dup', '挑出重复文件(内容相同的只留一份,其余归入「重复文件」)', True),
            ('org_versions', '挑出旧版本(报告(1)/副本/最终版,旧的归入「旧版本」)', True),
            ('org_junk', '挑出垃圾文件(Thumbs.db/临时文件/未完成下载/空文件)', True),
            ('org_empty', '整理后清理空文件夹', True),
            ('org_large', '把大文件单独归入「大文件」文件夹', False),
            ('org_preview', '试运行预览:先看清单并可手改,确认后再执行', True),
            ('org_smart_date', '按真实日期归类:优先用照片拍摄时间/文件名里的日期', True),
            ('org_scan_only', '只体检不整理:仅出一份"有什么问题"的报告,不动任何文件', False),
        ]
        for idx, (key, label, default) in enumerate(g_specs):
            cb = QCheckBox(label); cb.setChecked(default); self._ckg[key] = cb
            ggrid.addWidget(cb, idx // 2, idx % 2)
        gl.addLayout(ggrid)

        sr = QHBoxLayout(); sr.setSpacing(6)
        sr.addWidget(QLabel('大文件阈值:'))
        self.spin_large = QSpinBox()
        self.spin_large.setRange(1, 100000)
        self.spin_large.setValue(100)
        self.spin_large.setSuffix(' MB')
        self.spin_large.setFixedWidth(110)
        sr.addWidget(self.spin_large)
        sr.addStretch()
        self.btn_purge = QPushButton('🗑 清理「可清理/重复/旧版本」')
        self.btn_purge.setFixedHeight(30)
        self.btn_purge.clicked.connect(self._purge_now)
        sr.addWidget(self.btn_purge)
        self.btn_undo = QPushButton('↩ 撤销上次整理')
        self.btn_undo.setFixedHeight(30)
        self.btn_undo.clicked.connect(self._undo_last)
        sr.addWidget(self.btn_undo)
        gl.addLayout(sr)
        gl.addStretch()
        tabs.addTab(tg, '📁 文件整理')
        self._tabs = tabs

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
            'intelligent_min_freq': self.spin_minfreq.value(),
            'intelligent_exclude': self.txt_iexclude.text().strip(),
            'work_mode': self._mode(),
            'org_layout': self.cmb_layout.currentText().split('—')[0].strip(),
            'org_op_mode': 'copy' if self._rg_op.checkedId() == 1 else 'move',
            'org_large_mb': self.spin_large.value(),
        }
        for k, cb in self._ckg.items():
            cfg[k] = cb.isChecked()
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
            self.spin_minfreq.setValue(int(cfg.get('intelligent_min_freq', 10)))
            self.txt_iexclude.setText(str(cfg.get('intelligent_exclude', '')))
            mode = cfg.get('work_mode', 'person')
            self.cmb_mode.setCurrentIndex(1 if mode == 'organize' else 0)
            lay_txt = cfg.get('org_layout', '')
            if lay_txt:
                idx = self.cmb_layout.findData(lay_txt)
                if idx >= 0:
                    self.cmb_layout.setCurrentIndex(idx)
                else:
                    self.cmb_layout.setEditText(lay_txt)
            self._rg_op.button(1 if cfg.get('org_op_mode') == 'copy'
                               else 0).setChecked(True)
            self.spin_large.setValue(int(cfg.get('org_large_mb', 100)))
            for k, cb in self._ckg.items():
                cb.setChecked(bool(cfg.get(k, cb.isChecked())))
            self._on_mode_changed()
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
               'scan': ('扫描', 0.0, 0.15), 'health': ('体检', 0.15, 0.45),
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
            dlg.resize(860, 520)
            lay = QVBoxLayout(dlg)
            tip = QLabel('双击"归入文件夹"一格可直接改;选中多行(Ctrl/Shift)后'
                         '点"改归到…"可批量改。改动只影响本次归档。')
            tip.setStyleSheet(f'color:{TEXT_SEC};')
            lay.addWidget(tip)
            tree = QTreeWidget()
            tree.setHeaderLabels(['文件名', '来源单位', '归入文件夹', '命中方式'])
            tree.setAlternatingRowColors(True)
            tree.setRootIsDecorated(False)
            tree.setSelectionMode(QTreeWidget.ExtendedSelection)
            tree.setEditTriggers(QTreeWidget.NoEditTriggers)
            rows = []       # (QTreeWidgetItem, PlanItem)
            for item in plan:
                it = QTreeWidgetItem(tree, [item.fname, item.unit,
                                            item.display_target(), item.via])
                if item.action == 'place':      # 拆分行不支持手改
                    it.setFlags(it.flags() | Qt.ItemIsEditable)
                rows.append((it, item))
            for i, w in enumerate([300, 140, 220, 90]):
                tree.header().resizeSection(i, w)

            def _dbl(it, col):
                if col == 2 and (it.flags() & Qt.ItemIsEditable):
                    tree.editItem(it, 2)
            tree.itemDoubleClicked.connect(_dbl)
            lay.addWidget(tree)

            btn_box = QDialogButtonBox()
            btn_re = btn_box.addButton('改归到…', QDialogButtonBox.ActionRole)

            def _reassign():
                sel = [s for s in tree.selectedItems()
                       if s.flags() & Qt.ItemIsEditable]
                if not sel:
                    QMessageBox.information(dlg, '提示',
                                            '请先选中要改的行(拆分行不可改)。')
                    return
                folders = sorted({t for _it, pi in rows
                                  for t in pi.targets} | {'未分类'})
                choice, ok = QInputDialog.getItem(
                    dlg, '改归到', '目标文件夹(可直接输入新名称):',
                    folders, 0, True)
                if ok and choice.strip():
                    for s in sel:
                        s.setText(2, choice.strip())
            btn_re.clicked.connect(_reassign)

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
            # 确认后把界面上的修改写回归档计划
            if dlg._ok:
                for it, pi in rows:
                    if pi.action != 'place':
                        continue
                    txt = it.text(2).strip()
                    if txt and txt != pi.display_target():
                        new_targets = [safe_rel_path(t.strip())
                                       for t in re.split(r'[、,，;；]', txt)
                                       if t.strip()]
                        if new_targets:
                            pi.targets = new_targets
                            pi.via += '·手改'
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

    # ---------- 工作模式 ----------

    def _mode(self):
        return self.cmb_mode.currentData() or 'person'

    def _on_mode_changed(self, _idx=0):
        organize = (self._mode() == 'organize')
        self.btn_run.setText('▶  开始整理' if organize else '▶  开始分类')
        # 切到对应设置页,避免用户改错地方
        try:
            if organize:
                self._tabs.setCurrentIndex(self._tabs.count() - 1)
            else:
                self._tabs.setCurrentIndex(0)
        except Exception:
            pass

    def _organize_opts(self, out):
        layout = (self.cmb_layout.currentData()
                  if self.cmb_layout.currentIndex() >= 0 and
                  '—' in self.cmb_layout.currentText() else None)
        if not layout:
            # 用户手动编辑过:取输入框里 — 之前的部分
            layout = self.cmb_layout.currentText().split('—')[0].strip()
        return OrganizeOptions(
            inputs=list(self.inputs), out_dir=out,
            layout=layout or '{类别}/{年}',
            op_mode='copy' if self._rg_op.checkedId() == 1 else 'move',
            preview=self._ckg['org_preview'].isChecked(),
            rules=self._get_rules(),
            find_dup=self._ckg['org_dup'].isChecked(),
            find_versions=self._ckg['org_versions'].isChecked(),
            find_junk=self._ckg['org_junk'].isChecked(),
            separate_large=self._ckg['org_large'].isChecked(),
            large_threshold=self.spin_large.value() * 1024 * 1024,
            clean_empty_dirs=self._ckg['org_empty'].isChecked(),
            date_source=('auto' if self._ckg['org_smart_date'].isChecked()
                         else 'mtime'),
            scan_only=self._ckg['org_scan_only'].isChecked())

    def _start_organize(self, out):
        opts = self._organize_opts(out)
        if opts.op_mode == 'move':
            r = QMessageBox.question(
                self, '确认整理',
                f'将把所选位置的文件【移动】到:\n{out}\n\n'
                f'目录布局: {opts.layout}\n\n'
                f'全过程会记入撤销台账,整理后可随时点「撤销上次整理」还原。\n'
                f'确定继续吗?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        conf.save_config(self._gather_cfg())
        self._begin_job()

        def done(summary):
            self._ui_call(lambda: self._on_done(summary))

        threading.Thread(
            target=run_organize,
            args=(opts, self._log, self._on_progress,
                  self._confirm_plan, self._cancel, done),
            daemon=True).start()

    def _purge_now(self):
        """把整理结果里的「可清理/重复文件/旧版本」删到回收站。"""
        from .organize import BUCKET_JUNK, BUCKET_DUP, BUCKET_OLD
        from .health import human_size
        out = self.txt_out.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.warning(self, '提示', '请先选择整理结果所在的目录。')
            return
        found = []
        for b in (BUCKET_JUNK, BUCKET_DUP, BUCKET_OLD):
            base = os.path.join(out, b)
            if not os.path.isdir(base):
                continue
            n, size = 0, 0
            for root, _d, fs in os.walk(base):
                for f in fs:
                    n += 1
                    try:
                        size += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            if n:
                found.append((b, n, size))
        if not found:
            QMessageBox.information(
                self, '提示',
                f'该目录里没有「可清理 / 重复文件 / 旧版本」可删:\n{out}')
            return

        names = [f'{b}({n} 个,{human_size(sz)})' for b, n, sz in found]
        picked, ok = QInputDialog.getItem(
            self, '选择要清理的内容',
            '把下列文件夹里的文件删到回收站(可先自行核对内容):',
            names + ['全部'], len(names), False)
        if not ok:
            return
        targets = ([b for b, _n, _s in found] if picked == '全部'
                   else [found[names.index(picked)][0]])
        total = sum(n for b, n, _s in found if b in targets)
        saved = sum(sz for b, _n, sz in found if b in targets)
        r = QMessageBox.question(
            self, '确认清理',
            f'将把 {total} 个文件移入回收站,腾出约 {human_size(saved)}。\n'
            f'涉及: {"、".join(targets)}\n\n'
            f'(移入回收站,误删可从回收站还原;但整理台账无法再撤销这些文件)\n'
            f'确定继续吗?',
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return

        from .organize import OrganizeOptions, _purge_buckets
        self._begin_job()

        def work():
            opts = OrganizeOptions([], out, purge=targets)
            n = _purge_buckets(opts, self._log, self._cancel)
            self._ui_call(lambda: self._on_purge_done(n, saved))

        threading.Thread(target=work, daemon=True).start()

    def _on_purge_done(self, n, saved):
        from .health import human_size
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        QMessageBox.information(
            self, '清理完成',
            f'已把 {n} 个文件移入回收站,腾出约 {human_size(saved)}。')

    def _undo_last(self):
        out = self.txt_out.text().strip()
        if not out or not os.path.isdir(out):
            QMessageBox.warning(self, '提示', '请先选择整理结果所在的目录。')
            return
        journals = undo_mod.find_journals(out)
        if not journals:
            QMessageBox.information(
                self, '提示',
                f'该目录里没有找到整理台账(整理台账_*.jsonl):\n{out}')
            return
        names = [os.path.basename(j) for j in journals]
        pick, ok = QInputDialog.getItem(
            self, '撤销整理', '选择要撤销的那次整理(最新的在最前):',
            names, 0, False)
        if not ok:
            return
        journal = journals[names.index(pick)]
        meta, ops = undo_mod.read_journal(journal)
        r = QMessageBox.question(
            self, '确认撤销',
            f'将按台账把 {len(ops)} 项操作全部还原:\n{pick}\n'
            f'整理时间: {meta.get("time", "?")}   方式: {meta.get("op_mode", "?")}\n\n'
            f'文件会被移回整理前的原始位置。确定吗?',
            QMessageBox.Yes | QMessageBox.No)
        if r != QMessageBox.Yes:
            return
        self._begin_job()

        def work():
            stats = undo_mod.undo(journal, log=self._log, cancel=self._cancel)
            self._ui_call(lambda: self._on_undo_done(stats))

        threading.Thread(target=work, daemon=True).start()

    def _on_undo_done(self, stats):
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        QMessageBox.information(
            self, '撤销完成',
            f'已还原 {stats.get("restored", 0)} 项,'
            f'删除副本 {stats.get("removed", 0)} 个。\n'
            f'找不到 {stats.get("missing", 0)} 个,失败 {stats.get("failed", 0)} 个。')

    def _begin_job(self):
        self.btn_run.setEnabled(False)
        self.btn_run.setText('处理中...')
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.setText('取消')
        self.progress.setValue(0)
        self.progress.setVisible(True)
        self.lbl_prog.setVisible(True)
        self.log.clear()
        self._cancel.clear()

    def _start(self):
        if not self.inputs:
            QMessageBox.warning(self, '提示', '请先添加压缩包/文件夹/文件。')
            return
        out = self.txt_out.text().strip()
        if not out:
            QMessageBox.warning(self, '提示', '请先选择输出目录。')
            return
        os.makedirs(out, exist_ok=True)

        if self._mode() == 'organize':
            self._start_organize(out)
            return

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
            intelligent_min_freq=self.spin_minfreq.value(),
            intelligent_exclude=[t for t in re.split(
                r'[,，;；\s]+', self.txt_iexclude.text()) if t.strip()],
            **{k: cb.isChecked() for k, cb in self._ck.items()})

        self._begin_job()

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
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.setText('取消')
        self.progress.setValue(0 if summary.get('cancelled') else 100)
        self.lbl_prog.setText('已取消' if summary.get('cancelled') else '完成')
        if summary.get('cancelled'):
            return
        if summary.get('journal'):
            self._on_organize_done(summary)
            return
        msg = f'分类完成!共处理 {summary.get("files", 0)} 个文件。'
        if summary.get('skipped_pw'):
            msg += f'\n{summary["skipped_pw"]} 个加密包未解压,见「暂未解压」。'
        if summary.get('failed'):
            msg += f'\n{summary["failed"]} 个包解压失败,见「解压失败」。'
        if summary.get('reports'):
            msg += '\n已生成反馈核对表。'
        QMessageBox.information(self, '完成', msg)

    def _on_organize_done(self, summary):
        from .health import human_size
        hs = summary.get('health', {})
        if summary.get('scan_only'):
            lines = ['体检完成(未移动任何文件):',
                     f'· 文件总数 {len(summary.get("stats", {})) or ""}'.rstrip(),
                     f'· 重复文件 {hs.get("dup_extra", 0)} 个,'
                     f'删除可省出 {human_size(hs.get("dup_bytes", 0))}',
                     f'· 垃圾/临时文件 {hs.get("junk", 0)} 个,'
                     f'占用 {human_size(hs.get("junk_bytes", 0))}',
                     f'· 旧版本 {hs.get("old_versions", 0)} 个',
                     '\n详见输出目录里的「整理报告」。'
                     '去掉「只体检」勾选后再运行,即可真正整理。']
            QMessageBox.information(self, '体检完成', '\n'.join(lines))
            return
        lines = [f'整理完成!共处理 {summary.get("files", 0)} 个文件。']
        if hs.get('dup_extra'):
            lines.append(f'· 重复文件 {hs["dup_extra"]} 个 → 「重复文件」,'
                         f'确认后删除可省出 {human_size(hs.get("dup_bytes", 0))}')
        if hs.get('junk'):
            lines.append(f'· 垃圾/临时文件 {hs["junk"]} 个 → 「可清理」,'
                         f'占用 {human_size(hs.get("junk_bytes", 0))}')
        if hs.get('old_versions'):
            lines.append(f'· 旧版本 {hs["old_versions"]} 个 → 「旧版本」')
        if summary.get('empty_dirs'):
            lines.append(f'· 清理空文件夹 {summary["empty_dirs"]} 个')
        if summary.get('failed'):
            lines.append(f'· 失败 {summary["failed"]} 个(见日志)')
        if summary.get('reports'):
            lines.append('· 已生成整理报告(类型/年份/占用/最大文件)')
        lines.append('\n如果结果不满意,点「文件整理」页的'
                     '「撤销上次整理」即可全部还原。')
        QMessageBox.information(self, '完成', '\n'.join(lines))

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
