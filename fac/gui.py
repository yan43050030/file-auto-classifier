# -*- coding: utf-8 -*-
"""PySide6 Qt 图形界面——简洁现代风格。

设计原则:白底 + 蓝色强调 + 卡片式分区 + 引导式流程。
所有核心逻辑(fac/extract, pipeline, roster, intelligent 等)原样复用。
"""

import os
import re
import sys
import datetime
import gc
import threading

from PySide6.QtCore import Qt, Signal, QThread, QSize, QEvent
from PySide6.QtGui import QFont, QIcon, QAction
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QGroupBox, QListWidget, QListWidgetItem, QPushButton, QLabel,
    QScrollBar,
    QLineEdit, QTabWidget, QPlainTextEdit, QTextEdit, QProgressBar,
    QComboBox, QCheckBox, QRadioButton, QButtonGroup, QFileDialog,
    QMessageBox, QInputDialog, QSplitter, QFrame, QSizePolicy, QMenu,
    QScrollArea, QDialog, QDialogButtonBox, QTreeWidget, QTreeWidgetItem,
    QHeaderView, QSpinBox, QStackedWidget, QToolButton,
)

from . import VERSION, APP_NAME
from .util import resource_path, safe_rel_path
from .roster import Roster
from .pipeline import JobOptions, run_job
from .organize import LAYOUT_PRESETS
from .rules import Rule
from . import config as conf
from . import extract as ex

from .gui_style import QSS, TEXT_SEC, CARD_BG, BORDER, PRIMARY, apply_theme  # noqa: F401
from .gui_style import fit_tree_columns, roomy_dialog
from .gui_organize import OrganizeMixin
from .gui_tips import apply_tooltips, TIPS
from .gui_bridge import UiBridge, in_main_thread

# ---------- 拖拽 ----------

def _accept_urls(e):
    if e.mimeData().hasUrls():
        e.acceptProposedAction()
    else:
        e.ignore()


def _drop_urls(e, add):
    if not e.mimeData().hasUrls():
        e.ignore()
        return
    for url in e.mimeData().urls():
        p = url.toLocalFile()
        if p:
            add(os.path.normpath(p))
    e.acceptProposedAction()


class _DropList(QListWidget):
    """可从资源管理器拖入文件/文件夹的输入列表。

    QListWidget 默认在 dragMove 阶段拒绝外部文件(光标一直是禁止符号),
    所以 dragEnter / dragMove / drop 三个事件都要接管。"""

    def __init__(self, on_path, parent=None):
        super().__init__(parent)
        self._on_path = on_path
        self.setAcceptDrops(True)
        self.viewport().setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)

    def dragEnterEvent(self, e):
        _accept_urls(e)

    def dragMoveEvent(self, e):
        _accept_urls(e)

    def dropEvent(self, e):
        _drop_urls(e, self._on_path)


# ---------- 主窗口 ----------

