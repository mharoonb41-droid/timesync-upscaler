"""
preview_table.py - Interactive validation preview table with status badges,
manual asset re-linking, search filter, and duration summary.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from parser import TimestampEntry, format_seconds


class PreviewTableWidget(QWidget):
    """Interactive table displaying parsed timestamp script entries matched with media."""

    entry_updated = Signal(int)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.entries: List[TimestampEntry] = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(8)

        # Filter & stats toolbar
        toolbar = QHBoxLayout()
        toolbar.setSpacing(12)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 Filter by Prompt #, filename, or text...")
        self.search_input.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_input, stretch=2)

        self.stats_label = QLabel("Entries: 0 | Matched: 0 | Missing: 0 | Total Runtime: 00:00")
        self.stats_label.setObjectName("statLabel")
        toolbar.addWidget(self.stats_label, stretch=3, alignment=Qt.AlignRight)

        layout.addLayout(toolbar)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(7)
        self.table.setHorizontalHeaderLabels([
            "Prompt #", "Start Time", "End Time", "Duration", "Matched Media File", "Status", "Action"
        ])

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(4, QHeaderView.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(6, QHeaderView.ResizeToContents)

        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)

        layout.addWidget(self.table)

    def load_entries(self, entries: List[TimestampEntry]):
        self.entries = entries
        self.populate_table()

    def populate_table(self):
        self.table.setRowCount(0)
        total_duration = 0.0
        matched_count = 0
        missing_count = 0

        for row_idx, entry in enumerate(self.entries):
            self.table.insertRow(row_idx)

            # Col 0: Prompt #
            prompt_item = QTableWidgetItem(f"#{entry.prompt_id}")
            prompt_item.setTextAlignment(Qt.AlignCenter)
            prompt_item.setFlags(prompt_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 0, prompt_item)

            # Col 1: Start Time
            start_item = QTableWidgetItem(format_seconds(entry.start_seconds))
            start_item.setTextAlignment(Qt.AlignCenter)
            start_item.setFlags(start_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 1, start_item)

            # Col 2: End Time
            end_item = QTableWidgetItem(format_seconds(entry.end_seconds))
            end_item.setTextAlignment(Qt.AlignCenter)
            end_item.setFlags(end_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 2, end_item)

            # Col 3: Target Duration
            dur_item = QTableWidgetItem(f"{entry.duration:.2f}s")
            dur_item.setTextAlignment(Qt.AlignCenter)
            dur_item.setFlags(dur_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 3, dur_item)

            # Col 4: Matched Media File
            file_name = Path(entry.matched_file).name if entry.matched_file else "None"
            file_item = QTableWidgetItem(file_name)
            if entry.matched_file:
                file_item.setToolTip(f"{entry.matched_file}\n{entry.notes}")
            else:
                file_item.setToolTip("No file matched. Click 'Browse' to manually assign.")
            file_item.setFlags(file_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row_idx, 4, file_item)

            # Col 5: Status Badge
            status_container = QWidget()
            s_layout = QHBoxLayout(status_container)
            s_layout.setContentsMargins(4, 2, 4, 2)
            s_layout.setAlignment(Qt.AlignCenter)

            status_badge = QLabel()
            if entry.status == "MATCHED":
                status_badge.setText("● Matched")
                status_badge.setObjectName("badgeMatched")
                matched_count += 1
            else:
                status_badge.setText("✕ Missing")
                status_badge.setObjectName("badgeMissing")
                missing_count += 1

            s_layout.addWidget(status_badge)
            self.table.setCellWidget(row_idx, 5, status_container)

            # Col 6: Action Button (Browse/Replace)
            btn_container = QWidget()
            b_layout = QHBoxLayout(btn_container)
            b_layout.setContentsMargins(4, 2, 4, 2)
            b_layout.setAlignment(Qt.AlignCenter)

            browse_btn = QPushButton("Browse...")
            browse_btn.setToolTip("Assign or replace media file for this prompt")
            browse_btn.clicked.connect(lambda checked, idx=row_idx: self._browse_for_entry(idx))
            b_layout.addWidget(browse_btn)
            self.table.setCellWidget(row_idx, 6, btn_container)

            total_duration += entry.duration

        # Update stats
        runtime_str = format_seconds(total_duration)
        self.stats_label.setText(
            f"Entries: <b>{len(self.entries)}</b> | "
            f"Matched: <span style='color: #34d399;'><b>{matched_count}</b></span> | "
            f"Missing: <span style='color: #f87171;'><b>{missing_count}</b></span> | "
            f"Total Runtime: <b>{runtime_str}</b>"
        )

        self._apply_filter(self.search_input.text())

    def _browse_for_entry(self, row_idx: int):
        if row_idx < 0 or row_idx >= len(self.entries):
            return

        entry = self.entries[row_idx]
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select Media File for Prompt #{entry.prompt_id}",
            "",
            "All Supported Media (*.png *.jpg *.jpeg *.webp *.bmp *.mp4 *.mov *.gif);;Images (*.png *.jpg *.jpeg *.webp *.bmp);;Videos (*.mp4 *.mov *.gif)"
        )
        if file_path:
            entry.matched_file = file_path
            entry.status = "MATCHED"
            entry.notes = f"Manually assigned: {Path(file_path).name}"
            self.populate_table()
            self.entry_updated.emit(row_idx)

    def _apply_filter(self, filter_text: str):
        query = filter_text.strip().lower()
        for row in range(self.table.rowCount()):
            if not query:
                self.table.setRowHidden(row, False)
                continue

            prompt_text = self.table.item(row, 0).text().lower()
            file_text = self.table.item(row, 4).text().lower()
            entry_script_text = self.entries[row].text.lower() if row < len(self.entries) else ""

            match = (query in prompt_text) or (query in file_text) or (query in entry_script_text)
            self.table.setRowHidden(row, not match)
