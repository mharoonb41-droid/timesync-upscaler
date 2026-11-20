"""
log_console.py - Real-time color-coded log viewer console for TimeSync-Upscaler.
"""

from __future__ import annotations
import time
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


class LogConsoleWidget(QWidget):
    """Real-time console displaying execution and multiprocessing logs with color formatting."""

    COLOR_MAP = {
        "INFO": "#38bdf8",     # Sky blue
        "SUCCESS": "#34d399",  # Emerald green
        "WARNING": "#fbbf24",  # Amber
        "ERROR": "#f87171",    # Rose red
    }

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Controls bar
        ctrl_bar = QHBoxLayout()
        ctrl_bar.setSpacing(10)

        self.auto_scroll_chk = QCheckBox("Auto-scroll")
        self.auto_scroll_chk.setChecked(True)
        ctrl_bar.addWidget(self.auto_scroll_chk)

        ctrl_bar.addStretch()

        self.copy_btn = QPushButton("Copy All")
        self.copy_btn.clicked.connect(self.copy_all)
        ctrl_bar.addWidget(self.copy_btn)

        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_log)
        ctrl_bar.addWidget(self.clear_btn)

        layout.addLayout(ctrl_bar)

        # Text display
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        font = QFont("Cascadia Code", 10)
        font.setStyleHint(QFont.Monospace)
        self.text_edit.setFont(font)
        self.text_edit.setStyleSheet(
            "QTextEdit { background-color: #0b0f19; border: 1px solid #1e293b; border-radius: 6px; padding: 8px; }"
        )
        layout.addWidget(self.text_edit)

    def log(self, message: str, level: str = "INFO"):
        color = self.COLOR_MAP.get(level.upper(), "#cbd5e1")
        timestamp = time.strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level.upper()}]"

        html_line = f"<span style='color: #64748b;'>{prefix}</span> <span style='color: {color};'>{message}</span><br>"
        self.text_edit.moveCursor(QTextCursor.End)
        self.text_edit.insertHtml(html_line)

        if self.auto_scroll_chk.isChecked():
            self.text_edit.moveCursor(QTextCursor.End)

    def clear_log(self):
        self.text_edit.clear()

    def copy_all(self):
        QApplication.clipboard().setText(self.text_edit.toPlainText())
