"""
styles.py - Modern Dark Theme QSS Stylesheet and Color Palette for TimeSync-Upscaler.
Carefully tuned to prevent overlap, support high-DPI scaling, and provide fluid responsiveness.
"""

DARK_THEME_QSS = """
/* Global Application Style */
QWidget {
    background-color: #0f172a;
    color: #f1f5f9;
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
    selection-background-color: #0284c7;
    selection-color: #ffffff;
}

/* Main Window */
QMainWindow {
    background-color: #0b0f19;
}

/* Scroll Areas */
QScrollArea {
    background-color: transparent;
    border: none;
}
QScrollArea > QWidget > QWidget {
    background-color: transparent;
}

/* Scrollbars */
QScrollBar:vertical {
    border: none;
    background: #1e293b;
    width: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:vertical {
    background: #475569;
    min-height: 30px;
    border-radius: 4px;
}
QScrollBar::handle:vertical:hover {
    background: #64748b;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0px;
}
QScrollBar:horizontal {
    border: none;
    background: #1e293b;
    height: 8px;
    margin: 0px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal {
    background: #475569;
    min-width: 30px;
    border-radius: 4px;
}
QScrollBar::handle:horizontal:hover {
    background: #64748b;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0px;
}

/* Group Boxes / Cards */
QGroupBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px 10px 10px 10px;
    font-weight: 600;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: 2px;
    padding: 2px 8px;
    color: #38bdf8;
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 4px;
    font-size: 12px;
}

/* Tabs */
QTabWidget::pane {
    border: 1px solid #334155;
    background-color: #1e293b;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background-color: #0f172a;
    color: #94a3b8;
    border: 1px solid #334155;
    border-bottom: none;
    padding: 8px 16px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 4px;
    font-weight: 500;
    min-height: 20px;
}
QTabBar::tab:selected {
    background-color: #1e293b;
    color: #38bdf8;
    border-color: #38bdf8;
    border-bottom: 2px solid #1e293b;
    font-weight: 600;
}
QTabBar::tab:hover:!selected {
    background-color: #1e293b;
    color: #e2e8f0;
}

/* Buttons */
QPushButton {
    background-color: #334155;
    color: #f8fafc;
    border: 1px solid #475569;
    border-radius: 6px;
    padding: 6px 12px;
    font-weight: 500;
    min-height: 26px;
}
QPushButton:hover {
    background-color: #475569;
    border-color: #64748b;
}
QPushButton:pressed {
    background-color: #1e293b;
}
QPushButton:disabled {
    background-color: #1e293b;
    color: #475569;
    border-color: #334155;
}

/* Primary Accent Button */
QPushButton#primaryButton {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0284c7, stop:1 #2563eb);
    color: #ffffff;
    border: none;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 18px;
    border-radius: 6px;
    min-height: 32px;
}
QPushButton#primaryButton:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0ea5e9, stop:1 #3b82f6);
}
QPushButton#primaryButton:pressed {
    background: #0369a1;
}

/* Success Button */
QPushButton#successButton {
    background-color: #059669;
    color: #ffffff;
    border: 1px solid #10b981;
    font-weight: 600;
    font-size: 13px;
    padding: 8px 14px;
    border-radius: 6px;
    min-height: 30px;
}
QPushButton#successButton:hover {
    background-color: #10b981;
}

/* Danger / Cancel Button */
QPushButton#dangerButton {
    background-color: #991b1b;
    color: #fef2f2;
    border: 1px solid #b91c1c;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: 600;
    min-height: 32px;
}
QPushButton#dangerButton:hover {
    background-color: #dc2626;
}

/* LineEdits and TextEdits */
QLineEdit, QTextEdit, QPlainTextEdit {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f8fafc;
    selection-background-color: #0284c7;
    min-height: 22px;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #38bdf8;
}

/* Combo Boxes */
QComboBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
    color: #f8fafc;
    min-height: 24px;
}
QComboBox:hover {
    border-color: #475569;
}
QComboBox:focus {
    border-color: #38bdf8;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #334155;
    border-top-right-radius: 6px;
    border-bottom-right-radius: 6px;
}
QComboBox QAbstractItemView {
    background-color: #0f172a;
    border: 1px solid #334155;
    selection-background-color: #1e293b;
    selection-color: #38bdf8;
    outline: none;
    padding: 4px;
}

/* SpinBoxes */
QSpinBox {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 6px;
    padding: 5px 10px;
    color: #f8fafc;
    min-height: 24px;
}
QSpinBox:focus {
    border-color: #38bdf8;
}

/* Checkboxes */
QCheckBox {
    spacing: 8px;
    color: #cbd5e1;
    font-weight: 500;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid #475569;
    background-color: #0f172a;
}
QCheckBox::indicator:hover {
    border-color: #38bdf8;
}
QCheckBox::indicator:checked {
    background-color: #0284c7;
    border-color: #38bdf8;
}

/* Sliders */
QSlider::groove:horizontal {
    height: 6px;
    background: #334155;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #0284c7;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #38bdf8;
    border: 2px solid #0f172a;
    width: 14px;
    height: 14px;
    margin: -4px 0;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background: #7dd3fc;
}

/* Tables */
QTableWidget {
    background-color: #0f172a;
    border: 1px solid #334155;
    border-radius: 8px;
    gridline-color: #1e293b;
    color: #f1f5f9;
}
QTableWidget::item {
    padding: 4px 8px;
    border-bottom: 1px solid #1e293b;
}
QTableWidget::item:selected {
    background-color: #1e293b;
    color: #38bdf8;
}
QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 6px 8px;
    border: none;
    border-right: 1px solid #334155;
    border-bottom: 2px solid #334155;
    font-weight: 600;
}

/* Progress Bar */
QProgressBar {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 6px;
    text-align: center;
    color: #ffffff;
    font-weight: 600;
    min-height: 22px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #06b6d4, stop:0.5 #3b82f6, stop:1 #8b5cf6);
    border-radius: 5px;
}

/* Splitters */
QSplitter::handle {
    background-color: #1e293b;
}
QSplitter::handle:hover {
    background-color: #38bdf8;
}

/* Footer Card */
QFrame#footerCard {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 10px;
    padding: 10px;
}

/* Labels */
QLabel {
    color: #cbd5e1;
}
QLabel#headerTitle {
    font-size: 18px;
    font-weight: 700;
    color: #f8fafc;
}
QLabel#headerSubtitle {
    font-size: 12px;
    color: #94a3b8;
}
QLabel#badgeMatched {
    background-color: #064e3b;
    color: #34d399;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 11px;
}
QLabel#badgeMissing {
    background-color: #450a0a;
    color: #f87171;
    padding: 3px 8px;
    border-radius: 4px;
    font-weight: 600;
    font-size: 11px;
}
QLabel#statLabel {
    font-size: 12px;
    color: #94a3b8;
    font-weight: 500;
}
QLabel#destLabel {
    color: #38bdf8;
    font-weight: 600;
    font-size: 12px;
}
"""