class MainWindow(OrganizeMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f'{APP_NAME} {VERSION}')
        self.inputs = []
        self._cancel = threading.Event()
        self._rule_rows = []
        # 后台线程只往这里投递,由主线程定时刷到界面(见 _flush_ui)
        self._bridge = UiBridge(self)
        self._log_buf = []
        self._log_lock = threading.Lock()
        self._prog_state = None
        self._manual = {'person': False, 'organize': False}
        self._last_out = ''
        self._last_report = ''
        self._setup_ui()
        from PySide6.QtCore import QTimer
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(100)
        self._ui_timer.timeout.connect(self._flush_ui)
        self._ui_timer.start()
        # Python 的循环垃圾回收可能恰好在后台线程里触发,顺手释放掉已不用的
        # 对话框等 Qt 对象 —— Qt 要求它们只能在主线程销毁,否则直接闪退。
        # 所以关掉自动回收,改由主线程每 2 秒回收一次。
        gc.disable()
        self._gc_timer = QTimer(self)
        self._gc_timer.setInterval(2000)
        self._gc_timer.timeout.connect(gc.collect)
        self._gc_timer.start()
        self._apply_cfg(conf.load_config())
        self._set_icon()
        apply_tooltips(self)
        self._on_mode_changed()

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

        # ── 顶部:两种工作模式,像两个大按钮(当前模式着色) ──
        # cmb_mode 不显示,只作为"当前模式"的唯一来源(配置、测试、旧代码都用它)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem('按人归档(查询反馈 / 办案材料)', 'person')
        self.cmb_mode.addItem('文件整理(下载目录 / 移动硬盘)', 'organize')
        self.cmb_mode.setVisible(False)
        self.cmb_mode.setToolTip('当前工作模式')
        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        mr = QHBoxLayout(); mr.setSpacing(0)
        self._mode_labels = []
        btns = []
        for i, (title, sub, tip) in enumerate([
                ('📋  按人归档', '查询反馈 / 案件材料 → 每人一个文件夹', TIPS['📋  按人归档']),
                ('📁  文件整理', '下载目录 / 移动硬盘 → 按类型、时间', TIPS['📁  文件整理'])]):
            b = QPushButton()
            b.setObjectName('modeBtn')
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(tip)
            bl = QHBoxLayout(b); bl.setContentsMargins(16, 4, 16, 4); bl.setSpacing(12)
            bl.setSizeConstraint(QHBoxLayout.SetNoConstraint)
            t = QLabel(title); s_ = QLabel(sub)
            for x in (t, s_):
                x.setAttribute(Qt.WA_TransparentForMouseEvents)
            bl.addWidget(t); bl.addWidget(s_, 1)
            self._mode_labels.append((t, s_))
            b.clicked.connect(lambda _c=False, i=i: self.cmb_mode.setCurrentIndex(i))
            b.setFixedHeight(54)
            mr.addWidget(b, 1)
            btns.append(b)
        self.btn_mode_person, self.btn_mode_org = btns
        main.addLayout(mr)
        main.addWidget(self.cmb_mode)

        # ── 中部:左 = ① 材料 + ② 结果放哪;右 = 设置(随模式切换) ──
        mid = QHBoxLayout(); mid.setSpacing(10)
        left = QVBoxLayout(); left.setSpacing(8)
        left.addWidget(self._build_input_card(), 1)
        left.addWidget(self._build_output_card())
        mid.addLayout(left, 3)
        self._stack_settings = QStackedWidget()
        self._stack_settings.addWidget(self._build_person_settings())
        self._stack_settings.addWidget(self._build_organize_settings())
        self._stack_settings.setMinimumWidth(290)
        mid.addWidget(self._stack_settings, 2)
        main.addLayout(mid, 1)

        # 不常用的设置、名单、规则放对话框里(控件照常存在,随时可用)
        self._build_roster_dialog()
        self._build_rules_dialog()
        self._build_more_person_dialog()
        self._build_more_org_dialog()

        # ── 底部:开始 / 取消 / 进度 + 上次结果 + 详细日志(可展开) ──
        btn_row = QHBoxLayout(); btn_row.setSpacing(12)
        self.btn_run = QPushButton('▶  开始归档')
        self.btn_run.setObjectName('btnRun')
        self.btn_run.setMinimumHeight(46)
        self.btn_run.setMinimumWidth(150)
        self.btn_run.clicked.connect(self._start)
        btn_row.addWidget(self.btn_run)
        self.btn_cancel = QPushButton('取消')
        self.btn_cancel.setObjectName('btnCancel')
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_job)
        btn_row.addWidget(self.btn_cancel)
        pv = QVBoxLayout(); pv.setSpacing(2)
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setVisible(False)
        pv.addWidget(self.progress)
        self.lbl_prog = QLabel('')
        self.lbl_prog.setStyleSheet(f'color:{TEXT_SEC};font-size:12px;')
        self.lbl_prog.setVisible(False)
        pv.addWidget(self.lbl_prog)
        btn_row.addLayout(pv, 1)
        main.addLayout(btn_row)

        gb = QFrame()
        gb.setObjectName('resultBar')
        gb.setStyleSheet(f'QFrame#resultBar{{background:{CARD_BG};border:1px solid {BORDER};'
                         f'border-radius:8px;}}')
        rl = QVBoxLayout(gb); rl.setSpacing(4); rl.setContentsMargins(10, 6, 10, 6)
        rr = QHBoxLayout(); rr.setSpacing(6)
        t = QLabel('上次结果'); t.setStyleSheet('font-weight:600;')
        rr.addWidget(t)
        self.lbl_result = QLabel('还没有运行过。')
        self.lbl_result.setTextFormat(Qt.RichText)
        self.lbl_result.setWordWrap(True)
        rr.addWidget(self.lbl_result, 1)
        self.btn_res_unclassified = QPushButton('查看未分类')
        self.btn_res_unclassified.clicked.connect(self._open_unclassified)
        self.btn_res_unclassified.setVisible(False)
        rr.addWidget(self.btn_res_unclassified)
        self.btn_res_report = QPushButton('打开核对表')
        self.btn_res_report.clicked.connect(self._open_report)
        self.btn_res_report.setVisible(False)
        rr.addWidget(self.btn_res_report)
        self.btn_log = QPushButton('详细日志 ▾')
        self.btn_log.setCheckable(True)
        self.btn_log.toggled.connect(self._toggle_log)
        rr.addWidget(self.btn_log)
        rl.addLayout(rr)
        # QPlainTextEdit + 行数上限:文件特别多时日志也不会把界面拖慢
        # (完整日志另存于输出目录的 分类日志_*.txt)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(5000)
        self.log.setStyleSheet(
            f'QPlainTextEdit{{font-family:Consolas,"Microsoft YaHei UI";'
            f'font-size:12px;background:{CARD_BG};border:1px solid {BORDER};'
            f'border-radius:6px;padding:8px;}}')
        self.log.setMinimumHeight(140)
        self.log.setVisible(False)
        rl.addWidget(self.log, 1)
        main.addWidget(gb, 0)
        self._result_bar = gb

        # 按屏幕可用区域决定初始大小:笔记本(1366×768、125%/150% 缩放)
        # 上窗口不能比屏幕还高,否则底部的「开始」按钮会被挡住
        self.setMinimumSize(760, 520)
        w, h = 1080, 740
        try:
            scr = QApplication.primaryScreen()
            if scr is not None:
                g = scr.availableGeometry()
                w = min(w, int(g.width() * 0.95))
                h = min(h, int(g.height() * 0.92))
        except Exception:
            pass
        self.resize(max(w, 760), max(h, 520))

    @staticmethod
    def _scroll(page):
        """设置页放进可滚动区域:窗口/屏幕较小时内容滚动显示,
        而不是被压扁成几像素高、文字互相重叠。"""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page.setObjectName('tabPage')
        page.setStyleSheet('QWidget#tabPage{background:white;}')
        sa.setWidget(page)
        sa.viewport().setStyleSheet('background:white;')
        return sa

    @staticmethod
    def _scroll_plain(page):
        """右侧设置栏:内容多 / 窗口矮时竖向滚动,底色跟窗口一致。"""
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QFrame.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        sa.setWidget(page)
        return sa

    @staticmethod
    def _hint(text):
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f'color:{TEXT_SEC};font-size:12px;')
        return lbl

    def _build_input_card(self):
        self._gb_input = gb = QGroupBox('①  要归档的材料')
        gb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        lay = QVBoxLayout(gb); lay.setSpacing(6)
        self.lst_inputs = _DropList(self._add_input)
        self.lst_inputs.setMinimumHeight(70)
        self.lst_inputs.setAlternatingRowColors(True)
        self.lst_inputs.setSelectionMode(QListWidget.ExtendedSelection)
        self.lst_inputs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.lst_inputs.customContextMenuRequested.connect(self._input_menu)
        lay.addWidget(self.lst_inputs, 1)
        br = QHBoxLayout(); br.setSpacing(6)
        self.btn_add_archives = QPushButton('添加压缩包')
        self.btn_add_archives.clicked.connect(self._add_archives)
        br.addWidget(self.btn_add_archives)
        for txt, slot in [('添加文件夹', self._add_folder),
                          ('添加文件', self._add_files),
                          ('移除', self._rm_inputs),
                          ('清空', self._clr_inputs)]:
            b = QPushButton(txt); b.clicked.connect(slot)
            br.addWidget(b)
        br.addStretch()
        lay.addLayout(br)
        hr = QHBoxLayout(); hr.setSpacing(6)
        self.lbl_input_hint = self._hint('')
        hr.addWidget(self.lbl_input_hint, 1)
        # 密码本:按钮上直接显示用的是哪个文件
        self.btn_pw = QPushButton('🔑 密码本…')
        self.btn_pw.clicked.connect(self._pw_menu)
        hr.addWidget(self.btn_pw, 0, Qt.AlignTop)
        lay.addLayout(hr)
        self._setup_drop()
        return gb

    def _path_row(self, tag, color, edit, choose):
        r = QHBoxLayout(); r.setSpacing(6)
        lbl = QLabel(tag)
        lbl.setStyleSheet(f'background:{color};color:white;border-radius:4px;'
                          f'padding:4px 10px;font-weight:600;')
        r.addWidget(lbl)
        r.addWidget(edit, 1)
        b = QPushButton('更换…'); b.clicked.connect(choose)
        r.addWidget(b)
        return r

    def _build_output_card(self):
        gb = QGroupBox('②  结果放到')
        lay = QVBoxLayout(gb); lay.setSpacing(6)
        self._stack_out = QStackedWidget()

        # 按人归档:归档库(选好后一直记住,以后的新反馈都并进来)
        pw = QWidget(); pl = QVBoxLayout(pw); pl.setContentsMargins(0, 0, 0, 0); pl.setSpacing(4)
        self.txt_lib = QLineEdit()
        self.txt_lib.setPlaceholderText('未选时:放在最后添加的材料旁的「分类结果」')
        self.txt_lib.textEdited.connect(lambda t: self._set_manual('person', bool(t.strip())))
        self.txt_lib.textChanged.connect(lambda _t: self._lib_info_timer.start())
        pl.addLayout(self._path_row('归档库', PRIMARY, self.txt_lib,
                                    lambda: self._choose_out('person')))
        self.lbl_lib_info = self._hint('')
        pl.addWidget(self.lbl_lib_info)
        ar = QHBoxLayout(); ar.setSpacing(6)
        self.btn_open = QPushButton('📂 打开')
        self.btn_open.clicked.connect(self._open_out)
        ar.addWidget(self.btn_open)
        self.btn_sync = QPushButton('🔄 同步归档记录')
        self.btn_sync.clicked.connect(self._sync_library)
        ar.addWidget(self.btn_sync)
        self.btn_accounts = QToolButton()
        self.btn_accounts.setText('📊 生成账户汇总')
        self.btn_accounts.setPopupMode(QToolButton.MenuButtonPopup)
        self.btn_accounts.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.btn_accounts.clicked.connect(lambda: self._accounts_only())
        m = QMenu(self.btn_accounts)
        m.addAction('整个归档库', lambda: self._accounts_only())
        m.addAction('只做某个人…', lambda: self._accounts_pick(person=True))
        m.addAction('其他放流水的文件夹…', lambda: self._accounts_pick(person=False))
        self.btn_accounts.setMenu(m)
        ar.addWidget(self.btn_accounts)
        ar.addStretch()
        pl.addLayout(ar)
        self._stack_out.addWidget(pw)

        # 文件整理:整理结果目录(和归档库分开记)
        ow = QWidget(); ol = QVBoxLayout(ow); ol.setContentsMargins(0, 0, 0, 0); ol.setSpacing(4)
        self.txt_org = QLineEdit()
        self.txt_org.setPlaceholderText('未选时:放在所选文件夹下的「整理结果_日期」')
        self.txt_org.textEdited.connect(lambda t: self._set_manual('organize', bool(t.strip())))
        ol.addLayout(self._path_row('整理结果', '#EA580C', self.txt_org,
                                    lambda: self._choose_out('organize')))
        ol.addWidget(self._hint('只给文件整理用,和归档库分开记。'))
        orr = QHBoxLayout(); orr.setSpacing(6)
        self.btn_open_org = QPushButton('📂 打开')
        self.btn_open_org.clicked.connect(self._open_out)
        orr.addWidget(self.btn_open_org)
        self.btn_undo = QPushButton('↩ 撤销上次整理')
        self.btn_undo.clicked.connect(self._undo_last)
        orr.addWidget(self.btn_undo)
        self.btn_purge = QPushButton('🗑 一键清理')
        self.btn_purge.clicked.connect(self._purge_now)
        orr.addWidget(self.btn_purge)
        self.btn_hist = QPushButton('🔍 查文件去向')
        self.btn_hist.clicked.connect(self._search_history)
        orr.addWidget(self.btn_hist)
        orr.addStretch()
        ol.addLayout(orr)
        self._stack_out.addWidget(ow)

        lay.addWidget(self._stack_out)
        from PySide6.QtCore import QTimer
        self._lib_info_timer = QTimer(self)
        self._lib_info_timer.setSingleShot(True)
        self._lib_info_timer.setInterval(300)
        self._lib_info_timer.timeout.connect(self._refresh_lib_info)
        return gb

    def _build_person_settings(self):
        page = QWidget()
        lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)

        gb = QGroupBox('③  认人')
        gl = QVBoxLayout(gb); gl.setSpacing(4)
        r = QHBoxLayout()
        self.lbl_roster_sum = QLabel('')
        r.addWidget(self.lbl_roster_sum, 1)
        self.btn_roster = QPushButton('✏ 编辑名单…')
        self.btn_roster.clicked.connect(self._edit_roster)
        r.addWidget(self.btn_roster)
        gl.addLayout(r)
        self.lbl_roster_names = self._hint('')
        gl.addWidget(self.lbl_roster_names)
        self._ck = {}
        for key, label, default in [
                ('lib_roster', '归档库里已有的人自动认', True),
                ('auto_id', '自动识别身份证号', True),
                ('auto_company', '自动识别企业(名称 / 信用代码)', True),
                ('intelligent', '智能识别人名', True)]:
            cb = QCheckBox(label); cb.setChecked(default); self._ck[key] = cb
            gl.addWidget(cb)
        self._ck['lib_roster'].toggled.connect(lambda _v: self._refresh_roster_summary())
        lay.addWidget(gb)

        gb = QGroupBox('④  怎么放')
        gl = QVBoxLayout(gb); gl.setSpacing(4)
        r = QHBoxLayout(); r.setSpacing(6)
        r.addWidget(QLabel('每人文件夹里:'))
        self.cmb_unit = QComboBox()
        for mode, label in [('category', '按资料类型分(推荐)'),
                            ('subfolder', '按单位建子文件夹'),
                            ('prefix', '只在文件名前加【单位】'),
                            ('none', '不标注来源')]:
            self.cmb_unit.addItem(label, mode)
        self.cmb_unit.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_unit.setMinimumContentsLength(8)
        self.cmb_unit.currentIndexChanged.connect(lambda _i: self._sync_flow_ck())
        r.addWidget(self.cmb_unit, 1)
        gl.addLayout(r)
        self.ck_short = QCheckBox('精简文件名')
        self.ck_short.setChecked(True)
        gl.addWidget(self.ck_short)
        self._flow_ck = {}
        cb = QCheckBox('账户汇总表(合计余额)')
        cb.setChecked(True)
        self._flow_ck['account_summary'] = cb
        gl.addWidget(cb)
        cb = QCheckBox('流水整理版')
        cb.setChecked(True)
        self._flow_ck['tidy_flows'] = cb
        gl.addWidget(cb)
        self._ck.update(self._flow_ck)
        cb = QCheckBox('疑似空值单独放')
        cb.setChecked(True)
        self._ck['empty_detect'] = cb
        gl.addWidget(cb)
        cb = QCheckBox('先预览清单,确认后再执行')
        cb.setChecked(True)
        self._ck['preview'] = cb
        gl.addWidget(cb)
        r = QHBoxLayout(); r.setSpacing(6)
        self.btn_more = QPushButton('⚙ 更多设置…')
        self.btn_more.clicked.connect(lambda: self._dlg_more.exec())
        r.addWidget(self.btn_more)
        self.lbl_more = self._hint('')
        r.addWidget(self.lbl_more, 1)
        gl.addLayout(r)
        lay.addWidget(gb)
        lay.addStretch()
        return self._scroll_plain(page)

    def _build_organize_settings(self):
        page = QWidget()
        lay = QVBoxLayout(page); lay.setContentsMargins(0, 0, 0, 0); lay.setSpacing(8)
        gb = QGroupBox('③  怎么整理')
        gl = QVBoxLayout(gb); gl.setSpacing(5)
        gl.addWidget(self._hint('把下载目录 / 移动硬盘里的杂乱文件按类型 + 时间整理好,'
                                '同时挑出重复、旧版本和垃圾文件。全过程记入台账,可一键撤销。'))
        lr = QHBoxLayout(); lr.setSpacing(6)
        lr.addWidget(QLabel('目录布局:'))
        self.cmb_layout = QComboBox()
        self.cmb_layout.setEditable(True)
        for tpl, desc in LAYOUT_PRESETS:
            self.cmb_layout.addItem(f'{tpl}      — {desc}', tpl)
        self.cmb_layout.setCurrentIndex(1)
        self.cmb_layout.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_layout.setMinimumContentsLength(10)
        lr.addWidget(self.cmb_layout, 1)
        gl.addLayout(lr)
        gl.addWidget(self._hint('可用占位符: {类别} {年} {年月} {来源} {扩展名}(可直接编辑组合)'))
        opr = QHBoxLayout(); opr.setSpacing(12)
        self._rg_op = QButtonGroup(self)
        rb_mv = QRadioButton('移动(推荐)'); rb_mv.setChecked(True)
        self._rg_op.addButton(rb_mv, 0); opr.addWidget(rb_mv)
        rb_cp = QRadioButton('复制(保留原件)')
        self._rg_op.addButton(rb_cp, 1); opr.addWidget(rb_cp)
        opr.addStretch()
        gl.addLayout(opr)
        self._ckg = {}
        for key, label, default in [
                ('org_preview', '先预览清单,确认后再执行', True),
                ('org_smart_date', '按真实日期归类(拍摄时间 / 文件名日期)', True),
                ('org_keep_proj', '保护代码/工程目录(整体搬运不打散)', True),
                ('org_scan_only', '只体检不整理(只出报告,不动文件)', False)]:
            cb = QCheckBox(label); cb.setChecked(default); self._ckg[key] = cb
            gl.addWidget(cb)
        r = QHBoxLayout(); r.setSpacing(6)
        self.btn_more_org = QPushButton('⚙ 更多设置…')
        self.btn_more_org.clicked.connect(lambda: self._dlg_more_org.exec())
        r.addWidget(self.btn_more_org)
        r.addStretch()
        gl.addLayout(r)
        lay.addWidget(gb)
        lay.addStretch()
        return self._scroll_plain(page)

    # ---------- 对话框:名单 / 规则 / 更多设置 ----------

    def _dialog(self, title, w, h):
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        roomy_dialog(dlg, w, h)
        return dlg

    @staticmethod
    def _close_row(dlg, lay):
        box = QDialogButtonBox()
        b = box.addButton('完成', QDialogButtonBox.AcceptRole)
        b.setDefault(True)
        box.rejected.connect(dlg.accept)
        box.accepted.connect(dlg.accept)
        lay.addWidget(box)

    def _build_roster_dialog(self):
        dlg = self._dlg_roster = self._dialog('人员名单', 760, 560)
        tl = QVBoxLayout(dlg); tl.setSpacing(6)
        tl.addWidget(self._hint(
            '归档库里已有的人会自动认,这里只需补充:第一次出现、文件名只写姓名的人;'
            '曾用名 / 小名;同名不同人(写上证号区分)。'))
        rb = QHBoxLayout()
        for txt, slot in [('从 Excel 导入...', self._import_roster)]:
            b = QPushButton(txt); b.clicked.connect(slot)
            rb.addWidget(b)
        rb.addStretch()
        self.lbl_roster = QLabel('')
        self.lbl_roster.setStyleSheet(f'color:{TEXT_SEC};font-size:12px;')
        rb.addWidget(self.lbl_roster)
        tl.addLayout(rb)
        self.txt_roster = QPlainTextEdit()
        self.txt_roster.setPlaceholderText(
            '# 每行一个人:姓名,身份证号,曾用名…\n'
            '# 同一个人的姓名、证号、曾用名任一命中,文件都归入 TA 的文件夹。\n'
            '# 企业:公司名称,统一社会信用代码(名称或代码任一命中都归同一文件夹)\n'
            '# 示例(去掉开头的#即生效):\n张三\n李四,110101199003078515\n王五,王小五,老王\n'
            '某某科技有限公司,91110108MA01AB2C3T')
        self.txt_roster.textChanged.connect(self._refresh_roster_summary)
        tl.addWidget(self.txt_roster, 1)
        self._close_row(dlg, tl)

    def _build_rules_dialog(self):
        dlg = self._dlg_rules = self._dialog('高级分类规则', 760, 420)
        al = QVBoxLayout(dlg); al.setSpacing(6)
        al.addWidget(self._hint('名单 / 智能识别都没认出时,按规则从上到下依次匹配,'
                                '命中的放进「归入」写的文件夹。按人归档和文件整理都用。'))
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
            b = QPushButton(txt); b.clicked.connect(slot)
            rb2.addWidget(b)
        rb2.addStretch(); al.addLayout(rb2)
        self._close_row(dlg, al)
        dlg.finished.connect(lambda _r: self._refresh_rule_buttons())

    def _rules_button(self):
        b = QPushButton('高级分类规则…')
        b.clicked.connect(lambda: self._dlg_rules.exec())
        self._rule_btns = getattr(self, '_rule_btns', []) + [b]
        return b

    def _refresh_rule_buttons(self):
        n = len(self._get_rules())
        for b in getattr(self, '_rule_btns', []):
            b.setText(f'高级分类规则({n} 条)…' if n else '高级分类规则…')

    def _build_more_person_dialog(self):
        dlg = self._dlg_more = self._dialog('按人归档 — 更多设置', 820, 600)
        outer = QVBoxLayout(dlg)
        page = QWidget()
        ol = QVBoxLayout(page); ol.setSpacing(8); ol.setContentsMargins(12, 12, 12, 12)

        ol.addWidget(QLabel('<b>一个文件同时命中多人时</b>'))
        self._rb_multi = QButtonGroup(self)
        r1 = QRadioButton('命中多人→归入最匹配的(最长关键字优先)')
        r1.setChecked(True)
        self._rb_multi.addButton(r1, 0)
        ol.addWidget(r1)
        r2 = QRadioButton('命中多人→复制到每个文件夹')
        self._rb_multi.addButton(r2, 1)
        ol.addWidget(r2)
        ol.addWidget(self._sep())

        ol.addWidget(QLabel('<b>认人 / 处理</b>'))
        grid = QGridLayout(); grid.setSpacing(8)
        for idx, (key, label, default) in enumerate([
                ('content_match', '内容匹配:读 Excel/Word/PDF/文本查人', False),
                ('split_excel', 'Excel 按人拆分:多人表按行拆每人一份(原表保留)', False),
                ('dedup', '内容去重:同文件夹内文件只留一份', False),
                ('auto_pw_txt', '把输入文件夹里的 .txt 也当候选密码本(txt 仍照常分类)', False),
                ('delete_ok', '⚠ 成功后删除压缩包(移入回收站)', False)]):
            cb = QCheckBox(label); cb.setChecked(default); self._ck[key] = cb
            grid.addWidget(cb, idx // 2, idx % 2)
        ol.addLayout(grid)
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
        ol.addLayout(ir)
        er = QHBoxLayout(); er.setSpacing(6)
        er.addWidget(QLabel('疑似空值:小于'))
        self.spin_emptykb = QSpinBox()
        self.spin_emptykb.setRange(1, 1024)
        self.spin_emptykb.setValue(10)
        self.spin_emptykb.setSuffix(' KB')
        self.spin_emptykb.setFixedWidth(84)
        er.addWidget(self.spin_emptykb)
        er.addWidget(self._hint('且无实质内容的银行交易流水(只有表头、"查无账户"等)才放「疑似空值」;'
                                '"查无"回函是 Word(十几 KB)时可调到 30 左右'), 1)
        ol.addLayout(er)
        ol.addWidget(self._sep())

        ol.addWidget(QLabel('<b>密码本</b>(加密压缩包先用其中的密码自动尝试,不行再问你)'))
        pwf = QHBoxLayout(); pwf.setSpacing(6)
        self.txt_pwfile = QLineEdit()
        self.txt_pwfile.setPlaceholderText('可选:含解压密码的 txt(每行一个,或「文件名: 密码」)')
        self.txt_pwfile.textChanged.connect(lambda _t: self._refresh_pw_button())
        pwf.addWidget(self.txt_pwfile, 1)
        b = QPushButton('选择密码本'); b.clicked.connect(self._choose_pw)
        pwf.addWidget(b)
        ol.addLayout(pwf)
        ol.addWidget(self._sep())

        r = QHBoxLayout(); r.setSpacing(8)
        r.addWidget(self._rules_button())
        for txt, slot in [('保存模板...', self._save_tpl), ('加载模板...', self._load_tpl)]:
            b = QPushButton(txt); b.clicked.connect(slot)
            r.addWidget(b)
        r.addStretch()
        ol.addLayout(r)
        ol.addWidget(self._hint('模板 = 名单 + 全部选项,换个案子时一键切换。'))
        ol.addStretch()
        outer.addWidget(self._scroll(page), 1)
        self._close_row(dlg, outer)

    def _build_more_org_dialog(self):
        dlg = self._dlg_more_org = self._dialog('文件整理 — 更多设置', 820, 480)
        outer = QVBoxLayout(dlg)
        page = QWidget()
        gl = QVBoxLayout(page); gl.setSpacing(8); gl.setContentsMargins(12, 12, 12, 12)
        ggrid = QGridLayout(); ggrid.setSpacing(8)
        for idx, (key, label, default) in enumerate([
                ('org_dup', '挑出重复文件(内容相同的只留一份,其余归入「重复文件」)', True),
                ('org_versions', '挑出旧版本(报告(1)/副本/最终版,旧的归入「旧版本」)', True),
                ('org_junk', '挑出垃圾文件(Thumbs.db/临时文件/未完成下载/空文件)', True),
                ('org_empty', '整理后清理空文件夹', True),
                ('org_large', '把大文件单独归入「大文件」文件夹', False),
                ('org_extract', '顺带解开压缩包:把 zip/rar/7z 里的文件也一起整理', False),
                ('org_hidden', '包含隐藏文件(以 . 开头的文件)', False)]):
            cb = QCheckBox(label); cb.setChecked(default); self._ckg[key] = cb
            ggrid.addWidget(cb, idx, 0)
        gl.addLayout(ggrid)
        dr = QHBoxLayout(); dr.setSpacing(6)
        dr.addWidget(QLabel('查重最小体积:'))
        self.spin_mindup = QSpinBox()
        self.spin_mindup.setRange(0, 1024 * 1024)
        self.spin_mindup.setValue(10)
        self.spin_mindup.setSuffix(' KB')
        self.spin_mindup.setFixedWidth(110)
        dr.addWidget(self.spin_mindup)
        dr.addWidget(self._hint('(小于此体积的文件不查重 —— 空模板/配置文件内容相同是常态,'
                                '误判成重复反而添乱;填 0 则不限)'), 1)
        gl.addLayout(dr)
        sr = QHBoxLayout(); sr.setSpacing(6)
        sr.addWidget(QLabel('大文件阈值:'))
        self.spin_large = QSpinBox()
        self.spin_large.setRange(1, 100000)
        self.spin_large.setValue(100)
        self.spin_large.setSuffix(' MB')
        self.spin_large.setFixedWidth(110)
        sr.addWidget(self.spin_large)
        sr.addStretch()
        gl.addLayout(sr)
        r = QHBoxLayout(); r.addWidget(self._rules_button()); r.addStretch()
        gl.addLayout(r)
        gl.addStretch()
        outer.addWidget(self._scroll(page), 1)
        self._close_row(dlg, outer)

    def _sep(self):
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet(f'QFrame{{color:{BORDER};}}')
        f.setFixedHeight(1)
        return f

    # ---------- 名单摘要 / 归档库信息 / 密码本按钮 ----------

    def _library_people(self):
        out = self.txt_lib.text().strip()
        if not out or not os.path.isdir(out):
            return []
        try:
            from .pipeline import library_people
            return library_people(out)
        except Exception:
            return []

    def _refresh_lib_info(self):
        from .library import LEDGER_NAME
        out = self.txt_lib.text().strip()
        if not out:
            self.lbl_lib_info.setText('选好后一直记住,以后的新反馈都并进来。')
        elif not os.path.isdir(out):
            self.lbl_lib_info.setText('新的归档库(开始归档时自动创建)。')
        elif os.path.isfile(os.path.join(out, LEDGER_NAME)):
            n = len(self._library_people())
            self.lbl_lib_info.setText(f'已有归档库 · {n} 个人员/企业 · 新反馈会并进原文件夹,导入过的自动跳过')
        else:
            self.lbl_lib_info.setText('这个文件夹还不是归档库(开始归档后就是)。')
        self._refresh_roster_summary()

    def _refresh_roster_summary(self):
        if not hasattr(self, 'lbl_roster_sum'):
            return
        roster = Roster.from_text(self.txt_roster.toPlainText()) \
            if hasattr(self, 'txt_roster') else Roster([])
        lib = self._library_people() if self._ck.get('lib_roster') is not None \
            and self._ck['lib_roster'].isChecked() else []
        # 名单里已经写了的不重复算(和归档时一致)
        known = {p.name for p in roster.persons} | {x for p in roster.persons for x in p.aliases}
        ids = {i for p in roster.persons for i in p.ids}
        lib = [(n, c) for n, c in lib if n not in known and not (c and c in ids)]
        parts = []
        if lib:
            parts.append(f'归档库已有 <b>{len(lib)}</b> 人')
        parts.append(f'名单 <b>{len(roster)}</b> 人')
        self.lbl_roster_sum.setText(' + '.join(parts))
        names = [p.name + (f'({"、".join(p.aliases)})' if p.aliases else '')
                 for p in roster.persons]
        names += [n for n, _c in lib]
        if names:
            shown = '、'.join(names[:8]) + (f' …共 {len(names)} 个' if len(names) > 8 else '')
            self.lbl_roster_names.setText(shown)
        else:
            self.lbl_roster_names.setText('没有名单也能用:身份证号、企业、智能识别、文件夹名都会认人。')

    def _edit_roster(self):
        self._dlg_roster.exec()
        self._refresh_roster_summary()

    def _refresh_pw_button(self):
        pf = self.txt_pwfile.text().strip()
        self.btn_pw.setText(f'🔑 密码本:{os.path.basename(pf)}' if pf else '🔑 密码本…')

    def _pw_menu(self):
        m = QMenu(self)
        m.addAction('选择密码本…', self._choose_pw)
        if self.txt_pwfile.text().strip():
            m.addAction('不用密码本', lambda: self.txt_pwfile.setText(''))
        m.exec(self.btn_pw.mapToGlobal(self.btn_pw.rect().bottomLeft()))

    def _toggle_log(self, on):
        self.log.setVisible(on)
        self.btn_log.setText('详细日志 ▴' if on else '详细日志 ▾')

    # ---------- 输入操作 ----------

    def _add_input(self, path):
        path = (path or '').strip()
        if path:
            path = os.path.normpath(path)
        if not path or path in self.inputs:
            return
        if os.path.isdir(path):
            self.inputs.append(path)
            self.lst_inputs.addItem(f'📁 {path}')
        elif os.path.isfile(path):
            self.inputs.append(path)
            self.lst_inputs.addItem(f'📄 {path}')
        else:
            return
        self._auto_out()

    def _auto_out(self):
        """结果目录默认跟随「最后添加」的压缩包/文件所在目录(文件夹则放在该文件夹里);
        归档库、整理结果各自记:你选过(更换 / 手动输入)的那个不再自动变。"""
        if not self.inputs:
            return
        last = self.inputs[-1]
        base = last if os.path.isdir(last) else os.path.dirname(last)
        # 按人归档不带日期:同一收件目录里后续的反馈会自动合并到同一个结果目录
        if not self._manual['person']:
            self.txt_lib.setText(os.path.join(base, '分类结果'))
        if not self._manual['organize']:
            self.txt_org.setText(os.path.join(base, f'整理结果_{datetime.datetime.now():%Y%m%d}'))

    # 当前模式的结果目录(按人归档 = 归档库,文件整理 = 整理结果)
    @property
    def txt_out(self):
        return self.txt_org if self._mode() == 'organize' else self.txt_lib

    @property
    def _out_manual(self):
        return self._manual['organize' if self._mode() == 'organize' else 'person']

    @_out_manual.setter
    def _out_manual(self, v):
        self._manual['organize' if self._mode() == 'organize' else 'person'] = bool(v)

    def _set_manual(self, mode, on):
        self._manual[mode] = bool(on)
        if not on:                       # 清空 = 恢复跟随最后添加的材料
            self._auto_out()

    def _sync_library(self):
        """把你在结果目录里手动做的调整(挪动/改名/删除)写进归档记录,
        并刷新反馈核对表与文件名对照表。"""
        from .library import Library, LEDGER_NAME
        from .report import write_matrix_report, write_name_map
        out = self.txt_out.text().strip()
        if not out or not os.path.isfile(os.path.join(out, LEDGER_NAME)):
            QMessageBox.information(
                self, '提示', '输出目录里没有归档记录(归档记录.jsonl)。\n'
                              '请先选择按人归档的结果目录。')
            return
        self._begin_job()

        summ, tidy = self._flow_opts()

        def work():
            lib = Library(out, log=self._log)
            st = lib.sync(self._cancel)
            cum, cum_empty = lib.cumulative_matrix()
            write_matrix_report(out, cum, self._log, empty=cum_empty)
            write_name_map(out, lib.file_records(), self._log)
            # 挪动 / 删除过文件的人:账户汇总按现在的文件重做
            st['accounts'] = 0
            if (summ or tidy) and st.get('folders'):
                from . import accounts
                for f in sorted(st['folders']):
                    d = os.path.join(out, f)
                    if not os.path.isdir(os.path.join(d, accounts.FLOW_SUB)):
                        continue
                    try:
                        o, _r, _n = accounts.build(d, summary=summ, tidy=tidy, log=self._log)
                        st['accounts'] += bool(o)
                    except Exception as e:
                        self._log(f'  [提示] {f} 的账户汇总生成失败: {e}')
            self._ui_call(lambda: self._on_sync_done(st))

        threading.Thread(target=work, daemon=True).start()

    def _on_sync_done(self, st):
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        QMessageBox.information(
            self, '同步完成',
            f'已核对 {st["checked"]} 个已归档文件:\n'
            f'· 你挪动/改名过的 {st["moved"]} 个,已更新到新位置\n'
            f'· 已不在归档库里的 {st["gone"]} 个,记为已删除\n'
            f'· 你手动放进来、未登记的 {st["unregistered"]} 个,保持原样\n\n'
            f'反馈核对表、文件名对照表已同步更新。以后导入新反馈前也会自动同步。'
            + (f'\n涉及的 {st["accounts"]} 人的账户汇总表已按现在的文件重新生成。'
               if st.get('accounts') else ''))

    def _flow_opts(self):
        """(账户汇总表, 流水整理版) 两个勾选。"""
        return (self._flow_ck['account_summary'].isChecked(),
                self._flow_ck['tidy_flows'].isChecked())

    def _accounts_only(self, d=None):
        """对已经分好的文件夹补做账户汇总 / 流水整理版(不移动、不改名任何文件)。
        不指定时就是上面显示的归档库;别的文件夹从按钮右边的小箭头选。"""
        from . import accounts
        summ, tidy = self._flow_opts()
        if not (summ or tidy):
            QMessageBox.information(self, '提示', '「④ 怎么放」里的「账户汇总表」「流水整理版」都没勾选。')
            return
        if d is None:
            d = self.txt_lib.text().strip()
            if not d or not os.path.isdir(d):
                QMessageBox.information(
                    self, '提示', '上面的归档库还不存在。\n'
                                  '可以先「更换…」选已有的归档库,或点按钮右边的小箭头选别的文件夹。')
                return
        kind, items = accounts.plan_folder(d)
        if kind == 'library' and len(items) > 1:
            r = QMessageBox.question(
                self, '生成账户汇总',
                f'归档库:{d}\n共 {len(items)} 个人员/企业有「银行流水」。\n'
                f'将逐个读取他们的全部流水,生成账户汇总表'
                + ('和流水整理版' if tidy else '') + '(不移动、不改名任何文件)。\n\n'
                '文件多时需要一些时间,可随时取消。继续?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        elif kind == 'plain':
            r = QMessageBox.question(
                self, '生成账户汇总',
                f'「{os.path.basename(d)}」不是按人归档的文件夹,\n'
                '里面的全部流水会当作同一个对象汇总,汇总表放在这个文件夹里。继续?',
                QMessageBox.Yes | QMessageBox.No)
            if r != QMessageBox.Yes:
                return
        self._begin_job()

        def work():
            try:
                res = accounts.run_on_folder(d, summary=summ, tidy=tidy, log=self._log,
                                             progress=self._on_progress, cancel=self._cancel)
            except Exception as e:
                self._log(f'生成失败: {e}')
                res = {'summaries': [], 'tidied': 0, 'no_flow': [], 'failed': [d],
                       'cancelled': False, 'kind': kind}
            self._ui_call(lambda: self._on_accounts_done(d, res))

        threading.Thread(target=work, daemon=True).start()

    def _accounts_pick(self, person=True):
        """「只做某个人…」(从归档库里选)/「其他放流水的文件夹…」。"""
        lib = self.txt_lib.text().strip()
        start = lib if person and os.path.isdir(lib) else ''
        if not person:
            dirs = [x for x in self.inputs if os.path.isdir(x)]
            start = dirs[-1] if dirs else start
        d = QFileDialog.getExistingDirectory(
            self, '选择某人的文件夹' if person else '选择放着流水的文件夹', start)
        if d:
            self._accounts_only(os.path.normpath(d))

    def _on_accounts_done(self, d, res):
        self.btn_run.setEnabled(True)
        self._on_mode_changed()
        self.btn_cancel.setEnabled(False)
        self.progress.setVisible(False)
        self.lbl_prog.setVisible(False)
        if res.get('cancelled'):
            return
        msg = f'账户汇总表 {len(res["summaries"])} 份'
        if res['tidied']:
            msg += f',流水整理版新生成 {res["tidied"]} 份'
        msg += '。'
        if res['no_flow']:
            msg += f'\n{len(res["no_flow"])} 个没有认出流水(可能是 PDF / 扫描件 / 回函)。'
        if res['failed']:
            msg += f'\n{len(res["failed"])} 个生成失败,详见日志。'
        if len(res['summaries']) == 1:
            msg += f'\n\n{res["summaries"][0]}'
        elif res['summaries']:
            msg += f'\n\n在各人「银行流水」目录下,文件名以「账户汇总_」开头。'
        box = QMessageBox(self)
        box.setWindowTitle('生成完成')
        box.setText(msg)
        b_open = box.addButton('打开文件夹', QMessageBox.ActionRole)
        box.addButton(QMessageBox.Ok)
        box.exec()
        if box.clickedButton() is b_open:
            target = os.path.dirname(res['summaries'][0]) if len(res['summaries']) == 1 else d
            target = os.path.normpath(target)
            try:
                os.startfile(target)
            except Exception:
                QMessageBox.information(self, '提示', target)

    def _unit_mode(self):
        return self.cmb_unit.currentData() or 'category'

    def _set_unit_mode(self, mode):
        i = self.cmb_unit.findData(mode)
        self.cmb_unit.setCurrentIndex(i if i >= 0 else 0)

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
        """拖拽:拖到本窗口任意位置都可以(日志区、名单框、设置页、输出框……)。

        输入框、文本框等子控件默认会"吃掉"拖进来的文件(把路径当文字插入,
        或直接拒绝),所以在应用层装一个事件过滤器,凡是拖进本窗口的本地文件
        一律当作"添加输入"处理。"""
        self.setAcceptDrops(True)     # 列表本身见 _DropList
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def _set_drop_hint(self, on):
        lst = self.lst_inputs
        lst.setStyleSheet(
            f'QListWidget{{border:2px dashed {PRIMARY};background:#EFF6FF;}}' if on else '')

    def eventFilter(self, obj, ev):
        t = ev.type()
        if t in (QEvent.DragEnter, QEvent.DragMove, QEvent.Drop, QEvent.DragLeave) \
                and isinstance(obj, QWidget) and (obj.window() is self or
                                                  obj.window().parent() is self):
            if t == QEvent.DragLeave:
                self._set_drop_hint(False)
                return False
            md = ev.mimeData()
            if md is not None and md.hasUrls() and \
                    any(u.isLocalFile() for u in md.urls()):
                if t == QEvent.Drop:
                    self._set_drop_hint(False)
                    _drop_urls(ev, self._add_input)
                else:
                    self._set_drop_hint(True)
                    ev.acceptProposedAction()
                return True
        return super().eventFilter(obj, ev)

    def dragEnterEvent(self, e):
        _accept_urls(e)

    def dragMoveEvent(self, e):
        _accept_urls(e)

    def dropEvent(self, e):
        _drop_urls(e, self._add_input)

    def _choose_out(self, mode=None):
        mode = mode or self._mode()
        edit = self.txt_org if mode == 'organize' else self.txt_lib
        title = '选择整理结果放到哪里' if mode == 'organize' else \
            '选择归档库(已有的归档库,或新建一个空文件夹)'
        d = QFileDialog.getExistingDirectory(self, title, edit.text().strip())
        if d:
            edit.setText(os.path.normpath(d))
            self._manual[mode] = True

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
            QMessageBox.warning(self, '提示', '这个目录还不存在(开始运行后才会创建)。')

    def _open_path(self, path):
        try:
            os.startfile(os.path.normpath(path))
        except Exception:
            QMessageBox.information(self, '提示', path)

    def _open_unclassified(self):
        d = os.path.join(self._last_out or self.txt_lib.text().strip(), '未分类')
        if os.path.isdir(d):
            self._open_path(d)

    def _open_report(self):
        f = getattr(self, '_last_report', '')
        if f and os.path.isfile(f):
            self._open_path(f)

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

    def _sync_flow_ck(self):
        on = self._unit_mode() == 'category'
        for cb in self._flow_ck.values():
            cb.setEnabled(on)
            cb.setToolTip(cb.toolTip().split('\n(只在')[0] + ('' if on else
                          '\n(只在「按资料类型分」时有「银行流水」目录,现在不可用)'))

    # ---------- 配置 ----------

    def _gather_cfg(self):
        cfg = {
            'out_dir': self.txt_lib.text().strip(),
            'out_fixed': self._manual['person'],
            'org_out_dir': self.txt_org.text().strip(),
            'org_out_fixed': self._manual['organize'],
            'log_open': self.btn_log.isChecked(),
            'roster_text': self.txt_roster.toPlainText().rstrip('\n'),
            'multi_hit': 'first' if self._rb_multi.checkedId() == 0 else 'each',
            'unit_mode': self._unit_mode(),
            'short_names': self.ck_short.isChecked(),
            'layout_v46': True,
            'pw_txt_v502': True,
            'pw_file': self.txt_pwfile.text().strip(),
            'rules': [r.to_dict() for r in self._get_rules()],
            'intelligent_min_freq': self.spin_minfreq.value(),
            'intelligent_exclude': self.txt_iexclude.text().strip(),
            'empty_max_kb': self.spin_emptykb.value(),
            'work_mode': self._mode(),
            'org_layout': self.cmb_layout.currentText().split('—')[0].strip(),
            'org_op_mode': 'copy' if self._rg_op.checkedId() == 1 else 'move',
            'org_large_mb': self.spin_large.value(),
            'org_min_dup_kb': self.spin_mindup.value(),
        }
        for k, cb in self._ckg.items():
            cfg[k] = cb.isChecked()
        for ck_key, cb in self._ck.items():
            cfg[ck_key] = cb.isChecked()
        return cfg

    def _apply_cfg(self, cfg):
        try:
            mode = cfg.get('work_mode', 'person')
            if cfg.get('out_dir'):
                self.txt_lib.setText(cfg['out_dir'])
            org_dir = cfg.get('org_out_dir') or \
                (cfg.get('out_dir', '') if mode == 'organize' and 'org_out_dir' not in cfg else '')
            if org_dir:
                self.txt_org.setText(org_dir)
            from .library import LEDGER_NAME
            # 已经是归档库的目录:当作你选定的,添加新材料时不再跟着变
            self._manual['person'] = bool(cfg.get('out_fixed', False)) or bool(
                cfg.get('out_dir') and os.path.isfile(os.path.join(cfg['out_dir'], LEDGER_NAME)))
            self._manual['organize'] = bool(cfg.get('org_out_fixed', False))
            self.btn_log.setChecked(bool(cfg.get('log_open', False)))
            if cfg.get('roster_text'):
                self.txt_roster.setPlainText(cfg['roster_text'] + '\n')
            self._rb_multi.button(0).setChecked(cfg.get('multi_hit','first')=='first')
            self._rb_multi.button(1).setChecked(cfg.get('multi_hit','first')=='each')
            self._set_unit_mode(cfg.get('unit_mode', 'category'))
            self.ck_short.setChecked(bool(cfg.get('short_names', True)))
            self.txt_pwfile.setText(cfg.get('pw_file', ''))
            self.spin_minfreq.setValue(int(cfg.get('intelligent_min_freq', 10)))
            self.spin_emptykb.setValue(int(cfg.get('empty_max_kb', 10)))
            self.txt_iexclude.setText(str(cfg.get('intelligent_exclude', '')))
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
            self.spin_mindup.setValue(int(cfg.get('org_min_dup_kb', 10)))
            for k, cb in self._ckg.items():
                cb.setChecked(bool(cfg.get(k, cb.isChecked())))
            self._on_mode_changed()
            # 所有 checkbox 统一迭代设置
            for ck_key, cb in self._ck.items():
                cb.setChecked(bool(cfg.get(ck_key, cb.isChecked())))
            # 加载规则(先清掉现有的,加载模板时不叠加)
            for _ck2, _cmb, _val, _tgt in list(self._rule_rows):
                row_w = _ck2.parentWidget()
                self._rule_layout.removeWidget(row_w)
                row_w.deleteLater()
            self._rule_rows.clear()
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
            self._refresh_rule_buttons()
            self._sync_flow_ck()
            self._refresh_lib_info()
        except Exception:
            pass

    # ---------- 日志 / 进度 ----------

    def _log(self, msg):
        """可在任意线程调用:先进缓冲,由主线程每 100ms 批量刷到日志框。"""
        with self._log_lock:
            self._log_buf.append(str(msg))
        if in_main_thread():
            self._flush_ui()

    def _flush_ui(self):
        """(主线程)把缓冲的日志和最新进度刷到界面。"""
        with self._log_lock:
            buf, self._log_buf = self._log_buf, []
            prog, self._prog_state = self._prog_state, None
        if buf:
            if len(buf) > 5000:          # 一次涌入太多:只显示最后一段
                buf = [f'…(省略 {len(buf) - 5000} 行,完整内容见输出目录的日志文件)'] \
                    + buf[-5000:]
            self.log.appendPlainText('\n'.join(buf))
            sb = self.log.verticalScrollBar()
            sb.setValue(sb.maximum())
        if prog:
            self._apply_progress(*prog)

    _PHASES = {'extract': ('解压', 0, 0.5), 'classify': ('匹配', 0.5, 0.2),
               'scan': ('扫描', 0.0, 0.15), 'health': ('体检', 0.15, 0.45),
               'place': ('归档', 0.7, 0.3), 'accounts': ('账户汇总', 0.0, 1.0)}

    def _on_progress(self, phase, cur, total):
        """可在任意线程调用:只记下最新进度,由主线程定时刷新。"""
        with self._log_lock:
            self._prog_state = (phase, cur, total)

    def _apply_progress(self, phase, cur, total):
        name, base, span = self._PHASES.get(phase, (phase, 0, 1))
        pct = int((base + cur / total * span if total else base) * 100)
        self.progress.setVisible(True)
        self.progress.setValue(pct)
        self.lbl_prog.setVisible(True)
        self.lbl_prog.setText(f'{name} {cur}/{total}')

    # ---------- 后台交互 ----------

    def _ask_password(self, archive_name, attempt):
        """后台线程调用:在主线程弹密码框,阻塞等待用户输入。"""
        def _prompt():
            if attempt > 1:
                msg = f'密码错误,请重新输入。\n\n'
            else:
                msg = f'该压缩包有密码。\n\n'
            msg += f'「{archive_name}」需要解压密码:\n(取消→放入"暂未解压")'
            self._flush_ui()
            pwd, ok = QInputDialog.getText(
                self, '需要解压密码', msg,
                QLineEdit.Password, '')
            return pwd if ok else None

        return self._bridge.call_sync(_prompt)

    def _confirm_plan(self, plan):
        """后台线程调用:在主线程弹预览对话框,阻塞等待确认。"""
        def _show():
            self._flush_ui()
            dlg = QDialog(self)
            dlg.setWindowTitle(f'预览归档计划(共 {len(plan)} 个文件)')
            roomy_dialog(dlg, 1180, 640)
            lay = QVBoxLayout(dlg)
            tip = QLabel('双击"归入文件夹"一格可直接改;选中多行(Ctrl/Shift)后'
                         '点"改归到…"可批量改。改动只影响本次归档。')
            tip.setStyleSheet(f'color:{TEXT_SEC};')
            lay.addWidget(tip)
            tree = QTreeWidget()
            show_new = any(getattr(i, 'new_name', '') for i in plan)
            tree.setHeaderLabels(['文件名', '来源单位', '归入文件夹', '命中方式']
                                 + (['存为(精简后的文件名)'] if show_new else []))
            tree.setAlternatingRowColors(True)
            tree.setRootIsDecorated(False)
            tree.setSelectionMode(QTreeWidget.ExtendedSelection)
            tree.setEditTriggers(QTreeWidget.NoEditTriggers)
            rows = []       # (QTreeWidgetItem, PlanItem)
            for item in plan:
                cols = [item.fname, item.unit, item.display_target(),
                        getattr(item, 'preview_via', lambda: item.via)()]
                if show_new:
                    cols.append(getattr(item, 'new_name', '') or item.fname)
                it = QTreeWidgetItem(tree, cols)
                it.setToolTip(0, item.fname)    # 鼠标停留看完整文件名
                if show_new:
                    it.setToolTip(4, cols[4])
                if item.action == 'place':      # 拆分行不支持手改
                    it.setFlags(it.flags() | Qt.ItemIsEditable)
                rows.append((it, item))
            # 列宽按内容定,文字多时出现横向滚动条,不再被截成省略号
            fit_tree_columns(tree)

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
            dlg.deleteLater()           # 在主线程销毁,见 __init__ 中 gc 的说明
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
            return dlg._ok

        return self._bridge.call_sync(_show)

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
        self.btn_run.setText('▶  开始整理' if organize else '▶  开始归档')
        self.btn_run.setToolTip(TIPS['▶  开始整理' if organize else '▶  开始归档'])
        self._show_mode(organize)

    # (按钮底色, 边框, 标题色)
    _MODE_STYLE = {'person': ('#E3EEFC', '#2563EB', '#1D4ED8'),
                   'organize': ('#FFF1E3', '#EA580C', '#C2410C'),
                   'off': ('white', '#CBD5E1', '#334155')}

    def _style_mode_btn(self, b, labels, key):
        bg, bd, fg = self._MODE_STYLE[key]
        w = 2 if key != 'off' else 1
        b.setStyleSheet(f'QPushButton#modeBtn{{background:{bg};border:{w}px solid {bd};'
                        f'border-radius:8px;padding:0;min-height:50px;max-height:54px;}}'
                        f'QPushButton#modeBtn:hover{{border-color:{self._MODE_STYLE["person" if b is self.btn_mode_person else "organize"][1]};}}')
        t, sub = labels
        t.setStyleSheet(f'color:{fg};font-size:16px;font-weight:{700 if key != "off" else 500};')
        sub.setStyleSheet(f'color:{fg if key != "off" else TEXT_SEC};font-size:12px;')

    def _show_mode(self, organize):
        self.btn_mode_person.setChecked(not organize)
        self.btn_mode_org.setChecked(organize)
        self._style_mode_btn(self.btn_mode_person, self._mode_labels[0],
                             'off' if organize else 'person')
        self._style_mode_btn(self.btn_mode_org, self._mode_labels[1],
                             'organize' if organize else 'off')
        self._stack_out.setCurrentIndex(1 if organize else 0)
        self._stack_settings.setCurrentIndex(1 if organize else 0)
        self._gb_input.setTitle('①  要整理的文件夹' if organize else '①  要归档的材料')
        self.btn_add_archives.setVisible(not organize)
        self.btn_pw.setVisible(not organize)
        self.lbl_input_hint.setText(
            '💡 把文件夹拖到窗口任意位置即可;默认移动,全程记台账可一键撤销'
            if organize else
            '💡 压缩包、装压缩包的文件夹、已解压的乱放材料文件夹都行,拖到窗口任意位置即可')
        # 开始按钮:按人归档蓝色,文件整理橙色
        self.btn_run.setProperty('mode', 'organize' if organize else 'person')
        self.btn_run.style().unpolish(self.btn_run)
        self.btn_run.style().polish(self.btn_run)
        self.setWindowTitle(f'{APP_NAME} {VERSION} —— '
                            f'{"文件整理模式" if organize else "按人归档模式"}')

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
        self.lbl_result.setText('正在处理……(进度见上方;点「详细日志」看每一步)')
        self.btn_res_unclassified.setVisible(False)
        self.btn_res_report.setVisible(False)

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
        if len(roster) == 0 and not self._ck['auto_id'].isChecked() \
                and not self._ck['auto_company'].isChecked():
            QMessageBox.warning(self, '提示',
                                '请至少输入名单,或勾选"自动识别身份证号/企业"。')
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
            unit_mode=self._unit_mode(),
            pw_files=pw_files,
            rules=self._get_rules(),
            intelligent_min_freq=self.spin_minfreq.value(),
            empty_max_kb=self.spin_emptykb.value(),
            short_names=self.ck_short.isChecked(),
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
            self.lbl_result.setText('已取消。已处理的部分保留,详见日志。')
            return
        # 文件整理(含只体检 —— 只体检不写台账,不能只凭台账判断)
        if summary.get('journal') or summary.get('scan_only') \
                or 'health' in summary:
            self._show_result_org(summary)
            self._on_organize_done(summary)
            return
        self._show_result_person(summary)
        msg = f'分类完成!共处理 {summary.get("files", 0)} 个文件。'
        if summary.get('reimport_skipped'):
            msg += (f'\n其中新放入 {summary["files"] - summary["reimport_skipped"]} 个;'
                    f'{summary["reimport_skipped"]} 个之前已导入过,已跳过(原有文件和你的标记都不动)。')
        if summary.get('skipped_pw'):
            msg += f'\n{summary["skipped_pw"]} 个加密包未解压,见「暂未解压」。'
        if summary.get('failed'):
            msg += f'\n{summary["failed"]} 个包解压失败,见「解压失败」。'
        if summary.get('reports'):
            msg += '\n已生成反馈核对表。'
        if summary.get('account_summaries'):
            msg += f'\n已生成账户汇总表 {len(summary["account_summaries"])} 份。'
        if summary.get('backups'):
            msg += ('\n\n散放的原文件已按原来的文件夹结构备份在:\n'
                    + '\n'.join(summary['backups'])
                    + '\n确认新分的没问题后,可手动删除备份文件夹。')
        QMessageBox.information(self, '完成', msg)

    @staticmethod
    def _chip(n, label, color='#1D4ED8'):
        return (f'<span style="background:#F1F5F9;border-radius:4px;">&nbsp;'
                f'<b style="color:{color};font-size:15px;">{n}</b> {label}&nbsp;</span>')

    def _stamp(self):
        return f'<span style="color:{TEXT_SEC};">{datetime.datetime.now():%m-%d %H:%M}</span>&nbsp; '

    def _show_result_person(self, summary):
        self._last_out = self.txt_lib.text().strip()
        files = summary.get('files', 0)
        skipped = summary.get('reimport_skipped', 0)
        people = [k for k in (summary.get('stats') or {}) if k not in
                  ('未分类', '解压失败', '暂未解压', '原始反馈')]
        unc = (summary.get('stats') or {}).get('未分类', 0)
        chips = [self._chip(files, '个文件')]
        if skipped:
            chips.append(self._chip(skipped, '个导入过已跳过', TEXT_SEC))
        chips.append(self._chip(len(people), '人/企业'))
        if summary.get('empty'):
            chips.append(self._chip(summary['empty'], '疑似空值', TEXT_SEC))
        chips.append(self._chip(unc, '未分类', '#DC2626' if unc else '#16A34A'))
        if summary.get('account_summaries'):
            chips.append(self._chip(len(summary['account_summaries']), '份账户汇总'))
        bad = summary.get('failed', 0) + summary.get('skipped_pw', 0)
        if bad:
            chips.append(self._chip(bad, '个包未解开', '#DC2626'))
        if summary.get('backups'):
            chips.append('&nbsp;原文件已备份')
        self.lbl_result.setText(self._stamp() + ' '.join(chips))
        self.btn_res_unclassified.setVisible(bool(unc))
        reps = [r for r in summary.get('reports') or [] if r.endswith('.xlsx')]
        self._last_report = reps[0] if reps else ''
        self.btn_res_report.setVisible(bool(self._last_report))
        self._refresh_lib_info()

    def _show_result_org(self, summary):
        hs = summary.get('health', {})
        if summary.get('scan_only'):
            chips = [self._chip(summary.get('scanned', 0), '个文件已体检(未移动)')]
        else:
            chips = [self._chip(summary.get('files', 0), '个文件已整理')]
        for k, label in (('dup_extra', '重复'), ('junk', '垃圾/临时'), ('old_versions', '旧版本')):
            if hs.get(k):
                chips.append(self._chip(hs[k], label, '#C2410C'))
        if summary.get('failed'):
            chips.append(self._chip(summary['failed'], '失败', '#DC2626'))
        self.lbl_result.setText(self._stamp() + ' '.join(chips))
        self.btn_res_unclassified.setVisible(False)
        self.btn_res_report.setVisible(False)

    def _ui_call(self, fn):
        """可在任意线程调用:先刷完日志/进度,再在主线程执行 fn。"""
        def run():
            self._flush_ui()
            fn()
        self._bridge.post(run)

    def closeEvent(self, event):
        app = QApplication.instance()
        if app is not None:
            app.removeEventFilter(self)
        try:
            self._ui_timer.stop()
            self._gc_timer.stop()
        except Exception:
            pass
        gc.collect()
        gc.enable()
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
    apply_theme(app)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
