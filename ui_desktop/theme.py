"""Hoja de estilos QSS Dark Studio y paleta oficial para Kicksazos Studio v5.0."""

from __future__ import annotations

from typing import Dict

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

COLORS: Dict[str, str] = {
    "bg_root": "#0b0e14",
    "bg_panel": "#131822",
    "bg_card": "#171d29",
    "bg_input": "#0f141d",
    "bg_hover": "#1d2534",
    "border": "#232b3a",
    "border_focus": "#53fc18",
    "accent_kick": "#53fc18",
    "accent_kick_hover": "#6aff38",
    "accent_kick_text": "#071104",
    "accent_violet": "#8b5cf6",
    "accent_violet_hover": "#9f7aea",
    "accent_red": "#ff2a2a",
    "accent_red_hover": "#ff4d4d",
    "accent_amber": "#f59e0b",
    "accent_cyan": "#38bdf8",
    "text_primary": "#f1f5f9",
    "text_secondary": "#94a3b8",
    "text_muted": "#64748b",
}

DARK_STUDIO_QSS = f"""
/* ==================== Base & Tipografía ==================== */
QMainWindow, QDialog {{
    background-color: {COLORS['bg_root']};
    color: {COLORS['text_primary']};
    font-family: "Inter", "Noto Sans", "Segoe UI", "Ubuntu", sans-serif;
    font-size: 13px;
}}

QWidget {{
    color: {COLORS['text_primary']};
    font-family: "Inter", "Noto Sans", "Segoe UI", "Ubuntu", sans-serif;
    selection-background-color: {COLORS['accent_violet']};
    selection-color: #ffffff;
}}

QScrollArea, QStackedWidget {{
    background-color: transparent;
    border: none;
}}

QLabel#MutedLabel {{
    color: {COLORS['text_secondary']};
    font-size: 12px;
}}

QLabel#SectionTitle {{
    color: {COLORS['text_primary']};
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.2px;
}}

QLabel#PageTitle {{
    color: {COLORS['text_primary']};
    font-size: 20px;
    font-weight: 800;
}}

QLabel#PageSubtitle {{
    color: {COLORS['text_secondary']};
    font-size: 12px;
}}

/* ==================== Paneles & Tarjetas ==================== */
QFrame#PanelCard, QFrame#KpiCard, QFrame#WorkerCard, QFrame#VideoFrame {{
    background-color: {COLORS['bg_panel']};
    border: 1px solid {COLORS['border']};
    border-radius: 12px;
}}

QFrame#KpiCard {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

QFrame#WorkerCard {{
    background-color: #161d2b;
    border: 1px solid #2b3549;
    border-radius: 10px;
}}

QFrame#TopStatusBar {{
    background-color: {COLORS['bg_panel']};
    border-bottom: 1px solid {COLORS['border']};
}}

QFrame#SidebarFrame {{
    background-color: #0e121a;
    border-right: 1px solid {COLORS['border']};
}}

QFrame#StatusBanner {{
    background-color: {COLORS['bg_card']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
}}

/* ==================== Badges / Pills ==================== */
QLabel#StatusPill, QLabel#TopPillOk, QLabel#TopPillWarn, QLabel#TopPillViolet, QLabel#TopPillRed {{
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}}

QLabel#TopPillOk {{
    background-color: rgba(83, 252, 24, 0.14);
    color: {COLORS['accent_kick']};
    border: 1px solid rgba(83, 252, 24, 0.35);
}}

QLabel#TopPillWarn {{
    background-color: rgba(245, 158, 11, 0.15);
    color: {COLORS['accent_amber']};
    border: 1px solid rgba(245, 158, 11, 0.38);
}}

QLabel#TopPillViolet {{
    background-color: rgba(139, 92, 246, 0.16);
    color: #c4b5fd;
    border: 1px solid rgba(139, 92, 246, 0.42);
}}

QLabel#TopPillRed {{
    background-color: rgba(255, 42, 42, 0.15);
    color: #ff7a7a;
    border: 1px solid rgba(255, 42, 42, 0.4);
}}

/* ==================== Sidebar Navigation ==================== */
QListWidget#SidebarNav {{
    background-color: transparent;
    border: none;
    outline: none;
    padding: 6px;
}}

QListWidget#SidebarNav::item {{
    background-color: transparent;
    color: {COLORS['text_secondary']};
    border-radius: 10px;
    padding: 11px 12px;
    margin: 3px 0px;
    font-weight: 600;
    font-size: 13px;
}}

QListWidget#SidebarNav::item:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_primary']};
}}

QListWidget#SidebarNav::item:selected {{
    background-color: rgba(83, 252, 24, 0.14);
    color: {COLORS['accent_kick']};
    border: 1px solid rgba(83, 252, 24, 0.35);
}}

/* ==================== Botones ==================== */
QPushButton {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
    font-size: 12px;
}}

QPushButton:hover {{
    background-color: {COLORS['bg_hover']};
    border-color: #3a465c;
}}

QPushButton:pressed {{
    background-color: #101520;
}}

QPushButton:disabled {{
    background-color: #11151e;
    color: {COLORS['text_muted']};
    border-color: #1b2230;
}}

QPushButton#PrimaryKickButton {{
    background-color: {COLORS['accent_kick']};
    color: {COLORS['accent_kick_text']};
    border: 1px solid {COLORS['accent_kick']};
    font-weight: 800;
    font-size: 13px;
    padding: 10px 16px;
}}

QPushButton#PrimaryKickButton:hover {{
    background-color: {COLORS['accent_kick_hover']};
    border-color: {COLORS['accent_kick_hover']};
}}

QPushButton#PrimaryKickButton:disabled {{
    background-color: #1f3319;
    color: #5a7852;
    border-color: #263d1f;
}}

QPushButton#VioletButton {{
    background-color: {COLORS['accent_violet']};
    color: #ffffff;
    border: 1px solid {COLORS['accent_violet']};
    font-weight: 700;
}}

QPushButton#VioletButton:hover {{
    background-color: {COLORS['accent_violet_hover']};
    border-color: {COLORS['accent_violet_hover']};
}}

QPushButton#VioletButton:disabled {{
    background-color: #2b2347;
    color: #7c729e;
    border-color: #352b57;
}}

QPushButton#DangerButton {{
    background-color: rgba(255, 42, 42, 0.16);
    color: #ff6b6b;
    border: 1px solid rgba(255, 42, 42, 0.45);
    font-weight: 700;
}}

QPushButton#DangerButton:hover {{
    background-color: {COLORS['accent_red']};
    color: #ffffff;
    border-color: {COLORS['accent_red']};
}}

QPushButton#DangerButton:disabled {{
    background-color: #1c1519;
    color: #6b4347;
    border-color: #2b1d20;
}}

/* ==================== Inputs & Selectores ==================== */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox, QDateTimeEdit {{
    background-color: {COLORS['bg_input']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    padding: 7px 10px;
    font-size: 13px;
}}

QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover, QComboBox:hover, QSpinBox:hover, QDateTimeEdit:hover {{
    border-color: #39465e;
}}

QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus, QComboBox:focus, QSpinBox:focus, QDateTimeEdit:focus {{
    border: 1px solid {COLORS['accent_violet']};
    background-color: #111824;
}}

QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDateTimeEdit:disabled {{
    color: {COLORS['text_muted']};
    background-color: #0c1017;
}}

QComboBox::drop-down {{
    border: none;
    width: 24px;
}}

QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_panel']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border']};
    selection-background-color: {COLORS['accent_violet']};
    selection-color: #ffffff;
}}

QPlainTextEdit#LogConsole {{
    background-color: #080b10;
    color: #cbd5e1;
    border: 1px solid {COLORS['border']};
    border-radius: 8px;
    font-family: "JetBrains Mono", "Fira Code", "Noto Sans Mono", monospace;
    font-size: 11.5px;
    padding: 8px;
}}

/* ==================== Checkboxes ==================== */
QCheckBox {{
    spacing: 8px;
    color: {COLORS['text_primary']};
    font-size: 12.5px;
}}

QCheckBox::indicator {{
    width: 17px;
    height: 17px;
    border-radius: 5px;
    border: 1px solid #384459;
    background-color: {COLORS['bg_input']};
}}

QCheckBox::indicator:hover {{
    border-color: {COLORS['accent_kick']};
}}

QCheckBox::indicator:checked {{
    background-color: {COLORS['accent_kick']};
    border-color: {COLORS['accent_kick']};
}}

/* ==================== Barras de Progreso ==================== */
QProgressBar {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 7px;
    text-align: center;
    color: {COLORS['text_primary']};
    font-weight: 700;
    font-size: 11px;
    min-height: 18px;
}}

QProgressBar::chunk {{
    border-radius: 6px;
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 {COLORS['accent_violet']},
        stop: 1 {COLORS['accent_kick']}
    );
}}

QProgressBar#StageProgress::chunk {{
    border-radius: 6px;
    background-color: {COLORS['accent_violet']};
}}

QProgressBar#QuotaProgress::chunk {{
    border-radius: 6px;
    background-color: {COLORS['accent_kick']};
}}

/* ==================== Sliders (Reproductor) ==================== */
QSlider::groove:horizontal {{
    height: 6px;
    background: #1f2736;
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {COLORS['accent_kick']};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {COLORS['text_primary']};
    border: 2px solid {COLORS['accent_kick']};
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 8px;
}}

/* ==================== Tablas & Listas ==================== */
QTableWidget, QListWidget {{
    background-color: {COLORS['bg_input']};
    border: 1px solid {COLORS['border']};
    border-radius: 10px;
    gridline-color: #1c2432;
    outline: none;
}}

QTableWidget::item, QListWidget::item {{
    padding: 6px 8px;
    border-bottom: 1px solid #161d29;
}}

QTableWidget::item:selected, QListWidget::item:selected {{
    background-color: rgba(139, 92, 246, 0.24);
    color: #ffffff;
}}

QHeaderView::section {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 1px solid {COLORS['border']};
    border-right: 1px solid #1b2230;
    padding: 8px;
    font-weight: 700;
    font-size: 11.5px;
}}

/* ==================== Scrollbars Estilizadas ==================== */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
}}

QScrollBar::handle:vertical {{
    background: #2c364a;
    min-height: 28px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background: #43526e;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
    height: 0px;
}}

QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
}}

QScrollBar::handle:horizontal {{
    background: #2c364a;
    min-width: 28px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover {{
    background: #43526e;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
    width: 0px;
}}

/* ==================== Tooltips & Splitter ==================== */
QToolTip {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['accent_violet']};
    border-radius: 6px;
    padding: 5px 8px;
}}

QSplitter::handle {{
    background-color: {COLORS['border']};
}}

QSplitter::handle:hover {{
    background-color: {COLORS['accent_violet']};
}}
"""


def aplicar_tema_dark_studio(app: QApplication) -> None:
    """Aplica la paleta oscura y la hoja de estilos Dark Studio al QApplication."""
    if app is None:
        return
    try:
        app.setStyle("Fusion")
    except Exception:
        pass

    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(COLORS["bg_root"]))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(COLORS["text_primary"]))
    palette.setColor(QPalette.ColorRole.Base, QColor(COLORS["bg_input"]))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(COLORS["bg_panel"]))
    palette.setColor(QPalette.ColorRole.ToolTipBase, QColor(COLORS["bg_card"]))
    palette.setColor(QPalette.ColorRole.ToolTipText, QColor(COLORS["text_primary"]))
    palette.setColor(QPalette.ColorRole.Text, QColor(COLORS["text_primary"]))
    palette.setColor(QPalette.ColorRole.Button, QColor(COLORS["bg_card"]))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(COLORS["text_primary"]))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(COLORS["accent_violet"]))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    app.setPalette(palette)

    font = QFont("Inter", 10)
    app.setFont(font)
    app.setStyleSheet(DARK_STUDIO_QSS)
