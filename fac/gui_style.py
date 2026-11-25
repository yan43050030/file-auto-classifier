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
