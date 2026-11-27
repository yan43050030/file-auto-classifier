# -*- coding: utf-8 -*-
"""界面配色与 Qt 样式表(白底 + 蓝色强调 + 卡片式分区)。"""

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
RADIUS = '10px'

QSS = f"""
QMainWindow {{ background: {BG}; }}
QGroupBox {{
    background: {CARD_BG}; border: 1px solid {BORDER}; border-radius: {RADIUS};
    margin-top: 14px; padding: 12px; padding-top: 18px;
    font-size: 15px; font-weight: 600; color: {TEXT};
}}
QGroupBox::title {{
    subcontrol-origin: margin; left: 12px; padding: 0 4px;
    color: {TEXT};
}}
QPushButton {{
    border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 12px;
    min-height: 22px;
    background: {CARD_BG}; color: {TEXT}; font-size: 13px;
}}
QPushButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QToolButton {{
    border: 1px solid {BORDER}; border-radius: 7px; padding: 6px 12px; padding-right: 26px;
    min-height: 22px; background: {CARD_BG}; color: {TEXT}; font-size: 13px;
}}
QToolButton:hover {{ border-color: {PRIMARY}; color: {PRIMARY}; }}
QToolButton::menu-button {{ border: none; border-left: 1px solid {BORDER}; width: 20px; }}
QPushButton#btnRun {{
    background: {PRIMARY}; color: white; border: none; font-size: 16px;
    font-weight: 600; padding: 10px 32px;
}}
QPushButton#btnRun:hover {{ background: {PRIMARY_HOVER}; }}
QPushButton#btnRun[mode="organize"] {{ background: #EA580C; }}
QPushButton#btnRun[mode="organize"]:hover {{ background: #C2410C; }}
QPushButton#btnRun:disabled, QPushButton#btnRun[mode="organize"]:disabled {{ background: #94A3B8; }}
QToolTip {{
    background: #FFFFFF; color: {TEXT}; border: 1px solid {BORDER};
    padding: 6px 8px; font-size: 13px;
}}
QPushButton#btnCancel {{
    background: {DANGER}; color: white; border: none; font-size: 13px;
    padding: 8px 20px;
}}
QPushButton#btnCancel:hover {{ background: #DC2626; }}
QPushButton#btnCancel:disabled {{ background: #FCA5A5; }}
QLineEdit, QPlainTextEdit, QTextEdit {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 6px;
    background: white; color: {TEXT}; font-size: 13px;
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{
    border-color: {PRIMARY};
}}
QListWidget {{
    border: 1px dashed {BORDER}; border-radius: 6px; background: #F8FAFC;
    font-size: 13px; padding: 4px;
}}
QListWidget::item {{ padding: 4px 8px; }}
QListWidget::item:selected {{ background: {PRIMARY}; color: white; border-radius: 4px; }}
QComboBox {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 4px 8px;
    background: white; font-size: 13px;
}}
QCheckBox, QRadioButton {{ font-size: 13px; color: {TEXT}; spacing: 8px; padding: 2px 0; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; }}
QWidget {{ color: {TEXT}; }}
QLabel {{ color: {TEXT}; background: transparent; }}
QComboBox {{ color: {TEXT}; padding-right: 24px; }}
QComboBox::drop-down {{
    subcontrol-origin: padding; subcontrol-position: center right;
    width: 22px; border: none; background: transparent;
}}
QComboBox::down-arrow {{ image: url(__ARROW__); width: 10px; height: 6px; }}
QComboBox QAbstractItemView {{
    background: white; color: {TEXT}; selection-background-color: {PRIMARY};
    selection-color: white; border: 1px solid {BORDER};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    subcontrol-origin: border; width: 22px; border: none; background: transparent;
}}
QSpinBox::up-button {{ subcontrol-position: top right; }}
QSpinBox::down-button {{ subcontrol-position: bottom right; }}
QSpinBox::up-arrow {{ image: url(__ARROW_UP__); width: 10px; height: 6px; }}
QSpinBox::down-arrow {{ image: url(__ARROW__); width: 10px; height: 6px; }}
QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ background: #EFF6FF; }}
QSpinBox {{
    border: 1px solid {BORDER}; border-radius: 6px; padding: 3px 6px;
    padding-right: 24px; min-height: 26px;
    background: white; color: {TEXT}; font-size: 13px;
}}
QMenu {{ background: white; color: {TEXT}; border: 1px solid {BORDER}; }}
QMenu::item:selected {{ background: {PRIMARY}; color: white; }}
QDialog, QMessageBox, QInputDialog {{ background: {CARD_BG}; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QTabWidget::pane {{ border: 1px solid {BORDER}; border-radius: 6px; background: white; }}
QTabBar::tab {{
    padding: 9px 22px; border: 1px solid transparent; font-size: 14px;
    color: {TEXT_SEC};
}}
QTabBar::tab:selected {{ color: {PRIMARY}; border-bottom: 2px solid {PRIMARY}; font-weight: 600; }}
QTabBar::tab:hover {{ color: {PRIMARY}; }}
QProgressBar {{
    border: none; border-radius: 4px; background: {BORDER}; height: 6px;
    text-align: center; font-size: 11px;
}}
QProgressBar::chunk {{ background: {PRIMARY}; border-radius: 4px; }}
QSplitter::handle {{ background: {BORDER}; width: 1px; }}
QScrollArea {{ border: none; background: transparent; }}
QTreeWidget {{
    border: 1px solid {BORDER}; border-radius: 6px;
    font-size: 13px; alternate-background-color: #F8FAFC;
}}
QTreeWidget::item:selected {{ background: {PRIMARY}; color: white; }}
QTreeWidget::item {{ min-height: 26px; padding: 0 2px; }}
/* 表格里双击编辑时的输入框:不能套用普通输入框的大内边距,否则文字被挤成一条细线 */
QTreeView QLineEdit, QTableView QLineEdit, QListView QLineEdit {{
    padding: 0 4px; margin: 0; border: 1px solid {PRIMARY}; border-radius: 2px;
    font-size: 13px; background: white; color: {TEXT};
}}
QHeaderView::section {{
    background: #F1F5F9; border: none; border-bottom: 1px solid {BORDER};
    padding: 6px 10px; font-size: 13px; font-weight: 600;
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


def apply_theme(app):
    """固定使用本程序自己的浅色主题,不跟随 Windows 深色模式。

    Qt 6 在 Windows 深色模式下会给出深色调色板:样式表没逐一指定颜色的
    控件(标签、下拉框、数字框、滚动区域)就会变成"白底白字"或黑块,
    看起来像文字消失。这里统一用 Fusion 风格 + 显式浅色调色板。"""
    from PySide6.QtGui import QPalette, QColor, QFont
    from PySide6.QtCore import Qt
    try:
        app.styleHints().setColorScheme(Qt.ColorScheme.Light)   # Qt ≥ 6.8
    except Exception:
        pass
    app.setStyle('Fusion')
    pal = QPalette()
    roles = {
        QPalette.Window: BG, QPalette.WindowText: TEXT,
        QPalette.Base: '#FFFFFF', QPalette.AlternateBase: '#F8FAFC',
        QPalette.Text: TEXT, QPalette.PlaceholderText: '#94A3B8',
        QPalette.Button: CARD_BG, QPalette.ButtonText: TEXT,
        QPalette.ToolTipBase: '#FFFFFF', QPalette.ToolTipText: TEXT,
        QPalette.Highlight: PRIMARY, QPalette.HighlightedText: '#FFFFFF',
        QPalette.BrightText: '#FFFFFF', QPalette.Link: PRIMARY,
        QPalette.Light: '#FFFFFF', QPalette.Midlight: '#F1F5F9',
        QPalette.Mid: '#CBD5E1', QPalette.Dark: '#94A3B8',
        QPalette.Shadow: '#64748B',
    }
    for role, c in roles.items():
        pal.setColor(QPalette.All, role, QColor(c))
    for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
        pal.setColor(QPalette.Disabled, role, QColor('#94A3B8'))
    app.setPalette(pal)
    app.setStyleSheet(QSS.replace('__ARROW__', _arrow_file('down'))
                      .replace('__ARROW_UP__', _arrow_file('up')))
    app.setFont(QFont('Microsoft YaHei UI', 10))


def _arrow_file(direction='down'):
    """下拉/数字框箭头:运行时画成 PNG 写到临时目录供样式表引用。
    (PNG 是 Qt 内置格式,打包成单文件 exe 也不依赖额外插件)"""
    import os
    import tempfile
    from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
    from PySide6.QtCore import Qt, QPointF
    path = os.path.join(tempfile.gettempdir(), f'fac_arrow_{direction}.png')
    try:
        pm = QPixmap(20, 12)              # 2 倍尺寸,高分屏也清晰
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor(TEXT_SEC), 3)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        pts = [QPointF(2, 2), QPointF(10, 10), QPointF(18, 2)] if direction == 'down' \
            else [QPointF(2, 10), QPointF(10, 2), QPointF(18, 10)]
        p.drawPolyline(pts)
        p.end()
        if not pm.save(path, 'PNG'):
            return ''
    except Exception:
        return ''
    return path.replace('\\', '/')


def fit_tree_columns(tree, max_width=900, sample=400):
    """表格列宽按内容定(取前若干行估算),不再挤成省略号;总宽超出窗口时出现横向滚动条。

    列很多、行很多时不用 ResizeToContents(要扫全部行,十万行会卡);
    这里只看前 sample 行,够用且快。用户仍可拖动列宽。"""
    from PySide6.QtWidgets import QHeaderView, QAbstractItemView
    from PySide6.QtCore import Qt
    hdr = tree.header()
    hdr.setStretchLastSection(False)
    hdr.setSectionResizeMode(QHeaderView.Interactive)
    tree.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    tree.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    tree.setTextElideMode(Qt.ElideNone)
    fm = tree.fontMetrics()
    cols = tree.columnCount()
    widths = [fm.horizontalAdvance(tree.headerItem().text(c)) + 36 for c in range(cols)]
    n = min(tree.topLevelItemCount(), sample)
    for r in range(n):
        it = tree.topLevelItem(r)
        for c in range(cols):
            widths[c] = max(widths[c], fm.horizontalAdvance(it.text(c)) + 28)
    for c, w in enumerate(widths):
        hdr.resizeSection(c, min(w, max_width))


def roomy_dialog(dlg, w, h):
    """对话框:可最大化,初始大小不超过屏幕。"""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    dlg.setWindowFlags(dlg.windowFlags() | Qt.WindowMaximizeButtonHint
                       | Qt.WindowMinimizeButtonHint)
    try:
        g = QApplication.primaryScreen().availableGeometry()
        w, h = min(w, int(g.width() * 0.92)), min(h, int(g.height() * 0.85))
    except Exception:
        pass
    dlg.resize(w, h)
