"""
main_window.py - Main PySide6 Application Window for TimeSync-Upscaler.
Features a fluid, non-overlapping responsive layout, QScrollArea sidebar,
guaranteed single-file video export, and direct video playback shortcuts.
"""

from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QFileInfo, QPoint, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from exporter import ExportConfig, FFmpegEngine, RESOLUTION_PRESETS
from matcher import MediaFileInfo, SmartMatcher, scan_media_files
from parser import ScriptParser, TimestampEntry, format_seconds
from processor import RenderWorkerThread
from ui.log_console import LogConsoleWidget
from ui.preview_table import PreviewTableWidget
from ui.styles import DARK_THEME_QSS


class NoScrollComboBox(QComboBox):
    """QComboBox that ignores mouse wheel events to prevent accidental changes while scrolling."""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollSpinBox(QSpinBox):
    """QSpinBox that ignores mouse wheel events to prevent accidental changes while scrolling."""
    def wheelEvent(self, event):
        event.ignore()


class NoScrollSlider(QSlider):
    """QSlider that ignores mouse wheel events so mouse scrolling the page doesn't shift the slider."""
    def wheelEvent(self, event):
        event.ignore()


class MainWindow(QMainWindow):
    """Modern dark-themed PC desktop interface for Image-to-Video Synchronization and Upscaling."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("TimeSync-Upscaler • Automated Multiprocess Video Studio")
        self.resize(1360, 860)
        self.setMinimumSize(980, 680)
        self.setStyleSheet(DARK_THEME_QSS)
        self.setAcceptDrops(True)

        # State
        self.media_pool: List[MediaFileInfo] = []
        self.parsed_entries: List[TimestampEntry] = []
        self.audio_path: Optional[str] = None
        self.audio_duration: Optional[float] = None
        self.render_worker: Optional[RenderWorkerThread] = None
        self.last_exported_video: Optional[str] = None

        self._init_ui()
        self._detect_hardware_encoders()

    def _init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(14, 12, 14, 12)
        main_layout.setSpacing(10)

        # 1. Header Bar
        header = self._create_header_bar()
        main_layout.addLayout(header)

        # 2. Main Horizontal Splitter (Scrollable Left Sidebar / Right Workspace)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(5)

        # Left Controls Panel (wrapped in QScrollArea for responsive, non-overlapping layout)
        left_panel = self._create_left_panel()
        splitter.addWidget(left_panel)

        # Right Workspace (Tabs: Preview Table, Script Editor, Log Console)
        right_panel = self._create_right_panel()
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)
        main_layout.addWidget(splitter, stretch=1)

        # 3. Bottom Card: Single Output Destination, Progress, & Actions
        bottom_card = self._create_bottom_card()
        main_layout.addWidget(bottom_card)

    def _create_header_bar(self) -> QHBoxLayout:
        header = QHBoxLayout()
        header.setSpacing(12)

        title_layout = QVBoxLayout()
        title_layout.setSpacing(2)

        title_lbl = QLabel("TimeSync-Upscaler Studio")
        title_lbl.setObjectName("headerTitle")
        subtitle_lbl = QLabel("Automated Timestamp Synchronization • 2K/4K Lanczos Upscaler • Single-Video Output")
        subtitle_lbl.setObjectName("headerSubtitle")

        title_layout.addWidget(title_lbl)
        title_layout.addWidget(subtitle_lbl)
        header.addLayout(title_layout)

        header.addStretch()

        # Load Sample Demo Button
        load_sample_btn = QPushButton("📁 Load Sample Demo")
        load_sample_btn.setToolTip("Load sample script and generate placeholder images to test the pipeline")
        load_sample_btn.clicked.connect(self._load_sample_demo)
        header.addWidget(load_sample_btn)

        return header

    def _create_left_panel(self) -> QWidget:
        # Wrap left panel in a QScrollArea so that controls never overlap on smaller screens or high-DPI scaling
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QFrame.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        container = QWidget()
        container.setMinimumWidth(320)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(10)

        # 1. Media Assets Input
        media_group = QGroupBox("1. Media Assets (Images / Clips)")
        m_layout = QVBoxLayout(media_group)
        m_layout.setSpacing(6)

        self.media_folder_lbl = QLabel("No media folder selected (Drag & drop here)")
        self.media_folder_lbl.setWordWrap(True)
        self.media_folder_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        m_layout.addWidget(self.media_folder_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        choose_folder_btn = QPushButton("Select Folder...")
        choose_folder_btn.clicked.connect(self._browse_media_folder)
        btn_row.addWidget(choose_folder_btn)

        choose_files_btn = QPushButton("Select Files...")
        choose_files_btn.clicked.connect(self._browse_media_files)
        btn_row.addWidget(choose_files_btn)
        m_layout.addLayout(btn_row)

        self.media_count_lbl = QLabel("0 media items loaded")
        self.media_count_lbl.setStyleSheet("color: #38bdf8; font-weight: 600; font-size: 11px;")
        m_layout.addWidget(self.media_count_lbl)

        layout.addWidget(media_group)

        # 2. Timestamp Script Input
        script_group = QGroupBox("2. Timestamp Script")
        s_layout = QVBoxLayout(script_group)
        s_layout.setSpacing(6)

        self.script_file_lbl = QLabel("No script loaded (Select file or paste text)")
        self.script_file_lbl.setWordWrap(True)
        self.script_file_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        s_layout.addWidget(self.script_file_lbl)

        s_btn_row = QHBoxLayout()
        s_btn_row.setSpacing(6)
        load_script_btn = QPushButton("Load Script...")
        load_script_btn.setToolTip("Supports .txt, .srt, .csv")
        load_script_btn.clicked.connect(self._browse_script_file)
        s_btn_row.addWidget(load_script_btn)

        parse_match_btn = QPushButton("⚡ Parse & Match")
        parse_match_btn.clicked.connect(self._parse_and_match)
        s_btn_row.addWidget(parse_match_btn)
        s_layout.addLayout(s_btn_row)

        layout.addWidget(script_group)

        # 3. Optional Voiceover Audio
        audio_group = QGroupBox("3. Voiceover Audio (Attached to Final Video)")
        a_layout = QVBoxLayout(audio_group)
        a_layout.setSpacing(6)

        self.audio_lbl = QLabel("No audio attached (Video will be exported without audio)")
        self.audio_lbl.setWordWrap(True)
        self.audio_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        a_layout.addWidget(self.audio_lbl)

        a_btn_row = QHBoxLayout()
        a_btn_row.setSpacing(6)
        load_audio_btn = QPushButton("Attach Audio (.mp3/.wav)...")
        load_audio_btn.clicked.connect(self._browse_audio_file)
        a_btn_row.addWidget(load_audio_btn)

        clear_audio_btn = QPushButton("Clear")
        clear_audio_btn.clicked.connect(self._clear_audio)
        a_btn_row.addWidget(clear_audio_btn)
        a_layout.addLayout(a_btn_row)

        self.sync_last_chk = QCheckBox("Align final timestamp to audio duration")
        self.sync_last_chk.setChecked(True)
        a_layout.addWidget(self.sync_last_chk)

        layout.addWidget(audio_group)

        # 4. Export & Upscaling Settings
        settings_group = QGroupBox("4. Export & Upscaling Settings")
        st_layout = QGridLayout(settings_group)
        st_layout.setVerticalSpacing(8)
        st_layout.setHorizontalSpacing(8)

        # Processor & Hardware Acceleration Banner
        self.cpu_hardware_lbl = QLabel("🖥️ Processor: Detecting system CPU...")
        self.cpu_hardware_lbl.setWordWrap(True)
        self.cpu_hardware_lbl.setStyleSheet(
            "color: #38bdf8; font-size: 11px; font-weight: 600; padding: 6px 8px; "
            "background-color: #0b0f19; border: 1px solid #334155; border-radius: 6px;"
        )
        st_layout.addWidget(self.cpu_hardware_lbl, 0, 0, 1, 2)

        # Resolution Presets
        st_layout.addWidget(QLabel("Resolution:"), 1, 0)
        self.res_combo = NoScrollComboBox()
        for label in RESOLUTION_PRESETS.keys():
            self.res_combo.addItem(label)
        self.res_combo.setCurrentText("2K QHD (2560x1440) [16:9]")
        st_layout.addWidget(self.res_combo, 1, 1)

        # Frame Rate
        st_layout.addWidget(QLabel("Frame Rate:"), 2, 0)
        self.fps_combo = NoScrollComboBox()
        self.fps_combo.addItems(["24 fps", "30 fps", "60 fps"])
        self.fps_combo.setCurrentText("30 fps")
        st_layout.addWidget(self.fps_combo, 2, 1)

        # Scaling Mode
        st_layout.addWidget(QLabel("Scaling Mode:"), 3, 0)
        self.scaling_combo = NoScrollComboBox()
        self.scaling_combo.addItem("Fit (Letterbox/Pillars)", "fit")
        self.scaling_combo.addItem("Fill (Crop Canvas)", "fill")
        self.scaling_combo.addItem("Stretch", "stretch")
        st_layout.addWidget(self.scaling_combo, 3, 1)

        # Hardware Encoder
        st_layout.addWidget(QLabel("Processor / GPU:"), 4, 0)
        self.encoder_combo = NoScrollComboBox()
        self.encoder_combo.addItem("CPU libx264 (Software Default)", "libx264")
        st_layout.addWidget(self.encoder_combo, 4, 1)

        # Quality / CRF Slider
        st_layout.addWidget(QLabel("CRF Quality:"), 5, 0)
        crf_row = QHBoxLayout()
        self.crf_slider = NoScrollSlider(Qt.Horizontal)
        self.crf_slider.setRange(16, 28)
        self.crf_slider.setValue(18)
        self.crf_val_lbl = QLabel("18 (High)")
        self.crf_val_lbl.setStyleSheet("font-weight: 600; color: #38bdf8;")
        self.crf_slider.valueChanged.connect(lambda v: self.crf_val_lbl.setText(f"{v}"))
        crf_row.addWidget(self.crf_slider)
        crf_row.addWidget(self.crf_val_lbl)
        st_layout.addLayout(crf_row, 5, 1)

        # Multiprocessing Worker Pool
        st_layout.addWidget(QLabel("Worker Processes:"), 6, 0)
        self.workers_spin = NoScrollSpinBox()
        cpu_total = os.cpu_count() or 4
        self.workers_spin.setRange(1, cpu_total)
        self.workers_spin.setValue(max(1, cpu_total - 1))
        st_layout.addWidget(self.workers_spin, 6, 1)

        # Ken Burns Motion Effect
        self.ken_burns_chk = QCheckBox("Ken Burns Motion (Subtle zoom/pan for images)")
        self.ken_burns_chk.setChecked(False)
        st_layout.addWidget(self.ken_burns_chk, 7, 0, 1, 2)

        # Restore Defaults Button
        self.restore_defaults_btn = QPushButton("↺ Restore Default Settings")
        self.restore_defaults_btn.setToolTip("Reset all resolution, frame rate, encoder, CRF, and motion settings to default")
        self.restore_defaults_btn.clicked.connect(self._restore_default_settings)
        st_layout.addWidget(self.restore_defaults_btn, 8, 0, 1, 2)

        layout.addWidget(settings_group)
        layout.addStretch()

        scroll_area.setWidget(container)
        return scroll_area

    def _create_right_panel(self) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)

        self.tab_widget = QTabWidget()

        # Tab 1: Validation & Asset Matching Table
        self.preview_table = PreviewTableWidget()
        self.tab_widget.addTab(self.preview_table, "📋 Validation & Match Table")

        # Tab 2: Script Editor (Direct Edit & Paste)
        script_tab = QWidget()
        st_layout = QVBoxLayout(script_tab)
        st_layout.setContentsMargins(8, 8, 8, 8)
        st_layout.setSpacing(6)

        st_header = QHBoxLayout()
        st_header.addWidget(QLabel("<b>Timestamp Script Editor / Paste Input</b>"))
        st_header.addStretch()

        reparse_btn = QPushButton("⚡ Re-Parse from Text")
        reparse_btn.clicked.connect(self._parse_and_match)
        st_header.addWidget(reparse_btn)
        st_layout.addLayout(st_header)

        self.script_text_edit = QTextEdit()
        self.script_text_edit.setPlaceholderText(
            "Paste your timestamp script here. Example formats:\n\n"
            "[00:00] In July two thousand nineteen, a television prop buyer in Vancouver\n"
            "001,[00:04] walked into an Asian grocery store\n"
            "123,[00:06] looking for something that did not belong on Earth.\n\n"
            "Or standard range format:\n"
            "Prompt 1: 00:00 - 00:04 | Description\n"
            "Prompt 2: 00:04 - 00:08 | Description\n"
        )
        st_layout.addWidget(self.script_text_edit)
        self.tab_widget.addTab(script_tab, "✏️ Script Editor")

        # Tab 3: Realtime Output Console
        self.log_console = LogConsoleWidget()
        self.tab_widget.addTab(self.log_console, "💻 Realtime Console")

        layout.addWidget(self.tab_widget)
        return container

    def _create_bottom_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("footerCard")
        bottom_layout = QVBoxLayout(card)
        bottom_layout.setContentsMargins(12, 10, 12, 10)
        bottom_layout.setSpacing(8)

        # Row 1: Target Destination (1 Final Video Output)
        dest_row = QHBoxLayout()
        dest_row.setSpacing(8)
        dest_lbl = QLabel("<b>Output Destination (1 Final Video):</b>")
        dest_lbl.setObjectName("destLabel")
        dest_row.addWidget(dest_lbl)

        # Default to user's Videos folder or current working directory
        default_video_dir = Path.home() / "Videos"
        if not default_video_dir.exists():
            default_video_dir = Path.cwd()
        default_output = str(default_video_dir / "final_synchronized_video.mp4")

        self.output_path_edit = QLineEdit(default_output)
        self.output_path_edit.setToolTip("Path where the single, final assembled video will be saved")
        dest_row.addWidget(self.output_path_edit, stretch=1)

        browse_dest_btn = QPushButton("Change Destination...")
        browse_dest_btn.clicked.connect(self._browse_output_file)
        dest_row.addWidget(browse_dest_btn)
        bottom_layout.addLayout(dest_row)

        # Row 2: Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("Ready (%p%)")
        bottom_layout.addWidget(self.progress_bar)

        # Row 3: Responsive Controls Row
        action_row = QHBoxLayout()
        action_row.setSpacing(10)

        # Left status readout
        status_box = QVBoxLayout()
        status_box.setSpacing(2)
        self.status_lbl = QLabel("Status: Ready to Export")
        self.status_lbl.setStyleSheet("font-weight: 600; color: #38bdf8; font-size: 13px;")
        self.metrics_lbl = QLabel("Speed: -- fps | ETA: --:--")
        self.metrics_lbl.setStyleSheet("color: #94a3b8; font-size: 11px;")
        status_box.addWidget(self.status_lbl)
        status_box.addWidget(self.metrics_lbl)
        action_row.addLayout(status_box)

        action_row.addStretch()

        # Direct Play and Open Folder Buttons (Enabled upon completion)
        self.play_final_btn = QPushButton("▶ Play Final Video")
        self.play_final_btn.setObjectName("successButton")
        self.play_final_btn.setVisible(False)
        self.play_final_btn.clicked.connect(self._play_final_video)
        action_row.addWidget(self.play_final_btn)

        self.open_folder_btn = QPushButton("📂 Show in Folder")
        self.open_folder_btn.setVisible(False)
        self.open_folder_btn.clicked.connect(self._open_output_folder)
        action_row.addWidget(self.open_folder_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setObjectName("dangerButton")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_render)
        action_row.addWidget(self.cancel_btn)

        self.export_btn = QPushButton("🎬 Export 1 Final Combined Video")
        self.export_btn.setObjectName("primaryButton")
        self.export_btn.clicked.connect(self._start_export)
        action_row.addWidget(self.export_btn)

        bottom_layout.addLayout(action_row)
        return card

    # ---------------- Drag and Drop ----------------
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return

        file_paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        script_exts = {".txt", ".srt", ".csv"}
        audio_exts = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}

        for fp in file_paths:
            ext = Path(fp).suffix.lower()
            if os.path.isdir(fp):
                self._load_media_directory(fp)
            elif ext in script_exts:
                self._load_script_file(fp)
            elif ext in audio_exts:
                self._load_audio_file(fp)
            elif ext in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".mov"}:
                self._load_media_files([fp])

    # ---------------- Hardware & Media Handlers ----------------
    def _detect_hardware_encoders(self):
        try:
            cpu_info = FFmpegEngine.get_cpu_hardware_info()
            options = FFmpegEngine.get_encoder_options()

            # Update CPU banner in the UI
            arch_tag = "AMD Ryzen Engine" if cpu_info.is_amd else ("Intel Core Engine" if cpu_info.is_intel else "Multi-Core CPU")
            self.cpu_hardware_lbl.setText(
                f"🖥️ CPU: {cpu_info.cpu_name}\n"
                f"⚡ {cpu_info.threads} Cores/Threads | {arch_tag} | AMD AMF & Intel Ready"
            )

            self.encoder_combo.clear()
            rec_index = 0

            for i, opt in enumerate(options):
                status_suffix = ""
                if opt.is_verified:
                    status_suffix = " ✓ [Hardware Active]"
                elif opt.is_hardware:
                    status_suffix = " (Hardware Engine)"

                if opt.is_recommended:
                    status_suffix += " ★ [Recommended]"
                    rec_index = i

                display_text = f"{opt.label}{status_suffix}"
                self.encoder_combo.addItem(display_text, opt.key)

            self.encoder_combo.setCurrentIndex(rec_index)

            self.log_console.log(
                f"System Processor Detected: {cpu_info.cpu_name} ({cpu_info.threads} threads, {cpu_info.vendor} Architecture)",
                "INFO"
            )
            self.log_console.log(
                "Hardware Pipelines Available: AMD AMF (Radeon / Ryzen APU), Intel QuickSync, NVIDIA NVENC, and Multi-Core CPU.",
                "SUCCESS"
            )
        except Exception as e:
            self.log_console.log(f"Encoder detection notice: {e}", "WARNING")

    def _restore_default_settings(self):
        """Restores all video export and motion settings to recommended defaults."""
        self.res_combo.setCurrentText("2K QHD (2560x1440) [16:9]")
        self.fps_combo.setCurrentText("30 fps")
        self.scaling_combo.setCurrentIndex(0)  # Fit
        self.crf_slider.setValue(18)
        self.crf_val_lbl.setText("18 (High)")
        cpu_total = os.cpu_count() or 4
        self.workers_spin.setValue(max(1, cpu_total - 1))
        self.ken_burns_chk.setChecked(False)
        self.sync_last_chk.setChecked(True)

        # Restore encoder to recommended option
        options = FFmpegEngine.get_encoder_options()
        for i, opt in enumerate(options):
            if opt.is_recommended:
                self.encoder_combo.setCurrentIndex(i)
                break
        else:
            self.encoder_combo.setCurrentIndex(0)

        self.log_console.log("Settings successfully restored to default values.", "INFO")

    def _browse_media_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Media Assets Folder")
        if folder:
            self._load_media_directory(folder)

    def _load_media_directory(self, folder: str):
        self.media_pool = scan_media_files(folder)
        self.media_folder_lbl.setText(folder)
        self.media_count_lbl.setText(f"{len(self.media_pool)} supported media assets found")
        self.log_console.log(f"Loaded {len(self.media_pool)} media items from: {folder}", "INFO")

        suggested_out = os.path.join(folder, "final_synchronized_video.mp4")
        self.output_path_edit.setText(suggested_out)

        if self.parsed_entries:
            self._parse_and_match()

    def _browse_media_files(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Media Files",
            "",
            "Media Files (*.png *.jpg *.jpeg *.webp *.bmp *.gif *.mp4 *.mov)"
        )
        if files:
            self._load_media_files(files)

    def _load_media_files(self, files: List[str]):
        new_items = scan_media_files(files)
        existing_paths = {m.path for m in self.media_pool}
        added = [m for m in new_items if m.path not in existing_paths]
        self.media_pool.extend(added)

        self.media_folder_lbl.setText(f"{len(self.media_pool)} media assets loaded")
        self.media_count_lbl.setText(f"{len(self.media_pool)} media assets ready")
        self.log_console.log(f"Added {len(added)} media assets to pool (Total: {len(self.media_pool)})", "INFO")

        if self.parsed_entries:
            self._parse_and_match()

    def _browse_script_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Timestamp Script File",
            "",
            "Script Files (*.txt *.srt *.csv);;Text (*.txt);;SRT Subtitles (*.srt);;CSV (*.csv)"
        )
        if file_path:
            self._load_script_file(file_path)

    def _load_script_file(self, file_path: str):
        try:
            text = Path(file_path).read_text(encoding="utf-8", errors="replace")
            self.script_text_edit.setPlainText(text)
            self.script_file_lbl.setText(Path(file_path).name)
            self.log_console.log(f"Loaded script file: {file_path}", "INFO")
            self._parse_and_match()
        except Exception as e:
            QMessageBox.critical(self, "Error Loading Script", f"Could not read script file:\n{e}")

    def _browse_audio_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Voiceover Audio",
            "",
            "Audio Files (*.mp3 *.wav *.m4a *.aac *.flac *.ogg)"
        )
        if file_path:
            self._load_audio_file(file_path)

    def _load_audio_file(self, file_path: str):
        self.audio_path = file_path
        self.audio_duration = FFmpegEngine.get_media_duration(file_path)
        dur_str = format_seconds(self.audio_duration) if self.audio_duration else "Unknown duration"
        self.audio_lbl.setText(f"Attached: {Path(file_path).name} ({dur_str})")
        self.log_console.log(f"Attached voiceover audio: {file_path} ({dur_str})", "INFO")

        if self.parsed_entries:
            self._parse_and_match()

    def _clear_audio(self):
        self.audio_path = None
        self.audio_duration = None
        self.audio_lbl.setText("No audio attached (Video will be exported without audio)")
        self.log_console.log("Cleared attached audio track.", "INFO")

    def _browse_output_file(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Choose Final Video Destination",
            self.output_path_edit.text() or "final_synchronized_video.mp4",
            "MP4 Video (*.mp4)"
        )
        if file_path:
            self.output_path_edit.setText(file_path)

    # ---------------- Parse & Match ----------------
    def _parse_and_match(self):
        raw_text = self.script_text_edit.toPlainText().strip()
        if not raw_text:
            self.log_console.log("Script text is empty. Enter or load a script first.", "WARNING")
            return

        total_audio = self.audio_duration if self.sync_last_chk.isChecked() else None
        try:
            self.parsed_entries = ScriptParser.parse_text(
                raw_text,
                default_last_duration=4.0,
                total_audio_duration=total_audio
            )
            self.log_console.log(f"Parsed {len(self.parsed_entries)} timestamp entries from script.", "INFO")
        except Exception as e:
            self.log_console.log(f"Error parsing script: {e}", "ERROR")
            QMessageBox.critical(self, "Parse Error", f"Failed to parse script:\n{e}")
            return

        self.parsed_entries = SmartMatcher.match(
            entries=self.parsed_entries,
            media_pool=self.media_pool,
            enable_sequential_fallback=True
        )

        matched_count = sum(1 for e in self.parsed_entries if e.status == "MATCHED")
        missing_count = len(self.parsed_entries) - matched_count

        self.log_console.log(
            f"Matching completed: {matched_count} matched, {missing_count} missing.",
            "SUCCESS" if missing_count == 0 else "WARNING"
        )

        self.preview_table.load_entries(self.parsed_entries)
        self.tab_widget.setCurrentIndex(0)

    # ---------------- Export Orchestration ----------------
    def _start_export(self):
        if not self.parsed_entries:
            QMessageBox.warning(self, "No Script", "Please parse and match a timestamp script first.")
            return

        valid_entries = [e for e in self.parsed_entries if e.status == "MATCHED" and e.matched_file]
        if not valid_entries:
            QMessageBox.critical(
                self,
                "No Matched Assets",
                "None of the script entries have matched media files.\n"
                "Please add media files to the folder or manually assign them in the table."
            )
            return

        missing = len(self.parsed_entries) - len(valid_entries)
        if missing > 0:
            ret = QMessageBox.question(
                self,
                "Missing Assets Detected",
                f"{missing} entries do not have matching media files and will be skipped.\n"
                f"Do you want to proceed with the {len(valid_entries)} matched entries?",
                QMessageBox.Yes | QMessageBox.No
            )
            if ret != QMessageBox.Yes:
                return

        out_path = self.output_path_edit.text().strip()
        if not out_path:
            QMessageBox.warning(self, "Invalid Destination", "Please specify an output video file path.")
            return

        res_preset = self.res_combo.currentText()
        width, height = RESOLUTION_PRESETS.get(res_preset, (2560, 1440))
        fps_val = int(self.fps_combo.currentText().split()[0])
        encoder_val = self.encoder_combo.currentData() or "libx264"
        crf_val = self.crf_slider.value()
        scaling_mode_val = self.scaling_combo.currentData() or "fit"
        ken_burns_val = self.ken_burns_chk.isChecked()
        workers_count = self.workers_spin.value()

        config = ExportConfig(
            width=width,
            height=height,
            fps=fps_val,
            encoder=encoder_val,
            crf=crf_val,
            preset="medium",
            scaling_mode=scaling_mode_val,
            enable_ken_burns=ken_burns_val,
            audio_path=self.audio_path,
            num_workers=workers_count,
            output_path=out_path
        )

        # Switch to Realtime Console
        self.tab_widget.setCurrentIndex(2)

        # UI State updates
        self.export_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.play_final_btn.setVisible(False)
        self.open_folder_btn.setVisible(False)
        self.progress_bar.setValue(0)
        self.status_lbl.setText("Status: Processing frames across CPU cores...")

        # Launch background worker thread
        self.render_worker = RenderWorkerThread(entries=valid_entries, config=config, parent=self)
        self.render_worker.progress_updated.connect(self._on_progress_updated)
        self.render_worker.log_message.connect(self._on_log_message)
        self.render_worker.stage_changed.connect(self._on_stage_changed)
        self.render_worker.rendering_completed.connect(self._on_rendering_completed)
        self.render_worker.start()

    def _cancel_render(self):
        if self.render_worker and self.render_worker.isRunning():
            self.render_worker.cancel()
            self.cancel_btn.setEnabled(False)
            self.status_lbl.setText("Status: Cancelling...")

    def _on_progress_updated(self, current: int, total: int, status_msg: str, speed_fps: float, eta_str: str):
        pct = int((current / total) * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.progress_bar.setFormat(f"{pct}% ({current}/{total} Scenes)")
        self.status_lbl.setText(f"Status: {status_msg}")
        self.metrics_lbl.setText(f"Speed: {speed_fps:.1f} fps | ETA: {eta_str}")

    def _on_stage_changed(self, stage_name: str):
        self.status_lbl.setText(f"Status: {stage_name}")

    def _on_log_message(self, message: str, level: str):
        self.log_console.log(message, level)

    def _on_rendering_completed(self, success: bool, result_msg: str):
        self.export_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)

        if success:
            self.last_exported_video = result_msg
            self.progress_bar.setValue(100)
            self.progress_bar.setFormat("100% (Complete - 1 Video Saved)")
            self.status_lbl.setText("Status: ✅ 1 Final Video Exported Successfully!")

            # Show direct action buttons in footer
            self.play_final_btn.setVisible(True)
            self.open_folder_btn.setVisible(True)

            audio_note = f"Voiceover audio: {Path(self.audio_path).name}" if self.audio_path else "Audio: None"

            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("Export Complete")
            msg_box.setText(
                f"<b>Your entire synchronized video was successfully assembled into 1 complete file:</b><br><br>"
                f"<code>{result_msg}</code><br><br>"
                f"<span style='color: #94a3b8;'>{audio_note}</span>"
            )
            play_btn = msg_box.addButton("▶ Play Video", QMessageBox.ActionRole)
            folder_btn = msg_box.addButton("📂 Open Folder", QMessageBox.ActionRole)
            msg_box.addButton("Close", QMessageBox.RejectRole)

            msg_box.exec()
            clicked = msg_box.clickedButton()
            if clicked == play_btn:
                self._play_final_video()
            elif clicked == folder_btn:
                self._open_output_folder()
        else:
            self.status_lbl.setText("Status: Render Error / Aborted")
            QMessageBox.critical(self, "Rendering Error", f"Render pipeline failed:\n{result_msg}")

    def _play_final_video(self):
        if self.last_exported_video and os.path.isfile(self.last_exported_video):
            QDesktopServices.openUrl(QUrl.fromLocalFile(self.last_exported_video))

    def _open_output_folder(self):
        target = self.last_exported_video or self.output_path_edit.text()
        if target:
            folder = str(Path(target).parent.resolve())
            if os.path.isdir(folder):
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ---------------- Demo Sample Loader ----------------
    def _load_sample_demo(self):
        scratch_dir = Path(__file__).resolve().parent.parent / "sample_data"
        scratch_dir.mkdir(parents=True, exist_ok=True)

        sample_script = (
            "[00:00] In July two thousand nineteen, a television prop buyer in Vancouver\n"
            "001,[00:04] walked into an Asian grocery store\n"
            "123,[00:06] looking for something that did not belong on Earth.\n"
            "Prompt 4: [00:09 - 00:13] The buyer noticed an unusual jar labeled mysterious herbs.\n"
        )
        self.script_text_edit.setPlainText(sample_script)
        self.script_file_lbl.setText("Sample Script (Demo)")

        try:
            from PIL import Image, ImageDraw

            colors = [
                ("#1e3a8a", "Scene 0 - Prop Buyer in Vancouver", "0.png"),
                ("#065f46", "001 - Walked into Asian Grocery", "001.png"),
                ("#701a75", "123 - Looking for alien artifact", "123_scene.jpg"),
                ("#854d0e", "Prompt 4 - Mysterious Jar on Shelf", "prompt_04.png"),
            ]

            for bg_color, text, filename in colors:
                img_path = scratch_dir / filename
                if not img_path.exists():
                    img = Image.new("RGB", (1920, 1080), color=bg_color)
                    draw = ImageDraw.Draw(img)
                    draw.rectangle([40, 40, 1880, 1040], outline="#ffffff", width=4)
                    draw.text((100, 500), text, fill="#ffffff")
                    img.save(str(img_path))

            self._load_media_directory(str(scratch_dir))

            # Also check if test audio exists and attach it
            test_audio = scratch_dir / "test_audio.mp3"
            if test_audio.exists():
                self._load_audio_file(str(test_audio))

            self.log_console.log(f"Loaded sample demo assets from: {scratch_dir}", "SUCCESS")
        except Exception as e:
            self.log_console.log(f"Demo asset loader notice: {e}", "WARNING")

        self._parse_and_match()
