"""Warm charcoal and clay, using native Qt painting and logical pixels."""
import os
from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer
from ..brand import ICONS

BG, SIDEBAR, SURFACE, FIELD = "#272622", "#201F1C", "#302E29", "#25241F"
INK, MUTED, FAINT = "#EFEAE1", "#B3ADA2", "#8F897E"
ACCENT, BORDER = "#D69778", "#454038"

GLYPHS = {
    "overview": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "connection": '<circle cx="6" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="m8.5 8.5 7 7M15 3h6v6M3 15v6h6"/>',
    "workspace": '<path d="M3 8V5h7l2 3h9v12H3z"/><path d="m8 12 3 3-3 3m6 0h3"/>',
    "downloads": '<path d="M12 3v12m-4-4 4 4 4-4M4 16v5h16v-5"/>',
    "logs": '<rect x="4" y="3" width="16" height="18" rx="2"/><path d="M8 8h8M8 12h8M8 16h5"/>',
    "settings": '<path d="M3 6h18M3 12h18M3 18h18m-13-15v6m9 0v6m-10 0v6"/>',
    "arrow": '<path d="M5 12h14m-6-6 6 6-6 6"/>',
    "external": '<path d="M14 3h7v7m0-7L10 14M10 3H3v18h18v-7"/>',
    "shield": '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/>',
}


def icon(name, color=MUTED, size=20):
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{GLYPHS[name]}</svg>'
    pixmap = QPixmap(size * 2, size * 2)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    QSvgRenderer(QByteArray(svg.encode())).render(painter)
    painter.end()
    pixmap.setDevicePixelRatio(2)
    return QIcon(pixmap)


def apply(app):
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI" if os.name == "nt" else "Noto Sans CJK SC", 10))
    palette = QPalette()
    for role, color in ((QPalette.ColorRole.Window, BG), (QPalette.ColorRole.WindowText, INK),
                        (QPalette.ColorRole.Base, FIELD), (QPalette.ColorRole.AlternateBase, SURFACE),
                        (QPalette.ColorRole.Text, INK), (QPalette.ColorRole.Button, SURFACE),
                        (QPalette.ColorRole.ButtonText, INK), (QPalette.ColorRole.Highlight, "#614638"),
                        (QPalette.ColorRole.HighlightedText, INK), (QPalette.ColorRole.PlaceholderText, FAINT)):
        palette.setColor(role, QColor(color))
    app.setPalette(palette)
    app.setStyleSheet(STYLES.replace("@CHECK_ICON@", (ICONS / "check.svg").as_posix().replace('"', '\\"')))


STYLES = """
QWidget { color: #EFEAE1; font-size: 14px; }
QMainWindow, QDialog { background: #272622; }
QFrame#Shell { background: #272622; border: 1px solid #484238; border-radius: 10px; }
QWidget#TitleBar { background: #272622; border-bottom: 1px solid #37342D; }
QWidget#Sidebar { background: #201F1C; border-right: 1px solid #37342D; }
QWidget#Page, QWidget#Viewport { background: #272622; }
QScrollArea { border: none; background: transparent; }
QFrame#Panel { background: #302E29; border: 1px solid #403C34; border-radius: 10px; }
QFrame#Hero { background: #353029; border: 1px solid #5A4639; border-radius: 12px; }
QFrame#Inset { background: #282621; border: 1px solid #403C34; border-radius: 8px; }
QLabel { background: transparent; border: none; }
QLabel#Heading { font-size: 27px; font-weight: 600; color: #F1EBE2; }
QLabel#HeroTitle { font-size: 23px; font-weight: 600; color: #F1EBE2; }
QLabel#SectionTitle { font-size: 16px; font-weight: 600; }
QLabel#Brand { font-family: "Segoe UI"; font-size: 19px; font-weight: 600; letter-spacing: 1px; }
QLabel#Metric { font-size: 19px; font-weight: 600; }
QLabel#Muted { color: #B3ADA2; font-size: 13px; }
QLabel#Caption { color: #8F897E; font-size: 12px; }
QLabel#Accent { color: #DDA78B; font-size: 12px; font-weight: 600; }
QLabel#Chip { color: #C4BAAC; background: #38352E; border: 1px solid #51493D; border-radius: 12px; padding: 4px 10px; font-size: 12px; }
QLabel#StepNumber { background: #3E372E; color: #DDA78B; border-radius: 14px; font-size: 12px; font-weight: 600; }
QPushButton { background: #3B3730; border: 1px solid #514A3F; border-radius: 7px; padding: 9px 15px; font-size: 13px; font-weight: 500; }
QPushButton:hover { background: #484137; border-color: #6C5C4A; }
QPushButton:pressed { background: #302B25; }
QPushButton:focus { border-color: #D69778; }
QPushButton:disabled { background: #302D27; color: #7F796E; border-color: #3D3830; }
QPushButton#Primary { background: #D69778; color: #241A15; border-color: #D69778; font-weight: 600; }
QPushButton#Primary:hover { background: #E1A88B; border-color: #E1A88B; }
QPushButton#Primary:pressed { background: #BF7F61; }
QPushButton#Primary:disabled { background: #514035; color: #968171; border-color: #514035; }
QPushButton#Ghost { background: transparent; border-color: transparent; color: #BCB3A5; }
QPushButton#Ghost:hover { background: #36322B; color: #EFEAE1; }
QPushButton#Nav { text-align: left; background: transparent; border: 1px solid transparent; padding: 12px 15px; color: #B3ADA2; }
QPushButton#Nav:hover { background: #2C2923; color: #EFEAE1; }
QPushButton#Nav:checked { background: #3A3029; border-color: #4B3A2E; color: #E0AC91; }
QPushButton#WindowControl { background: transparent; border: none; border-radius: 5px; padding: 2px; font-size: 16px; color: #B3ADA2; }
QPushButton#WindowControl:hover { background: #3D3830; color: #EFEAE1; }
QPushButton#WindowClose { background: transparent; border: none; border-radius: 5px; padding: 2px; font-size: 20px; color: #B3ADA2; }
QPushButton#WindowClose:hover { background: #914E41; color: #FFF2EB; }
QLineEdit, QComboBox, QPlainTextEdit { background: #25241F; border: 1px solid #4B453A; border-radius: 7px; padding: 10px 11px; color: #EFEAE1; selection-background-color: #614638; selection-color: #FFF1E7; }
QLineEdit:hover, QComboBox:hover { border-color: #6A5D4B; }
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus { border-color: #D69778; }
QLineEdit:disabled, QComboBox:disabled { color: #817A6F; border-color: #3C3830; }
QComboBox { padding-right: 30px; }
QComboBox::drop-down { width: 28px; border: none; }
QComboBox QAbstractItemView { background: #302C26; border: 1px solid #5B4D3D; selection-background-color: #5C4132; padding: 5px; }
QCheckBox { spacing: 9px; color: #C7BFB1; font-size: 13px; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #74634F; border-radius: 4px; background: #25241F; }
QCheckBox::indicator:checked { background: #D69778; border: 1px solid #D69778; image: url("@CHECK_ICON@"); }
QCheckBox::indicator:disabled { border-color: #4B453A; background: #302D27; }
QProgressBar { background: #211F1B; border: none; border-radius: 3px; height: 5px; max-height: 5px; color: transparent; }
QProgressBar::chunk { background: #CA8B6D; border-radius: 3px; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #544B3E; min-height: 35px; border-radius: 3px; }
QScrollBar::handle:vertical:hover { background: #8B715A; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QToolTip { color: #EFEAE1; background: #383129; border: 1px solid #6B5845; padding: 5px; }
"""
