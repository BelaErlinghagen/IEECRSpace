import os
import platform
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Fix "Fontconfig error: Cannot load default config file" in pixi/conda environments.
# Qt reads FONTCONFIG_FILE before any Python code runs, so we must set it here,
# before the first PyQt6 import, using sys.prefix which points to the active env root.
_fc_conf = Path(sys.prefix) / "etc" / "fonts" / "fonts.conf"
if _fc_conf.exists() and "FONTCONFIG_FILE" not in os.environ:
    os.environ["FONTCONFIG_FILE"] = str(_fc_conf)

from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal, QStringListModel
from PyQt6.QtGui import QFontDatabase, QPixmap, QImage
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget,
    QVBoxLayout, QHBoxLayout, QFormLayout, QSplitter,
    QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QComboBox, QFileDialog, QStatusBar,
    QListWidget, QListWidgetItem, QGroupBox, QCheckBox,
    QMessageBox, QCompleter, QScrollArea, QSpinBox,
    QTreeWidget, QTreeWidgetItem, QRadioButton, QButtonGroup,
)

import rspace


# ── Logo helper ──────────────────────────────────────────────────────────────

_LOGO_WHITE_THRESHOLD = 230  # pixels at/above this in all channels become transparent


def _load_logo_pixmap(path, height):
    """Load the logo scaled to `height` px tall, with its near-white background
    made transparent so it blends into the app background. Returns a QPixmap or
    None if the file can't be read."""
    src = QPixmap(str(path))
    if src.isNull():
        return None
    scaled = src.scaledToHeight(height, Qt.TransformationMode.SmoothTransformation)
    img = scaled.toImage().convertToFormat(QImage.Format.Format_ARGB32)
    t = _LOGO_WHITE_THRESHOLD
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            if c.red() >= t and c.green() >= t and c.blue() >= t:
                c.setAlpha(0)
                img.setPixelColor(x, y, c)
    return QPixmap.fromImage(img)


# ── Background worker ──────────────────────────────────────────────────────────

class Worker(QThread):
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs

    def run(self):
        try:
            self.finished.emit(self._fn(*self._args, **self._kwargs))
        except Exception as exc:
            self.error.emit(str(exc))


# ── Folder tree selector ────────────────────────────────────────────────────────

# Custom roles for storing data on tree items.
_ROLE_ID = Qt.ItemDataRole.UserRole          # folder id (or None for the workspace item)
_ROLE_PATH = Qt.ItemDataRole.UserRole + 1    # full path string


class FolderTree(QWidget):
    """An expandable tree for selecting an RSpace folder/notebook.

    Shows the real folder hierarchy (rebuilt from the flat list returned by
    ``rspace.list_all_folders``) and a label with the full path of the current
    selection. Use ``populate`` to fill it and ``current_folder_id`` to read the
    selection.
    """

    selection_changed = pyqtSignal()

    def __init__(self, include_workspace=False):
        super().__init__()
        self._include_workspace = include_workspace

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumHeight(160)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._tree)

        self._path_label = QLabel("Selected: (none)")
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        QTreeWidgetItem(self._tree, ["Loading…"])

    def populate(self, nodes):
        """Fill the tree from the nested structure returned by ``rspace.create_tree``.

        Only folders and notebooks are shown (documents would overcrowd it); the full
        depth of the hierarchy is represented.
        """
        self._tree.clear()

        if self._include_workspace:
            ws = QTreeWidgetItem(self._tree, ["— Entire Workspace —"])
            ws.setData(0, _ROLE_ID, None)
            ws.setData(0, _ROLE_PATH, "Entire Workspace")

        def add(parent, node, prefix_path):
            if node.get("type") not in ("folder", "notebook"):
                return  # skip documents and other items
            full = f"{prefix_path}/{node['name']}" if prefix_path else node["name"]
            text = f"{node['name']}  [NB]" if node.get("notebook") else node["name"]
            item = QTreeWidgetItem(parent, [text])
            item.setData(0, _ROLE_ID, node["id"])
            item.setData(0, _ROLE_PATH, full)
            item.setToolTip(0, full)
            for child in node.get("children", []):
                add(item, child, full)

        for node in nodes:
            add(self._tree, node, "")

        self._tree.expandToDepth(1)  # show the first couple of levels; deeper is expandable
        if self._include_workspace:
            self._tree.setCurrentItem(self._tree.topLevelItem(0))

    def current_folder_id(self):
        item = self._tree.currentItem()
        if item is None:
            return None
        return item.data(0, _ROLE_ID)

    def select_by_id(self, folder_id):
        """Select the tree item whose folder id equals `folder_id` (no-op if absent)."""
        if folder_id is None:
            return

        def find(item):
            if item.data(0, _ROLE_ID) == folder_id:
                return item
            for i in range(item.childCount()):
                hit = find(item.child(i))
                if hit:
                    return hit
            return None

        for i in range(self._tree.topLevelItemCount()):
            hit = find(self._tree.topLevelItem(i))
            if hit:
                self._tree.setCurrentItem(hit)
                self._tree.scrollToItem(hit)
                return

    def _on_selection_changed(self):
        item = self._tree.currentItem()
        if item is None:
            self._path_label.setText("Selected: (none)")
        else:
            full = item.data(0, _ROLE_PATH) or item.text(0)
            self._path_label.setText(f"Selected: {full}")
        self.selection_changed.emit()


# ── Main window ────────────────────────────────────────────────────────────────

class RSpaceGUI(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("RSpace Interface")
        self.resize(860, 700)

        self._folders = []
        self._folder_combos = []
        self._folder_trees = []
        self._workers = []
        self._rename_tags_loaded = False   # lazy-load guard for Rename tab

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(8, 8, 8, 8)
        root_layout.setSpacing(6)

        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._tabs.addTab(self._build_create_tab(),     "Create Entry")
        self._tabs.addTab(self._build_rename_tab(),     "Rename Files")
        self._tabs.addTab(self._build_metadata_tab(),   "Fetch Metadata")
        self._tabs.addTab(self._build_csv_tab(),        "Summary CSV")
        self._tabs.addTab(self._build_filepaths_tab(),  "File Paths")
        self._tabs.addTab(self._build_overview_tab(),   "Project Overview")
        self._tabs.addTab(self._build_results_tab(),    "Results Entry")
        self._settings_tab_index = self._tabs.addTab(self._build_settings_tab(), "Settings")

        # Output panel lives below the tabs in a draggable splitter, so it never
        # steals a fixed slice of the window when empty (and can be resized).
        output_container = QWidget()
        out_layout = QVBoxLayout(output_container)
        out_layout.setContentsMargins(0, 0, 0, 0)
        out_layout.setSpacing(4)

        output_label = QLabel("Output")
        _lbl_font = output_label.font()
        _lbl_font.setBold(True)
        output_label.setFont(_lbl_font)
        out_layout.addWidget(output_label)

        self._output = QPlainTextEdit()
        self._output.setReadOnly(True)
        self._output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        out_layout.addWidget(self._output)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._tabs)
        splitter.addWidget(output_container)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([520, 180])
        root_layout.addWidget(splitter)

        # IEECR logo, bottom-right, with its white background keyed out so it
        # blends into the window. Sits just above the (thin) status bar.
        logo_path = Path(__file__).resolve().parent / "IEECRlogo.png"
        logo_pix = _load_logo_pixmap(logo_path, 56) if logo_path.exists() else None
        if logo_pix is not None:
            footer = QHBoxLayout()
            footer.setContentsMargins(0, 2, 4, 0)
            footer.addStretch()
            logo = QLabel()
            logo.setPixmap(logo_pix)
            footer.addWidget(logo)
            root_layout.addLayout(footer)

        self._status = QStatusBar()
        self.setStatusBar(self._status)

        if rspace.has_credentials():
            self._set_status("Loading folders…")
            self._run(rspace.create_tree, self._on_folders_loaded)
        else:
            self._set_status("Enter your API key in the Settings tab to get started.")
            self._tabs.setCurrentIndex(self._settings_tab_index)

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _tab_widget(self):
        outer = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(outer)
        layout = QVBoxLayout(outer)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        # return a wrapper that IS the scroll area
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addWidget(scroll)
        return wrapper, layout

    def _make_form(self, parent=None):
        """A QFormLayout whose fields grow to fill the width on every platform.

        macOS's native style otherwise leaves fields at their (tiny) size hint,
        which is why inputs looked cramped on Mac but fine elsewhere.
        """
        form = QFormLayout(parent) if parent is not None else QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.DontWrapRows)
        return form

    def _tab_header(self, layout, title, help_text):
        row = QHBoxLayout()
        lbl = QLabel(title)
        _font = lbl.font()
        _font.setBold(True)
        if _font.pointSize() > 0:
            _font.setPointSize(_font.pointSize() + 1)
        lbl.setFont(_font)
        row.addWidget(lbl)
        row.addStretch()
        row.addWidget(self._help_btn(help_text))
        layout.addLayout(row)

    def _help_btn(self, text):
        btn = QPushButton("?")
        btn.setFixedSize(22, 22)
        btn.setToolTip(text)
        btn.clicked.connect(lambda: QMessageBox.information(self, "Help", text))
        return btn

    def _make_folder_combo(self, include_workspace=False):
        combo = QComboBox()
        combo.setProperty("has_workspace", include_workspace)
        combo.addItem("Loading…", None)
        self._folder_combos.append(combo)
        return combo

    def _make_folder_tree(self, include_workspace=False):
        tree = FolderTree(include_workspace)
        self._folder_trees.append(tree)
        return tree

    def _make_searchable_combo(self):
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        completer = QCompleter()
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        combo.setCompleter(completer)
        return combo

    def _run(self, fn, on_success, *args, **kwargs):
        worker = Worker(fn, *args, **kwargs)
        worker.finished.connect(on_success)
        worker.error.connect(self._show_error)
        worker.error.connect(lambda _: self._set_status("Error — see output"))
        # Clean up the worker once it finishes so the list doesn't grow unboundedly
        worker.finished.connect(lambda _: self._workers.remove(worker) if worker in self._workers else None)
        worker.error.connect(lambda _: self._workers.remove(worker) if worker in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _print(self, text):
        self._output.appendPlainText(text)
        self._output.appendPlainText("")

    def _show_error(self, msg):
        self._output.appendPlainText(f"ERROR: {msg}\n")

    def _set_status(self, msg):
        self._status.showMessage(msg)

    def _open_path(self, path):
        if not path:
            return
        p = Path(path)
        target = p.parent if p.is_file() else p
        system = platform.system()
        if system == "Windows":
            os.startfile(str(target))
        elif system == "Darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])

    # ── Folder loading ─────────────────────────────────────────────────────────

    def _on_folders_loaded(self, tree_nodes):
        self._folders = tree_nodes
        for tree in self._folder_trees:
            tree.populate(tree_nodes)

        def count(nodes):
            return sum(1 + count(n.get("children", [])) for n in nodes
                       if n.get("type") in ("folder", "notebook"))
        self._set_status(f"{count(tree_nodes)} folders / notebooks loaded")
        self._refresh_create_tags()

    def _output_folder_row(self):
        """Create an output-folder picker. Returns (line_edit, row_layout)."""
        line = QLineEdit()
        line.setPlaceholderText("Choose a folder to save into…")
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_folder(line))
        row = QHBoxLayout()
        row.addWidget(line)
        row.addWidget(browse)
        return line, row

    # ── Tab: Fetch Metadata ────────────────────────────────────────────────────

    def _build_metadata_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Fetch Metadata",
            "Downloads a summary of all documents in the selected folder and saves it "
            "as a JSON file in the chosen output folder. Use this as the starting point "
            "for creating a CSV.")
        form = self._make_form()
        self._meta_folder = self._make_folder_tree()
        form.addRow("Folder / Notebook:", self._meta_folder)
        self._meta_output, out_row = self._output_folder_row()
        form.addRow("Save to:", out_row)
        layout.addLayout(form)
        btn = QPushButton("Fetch Metadata")
        btn.clicked.connect(self._run_get_metadata)
        layout.addWidget(btn)
        self._meta_open_btn = QPushButton("Open saved JSON…")
        self._meta_open_btn.setEnabled(False)
        self._meta_last_path = None
        self._meta_open_btn.clicked.connect(lambda: self._open_path(self._meta_last_path))
        layout.addWidget(self._meta_open_btn)
        layout.addStretch()
        return w

    def _run_get_metadata(self):
        folder_id = self._meta_folder.current_folder_id()
        if folder_id is None:
            self._print("Please select a folder or notebook.")
            return
        output_dir = self._meta_output.text().strip()
        if not output_dir:
            self._print("Please choose an output folder ('Save to').")
            return
        self._set_status("Fetching metadata…")
        self._run(rspace.get_metadata_in_folder, self._show_metadata_result, folder_id, output_dir)

    def _show_metadata_result(self, path):
        self._meta_last_path = path
        self._meta_open_btn.setEnabled(True)
        import json
        with open(path) as f:
            count = len(json.load(f))
        self._print(f"Saved {count} document(s) to:\n{path}")
        self._set_status(f"Metadata saved — {count} documents")

    # ── Tab: Summary CSV ───────────────────────────────────────────────────────

    def _build_csv_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Summary CSV",
            "Reads the JSON file you fetched earlier and converts it into a spreadsheet (CSV). "
            "Each row is one RSpace document, with its ID, date, experimenter name, and tags.")
        form = self._make_form()
        self._csv_meta_path = QLineEdit()
        self._csv_meta_path.setPlaceholderText("metadata_12345.json")
        self._csv_meta_path.textChanged.connect(self._on_csv_meta_path_changed)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_metadata_json)
        row = QHBoxLayout()
        row.addWidget(self._csv_meta_path)
        row.addWidget(browse)
        form.addRow("Metadata JSON:", row)
        self._csv_output, out_row = self._output_folder_row()
        form.addRow("Save to:", out_row)
        layout.addLayout(form)

        # Optional filter: keep only entries carrying one of the chosen tags. The
        # choices are the "preprocessed"/"results" tags and the methods found in the
        # selected file. Leaving it empty includes every entry.
        self._csv_all_filters = []
        self._csv_selected_filters = []
        filter_box = QGroupBox("Filter entries by tag (optional)")
        fbl = QVBoxLayout(filter_box)
        fbl.setSpacing(4)
        fbl.addWidget(QLabel(
            "Add tags to keep only entries that have ANY of them (preprocessed, results, "
            "or a method). Leave empty to include every entry."))
        self._csv_filter_search = QLineEdit()
        self._csv_filter_search.setPlaceholderText("Search preprocessed / results / methods…")
        self._csv_filter_search.textChanged.connect(self._rebuild_csv_filter_available)
        fbl.addWidget(self._csv_filter_search)
        self._csv_filter_available = QListWidget()
        self._csv_filter_available.setMaximumHeight(110)
        fbl.addWidget(self._csv_filter_available)
        fbl.addWidget(QLabel("Active filters:"))
        self._csv_filter_selected = QListWidget()
        self._csv_filter_selected.setMaximumHeight(80)
        fbl.addWidget(self._csv_filter_selected)
        layout.addWidget(filter_box)

        btn = QPushButton("Create Summary CSV")
        btn.clicked.connect(self._run_create_csv)
        layout.addWidget(btn)
        self._csv_open_btn = QPushButton("Open saved CSV…")
        self._csv_open_btn.setEnabled(False)
        self._csv_last_path = None
        self._csv_open_btn.clicked.connect(lambda: self._open_path(self._csv_last_path))
        layout.addWidget(self._csv_open_btn)
        layout.addStretch()
        return w

    def _browse_metadata_json(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select metadata JSON", "", "JSON files (*.json)")
        if path:
            self._csv_meta_path.setText(path)

    # Tag filter (populated from the selected metadata file)

    def _on_csv_meta_path_changed(self, *_):
        self._load_csv_filters()

    def _load_csv_filters(self):
        path = self._csv_meta_path.text().strip()
        if not path:
            self._csv_all_filters = []
        else:
            try:
                self._csv_all_filters = rspace.filterable_tags(path)
            except Exception as exc:
                self._csv_all_filters = []
                self._show_error(f"Could not read tags from {path}: {exc}")
        # drop any selections no longer present in the file
        self._csv_selected_filters = [t for t in self._csv_selected_filters
                                      if t in self._csv_all_filters]
        self._rebuild_csv_filter_available()
        self._rebuild_csv_filter_selected()

    def _rebuild_csv_filter_available(self, *_):
        query = self._csv_filter_search.text().strip().lower()
        available = [t for t in self._csv_all_filters
                     if t not in self._csv_selected_filters and query in t.lower()]
        self._fill_tag_list(self._csv_filter_available, available, "+", self._add_csv_filter)

    def _rebuild_csv_filter_selected(self):
        self._fill_tag_list(self._csv_filter_selected, self._csv_selected_filters,
                            "✕", self._remove_csv_filter)

    def _add_csv_filter(self, tag):
        if tag not in self._csv_selected_filters:
            self._csv_selected_filters.append(tag)
            self._rebuild_csv_filter_selected()
            self._rebuild_csv_filter_available()

    def _remove_csv_filter(self, tag):
        if tag in self._csv_selected_filters:
            self._csv_selected_filters.remove(tag)
            self._rebuild_csv_filter_selected()
            self._rebuild_csv_filter_available()

    def _run_create_csv(self):
        path = self._csv_meta_path.text().strip()
        if not path:
            self._print("Please select a metadata JSON file.")
            return
        output_dir = self._csv_output.text().strip()
        if not output_dir:
            self._print("Please choose an output folder ('Save to').")
            return
        filter_tags = list(self._csv_selected_filters) or None
        self._set_status("Creating summary CSV…")
        self._run(rspace.create_summary_csv, self._show_csv_result, path, output_dir, filter_tags)

    def _show_csv_result(self, path):
        self._csv_last_path = path
        self._csv_open_btn.setEnabled(True)
        self._print(f"Summary CSV saved to:\n{path}")
        self._set_status("CSV created")

    # ── Tab: File Paths ────────────────────────────────────────────────────────

    def _build_filepaths_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Generate File Paths",
            "Reads the summary CSV and generates a suggested folder path for each entry, "
            "saving them as a CSV in the chosen output folder. Raw entries go to "
            "raw_data/method/experimenter/filename; entries tagged 'preprocessed' or "
            "'results' go to processed_data/<lab>/experimenter/<preprocessed|results>/filename. "
            "Choose the output format and whether to include the raw_data/ and "
            "processed_data/ top-level folders — the Example below updates to match.")
        form = self._make_form()
        self._fp_csv_path = QLineEdit()
        self._fp_csv_path.setPlaceholderText("summary_metadata_12345.csv")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_summary_csv)
        row = QHBoxLayout()
        row.addWidget(self._fp_csv_path)
        row.addWidget(browse)
        form.addRow("Summary CSV:", row)
        self._fp_output, out_row = self._output_folder_row()
        form.addRow("Save to:", out_row)
        layout.addLayout(form)

        # Output format: one full-path column (current) or split into three columns.
        fmt_box = QGroupBox("Output format")
        fmt_layout = QVBoxLayout(fmt_box)
        fmt_layout.setSpacing(4)
        self._fp_fmt_group = QButtonGroup(self)
        self._fp_fmt_full = QRadioButton(
            "One path per entry  —  columns:  mouseID, filepath")
        self._fp_fmt_split = QRadioButton(
            "Split  —  columns:  id, entry name, path  (path excludes the entry name)")
        self._fp_fmt_full.setChecked(True)   # default: current behaviour
        self._fp_fmt_group.addButton(self._fp_fmt_full)
        self._fp_fmt_group.addButton(self._fp_fmt_split)
        fmt_layout.addWidget(self._fp_fmt_full)
        fmt_layout.addWidget(self._fp_fmt_split)
        layout.addWidget(fmt_box)

        # Optional top-level folders. Off = the path starts one level lower, so users
        # whose top-level folder is named differently can add their own.
        top_box = QGroupBox("Top-level folders (optional)")
        top_layout = QVBoxLayout(top_box)
        top_layout.setSpacing(4)
        top_layout.addWidget(QLabel(
            "Prepend a standard top-level folder. Turn one off if your computer uses a "
            "different top-level name — everything below it stays the same."))
        self._fp_rawdata_chk = QCheckBox("Prefix raw-data paths with 'raw_data/'")
        self._fp_rawdata_chk.setChecked(True)
        self._fp_processed_chk = QCheckBox(
            "Prefix preprocessed/results paths with 'processed_data/'")
        self._fp_processed_chk.setChecked(True)
        top_layout.addWidget(self._fp_rawdata_chk)
        top_layout.addWidget(self._fp_processed_chk)
        layout.addWidget(top_box)

        # Live example of what the chosen options produce (uses the real backend so it
        # always matches the generated CSV).
        ex_box = QGroupBox("Example")
        ex_layout = QVBoxLayout(ex_box)
        self._fp_example = QLabel()
        self._fp_example.setWordWrap(True)
        self._fp_example.setStyleSheet("font-family: monospace;")
        self._fp_example.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        ex_layout.addWidget(self._fp_example)
        layout.addWidget(ex_box)

        for widget in (self._fp_fmt_full, self._fp_fmt_split,
                       self._fp_rawdata_chk, self._fp_processed_chk):
            widget.toggled.connect(self._update_fp_example)
        self._update_fp_example()

        btn = QPushButton("Generate File Paths")
        btn.clicked.connect(self._run_generate_filepaths)
        layout.addWidget(btn)
        self._fp_open_btn = QPushButton("Open saved CSV…")
        self._fp_open_btn.setEnabled(False)
        self._fp_last_path = None
        self._fp_open_btn.clicked.connect(lambda: self._open_path(self._fp_last_path))
        layout.addWidget(self._fp_open_btn)
        layout.addStretch()
        return w

    def _browse_summary_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select summary CSV", "", "CSV files (*.csv)")
        if path:
            self._fp_csv_path.setText(path)

    def _fp_options(self):
        """Return the (fmt, raw_data_prefix, processed_data_prefix) chosen in the tab."""
        return (
            "split" if self._fp_fmt_split.isChecked() else "full",
            self._fp_rawdata_chk.isChecked(),
            self._fp_processed_chk.isChecked(),
        )

    def _update_fp_example(self, *_):
        """Refresh the live example to match the selected format and prefixes."""
        fmt, raw_prefix, processed_prefix = self._fp_options()
        # Two representative entries: a raw recording and a preprocessed result.
        sample = [
            {"mouseID": "OPI111", "date": "20260601", "time": "1030",
             "experimenter_name": "ada_lovelace", "method": "microscopy",
             "tags": "id_OPI111;m_microscopy", "extra": "test"},
            {"mouseID": "OPI112", "date": "20260601", "time": "1045",
             "experimenter_name": "ada_lovelace", "method": "",
             "tags": "preprocessed", "extra": "analysis"},
        ]
        records = rspace.filepaths_for_rows(
            sample, rspace.load_lab_group(), fmt=fmt,
            raw_data_prefix=raw_prefix, processed_data_prefix=processed_prefix)
        if fmt == "split":
            lines = ["id  |  entry name  |  path"]
            lines += [f"{r[0] or '(none)'}  |  {r[1]}  |  {r[2]}" for r in records]
        else:
            lines = ["mouseID  |  filepath"]
            lines += [f"{r[0] or '(none)'}  |  {r[1]}" for r in records]
        self._fp_example.setText("\n".join(lines))

    def _run_generate_filepaths(self):
        path = self._fp_csv_path.text().strip()
        if not path:
            self._print("Please select a summary CSV file.")
            return
        output_dir = self._fp_output.text().strip()
        if not output_dir:
            self._print("Please choose an output folder ('Save to').")
            return
        fmt, raw_prefix, processed_prefix = self._fp_options()
        self._set_status("Generating file paths…")
        self._run(rspace.generate_filepaths, self._show_filepaths_result, path, output_dir,
                  fmt=fmt, raw_data_prefix=raw_prefix, processed_data_prefix=processed_prefix)

    def _show_filepaths_result(self, path):
        self._fp_last_path = path
        self._fp_open_btn.setEnabled(True)
        self._print(f"File paths saved to:\n{path}")
        self._set_status("File paths created")

    # ── Tab: Create Entry ──────────────────────────────────────────────────────

    def _build_create_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Create Entry",
            "Creates one or more entries in the selected RSpace folder. Pick the folder, "
            "choose the subject ID(s) — use 'Add subject +' for several animals — set the "
            "date/time and a short name, add any extra tags, then click 'Create Entry'. One "
            "entry is created per subject, named date_time_name and tagged with that "
            "subject's ID plus the shared tags.")
        form = self._make_form()

        self._create_all_tags = []
        self._create_selected_tags = []
        self._create_id_tags = []      # available id_ tags for the subject dropdowns
        self._create_id_combos = []    # one searchable combo per subject

        # Where to store the entry. Selecting a folder refreshes the subject IDs
        # (which are folder-scoped); the additional-tags vocabulary is workspace-wide.
        self._create_folder = self._make_folder_tree()
        self._create_folder.selection_changed.connect(self._refresh_create_ids)
        form.addRow("Folder / Notebook:", self._create_folder)

        # Which subject(s) this entry is for (tags starting with "id_")
        subjects_box = QWidget()
        subjects_outer = QVBoxLayout(subjects_box)
        subjects_outer.setContentsMargins(0, 0, 0, 0)
        subjects_outer.setSpacing(4)
        self._create_subjects_layout = QVBoxLayout()
        self._create_subjects_layout.setContentsMargins(0, 0, 0, 0)
        self._create_subjects_layout.setSpacing(4)
        subjects_outer.addLayout(self._create_subjects_layout)
        add_subject_btn = QPushButton("Add subject +")
        add_subject_btn.clicked.connect(self._add_subject_row)
        subjects_outer.addWidget(add_subject_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        form.addRow("Subject ID(s):", subjects_box)

        # Date / Time
        self._create_date = QLineEdit()
        self._create_date.setPlaceholderText("YYYYMMDD")
        self._create_date.textChanged.connect(self._update_create_name_preview)
        form.addRow("Date:", self._create_date)

        self._create_time = QLineEdit()
        self._create_time.setPlaceholderText("HHMM")
        self._create_time.textChanged.connect(self._update_create_name_preview)
        form.addRow("Time:", self._create_time)

        self._create_use_now_chk = QCheckBox("Fill in current date && time")
        self._create_use_now_chk.setToolTip(
            "Reads this computer's current date and time once and fills the fields "
            "above. Tick again to refresh."
        )
        self._create_use_now_chk.toggled.connect(self._on_create_now_toggled)
        form.addRow("", self._create_use_now_chk)

        # The "Extra" part of the name
        self._create_extra = QLineEdit()
        self._create_extra.setPlaceholderText("e.g. Recording1, Test…")
        self._create_extra.textChanged.connect(self._update_create_name_preview)
        form.addRow("Name (Extra):", self._create_extra)

        # Preview of the full name
        self._create_name_preview = QLabel("")
        self._create_name_preview.setWordWrap(True)
        form.addRow("Will be created as:", self._create_name_preview)

        # Start with one subject row (needs the date/time/preview widgets to exist first).
        self._add_subject_row()

        # Additional tags: search + available list (+) and chosen list (×)
        tags_box = QWidget()
        tags_layout = QVBoxLayout(tags_box)
        tags_layout.setContentsMargins(0, 0, 0, 0)
        tags_layout.setSpacing(4)

        self._create_tag_search = QLineEdit()
        self._create_tag_search.setPlaceholderText("Search tags…")
        self._create_tag_search.textChanged.connect(self._rebuild_create_available)
        tags_layout.addWidget(self._create_tag_search)

        self._create_tag_available = QListWidget()
        self._create_tag_available.setMaximumHeight(120)
        tags_layout.addWidget(self._create_tag_available)

        tags_layout.addWidget(QLabel("Added tags:"))
        self._create_tag_selected = QListWidget()
        self._create_tag_selected.setMaximumHeight(90)
        tags_layout.addWidget(self._create_tag_selected)
        form.addRow("Tags:", tags_box)

        # Comment / content
        self._create_content = QPlainTextEdit()
        self._create_content.setPlaceholderText("Comment / content (plain text or HTML)…")
        self._create_content.setMaximumHeight(100)
        form.addRow("Comment / Content:", self._create_content)

        layout.addLayout(form)

        # ── Drafts / autosave ──
        self._create_active_draft_id = None
        self._create_active_draft_path = None
        self._create_autosave_timer = QTimer(self)
        self._create_autosave_timer.setInterval(60000)  # once per minute
        self._create_autosave_timer.timeout.connect(self._create_autosave_now)

        drafts_box = QGroupBox("Drafts (autosave)")
        drafts_layout = QVBoxLayout(drafts_box)
        drafts_layout.setSpacing(4)

        self._create_autosave_chk = QCheckBox("Autosave this draft every minute")
        self._create_autosave_chk.setToolTip(
            "Periodically saves the form to the Autosaved/ folder so a crash doesn't lose "
            "your notes. The draft can be reloaded below.")
        self._create_autosave_chk.toggled.connect(self._on_create_autosave_toggled)
        drafts_layout.addWidget(self._create_autosave_chk)

        self._create_autosave_status = QLabel("")
        self._create_autosave_status.setWordWrap(True)
        drafts_layout.addWidget(self._create_autosave_status)

        load_row = QHBoxLayout()
        load_row.addWidget(QLabel("Load draft:"))
        self._create_draft_combo = QComboBox()
        load_row.addWidget(self._create_draft_combo, stretch=1)
        load_btn = QPushButton("Load")
        load_btn.clicked.connect(self._load_selected_draft)
        load_row.addWidget(load_btn)
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Refresh the list of saved drafts")
        refresh_btn.clicked.connect(self._refresh_create_drafts)
        load_row.addWidget(refresh_btn)
        drafts_layout.addLayout(load_row)

        self._create_delete_on_publish_chk = QCheckBox("Delete this draft after publishing")
        drafts_layout.addWidget(self._create_delete_on_publish_chk)

        layout.addWidget(drafts_box)
        self._refresh_create_drafts()

        btn = QPushButton("Create Entry")
        btn.clicked.connect(self._run_create_entry)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    # ── Create tab — subjects & name building ────────────────────────────────────

    def _add_subject_row(self, *_):
        """Append another subject-ID search bar (with a remove button)."""
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        combo = self._make_searchable_combo()
        combo.setPlaceholderText("Select a subject ID (id_…)")
        combo.addItems(self._create_id_tags)
        combo.setCurrentIndex(-1)
        combo.completer().setModel(QStringListModel(self._create_id_tags))
        combo.currentTextChanged.connect(self._update_create_name_preview)
        h.addWidget(combo)
        remove = QPushButton("✕")
        remove.setFixedWidth(28)
        remove.setToolTip("Remove this subject")
        remove.clicked.connect(lambda: self._remove_subject_row(row, combo))
        h.addWidget(remove)
        self._create_subjects_layout.addWidget(row)
        self._create_id_combos.append(combo)
        self._update_create_name_preview()

    def _remove_subject_row(self, row, combo):
        if len(self._create_id_combos) <= 1:
            combo.setCurrentIndex(-1)   # keep at least one row — just clear it
        else:
            self._create_id_combos.remove(combo)
            self._create_subjects_layout.removeWidget(row)
            row.deleteLater()
        self._update_create_name_preview()

    def _create_subject_id_tags(self):
        """The non-empty subject ID tags chosen across all rows (de-duplicated)."""
        chosen = []
        for combo in self._create_id_combos:
            tag = combo.currentText().strip()
            if tag and tag not in chosen:
                chosen.append(tag)
        return chosen

    def _create_entry_items(self):
        """Return a list of (name, tags) — one per subject (or a single item if none).

        The name is date_time_extra (no subject ID prefix); the subject is recorded via
        its id_ tag, so several subjects produce identically-named entries with different
        ID tags.
        """
        name = "_".join(p for p in (self._create_date.text().strip(),
                                    self._create_time.text().strip(),
                                    self._create_extra.text().strip()) if p)
        subjects = self._create_subject_id_tags()
        if subjects:
            return [(name, list(dict.fromkeys([id_tag] + self._create_selected_tags)))
                    for id_tag in subjects]
        return [(name, list(self._create_selected_tags))]

    def _update_create_name_preview(self, *_):
        items = self._create_entry_items()
        name = items[0][0] if items else ""
        n = len(self._create_subject_id_tags())
        if not name:
            self._create_name_preview.setText("<name>")
        elif n > 1:
            self._create_name_preview.setText(f"{name}   (× {n} entries, one per subject)")
        else:
            self._create_name_preview.setText(name)

    def _on_create_now_toggled(self, checked):
        if checked:  # read the clock once and fill the fields
            date, time = rspace.current_date_time()
            self._create_date.setText(date)
            self._create_time.setText(time)
            self._update_create_name_preview()

    # ── Create tab — tags ────────────────────────────────────────────────────────

    def _refresh_create_tags(self):
        # Additional-tags vocabulary: the whole workspace (so method (m_) and other
        # tags are always available regardless of the target folder). Loaded once.
        self._run(rspace.get_tags, self._populate_create_workspace_tags)

    def _populate_create_workspace_tags(self, tags):
        self._create_all_tags = list(tags)
        self._rebuild_create_available()
        self._rebuild_create_selected()

    def _refresh_create_ids(self, *_):
        # Subject IDs come from the selected target folder only.
        folder_id = self._create_folder.current_folder_id()
        self._run(rspace.get_tags, self._populate_create_ids, project_folder=folder_id)

    def _populate_create_ids(self, tags):
        self._create_id_tags = [t for t in tags if t.startswith("id_")]
        for combo in self._create_id_combos:
            prev = combo.currentText()
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(self._create_id_tags)
            combo.completer().setModel(QStringListModel(self._create_id_tags))
            combo.setCurrentIndex(combo.findText(prev))  # keep prior pick if still valid, else clear
            combo.blockSignals(False)
        self._update_create_name_preview()

    def _tag_row_widget(self, tag, symbol, handler):
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(4, 1, 4, 1)
        h.addWidget(QLabel(tag))
        h.addStretch()
        btn = QPushButton(symbol)
        btn.setFixedWidth(28)
        btn.clicked.connect(lambda: handler(tag))
        h.addWidget(btn)
        return row

    def _fill_tag_list(self, list_widget, tags, symbol, handler):
        list_widget.clear()
        for tag in tags:
            widget = self._tag_row_widget(tag, symbol, handler)
            item = QListWidgetItem()
            item.setSizeHint(widget.sizeHint())
            list_widget.addItem(item)
            list_widget.setItemWidget(item, widget)

    def _rebuild_create_available(self, *_):
        query = self._create_tag_search.text().strip().lower()
        available = [
            t for t in self._create_all_tags
            if not t.startswith("id_")          # subject IDs are chosen above, not here
            and t not in self._create_selected_tags
            and (query in t.lower())
        ]
        self._fill_tag_list(self._create_tag_available, available, "+", self._add_create_tag)

    def _rebuild_create_selected(self):
        self._fill_tag_list(self._create_tag_selected, self._create_selected_tags,
                            "✕", self._remove_create_tag)

    def _add_create_tag(self, tag):
        if tag not in self._create_selected_tags:
            self._create_selected_tags.append(tag)
            self._rebuild_create_selected()
            self._rebuild_create_available()

    def _remove_create_tag(self, tag):
        if tag in self._create_selected_tags:
            self._create_selected_tags.remove(tag)
            self._rebuild_create_selected()
            self._rebuild_create_available()

    def _run_create_entry(self):
        folder_id = self._create_folder.current_folder_id()
        items = [(name, tags) for name, tags in self._create_entry_items() if name]
        if folder_id is None or not items:
            self._print("Please select a folder and fill in at least one name part (subject ID, date, time or name).")
            return
        content = self._create_content.toPlainText().strip()
        n = len(items)
        self._set_status(f"Creating {n} entr{'y' if n == 1 else 'ies'}…")
        self._run(rspace.create_entries, self._show_create_result, folder_id, items, content)

    def _show_create_result(self, results):
        if isinstance(results, dict):  # be tolerant of a single-dict result
            results = [results]
        n = len(results)
        lines = [f"Created {n} entr{'y' if n == 1 else 'ies'}:"]
        for data in results:
            lines.append(f"  {data.get('globalId')}  {data.get('name')}  [tags: {data.get('tags')}]")
        self._print("\n".join(lines))
        self._set_status(f"Created {n} entr{'y' if n == 1 else 'ies'}")

        if self._create_delete_on_publish_chk.isChecked() and self._create_active_draft_path:
            rspace.delete_draft(self._create_active_draft_path)
            self._create_active_draft_path = None
            self._create_active_draft_id = None
            self._create_autosave_chk.setChecked(False)  # also stops the timer
            self._refresh_create_drafts()
            self._print("Deleted the autosaved draft.")

    # ── Create tab — autosave / drafts ───────────────────────────────────────────

    def _create_form_state(self):
        names = [name for name, _ in self._create_entry_items() if name]
        return {
            "folder_id": self._create_folder.current_folder_id(),
            "subjects": self._create_subject_id_tags(),
            "date": self._create_date.text(),
            "time": self._create_time.text(),
            "extra": self._create_extra.text(),
            "tags": list(self._create_selected_tags),
            "content": self._create_content.toPlainText(),
            "name": names[0] if names else "(unnamed draft)",
        }

    def _on_create_autosave_toggled(self, checked):
        if checked:
            if not self._create_active_draft_id:
                self._create_active_draft_id = datetime.now().strftime("draft_%Y%m%d_%H%M%S")
            self._create_autosave_now()
            self._create_autosave_timer.start()
        else:
            self._create_autosave_timer.stop()

    def _create_autosave_now(self):
        if not self._create_active_draft_id:
            self._create_active_draft_id = datetime.now().strftime("draft_%Y%m%d_%H%M%S")
        try:
            self._create_active_draft_path = rspace.save_draft(
                self._create_active_draft_id, self._create_form_state())
            self._create_autosave_status.setText(
                f"Autosaved at {datetime.now().strftime('%H:%M:%S')} "
                f"→ {self._create_active_draft_id}.json")
            self._refresh_create_drafts()
        except Exception as exc:
            self._show_error(f"Autosave failed: {exc}")

    def _refresh_create_drafts(self):
        drafts = rspace.list_drafts()
        self._create_draft_combo.clear()
        for d in drafts:
            label = d["name"] + (f"  ({d['saved_at']})" if d["saved_at"] else "")
            self._create_draft_combo.addItem(label, d["path"])

    def _load_selected_draft(self):
        path = self._create_draft_combo.currentData()
        if not path:
            self._print("No saved draft to load.")
            return
        try:
            data = rspace.load_draft(path)
        except Exception as exc:
            self._show_error(f"Could not load draft: {exc}")
            return
        self._load_create_draft(data)
        self._create_active_draft_path = path
        self._create_active_draft_id = Path(path).stem
        self._set_status(f"Loaded draft: {data.get('name', '')}")

    def _load_create_draft(self, data):
        self._create_folder.select_by_id(data.get("folder_id"))
        self._set_subjects(data.get("subjects") or [])
        self._create_date.setText(data.get("date", ""))
        self._create_time.setText(data.get("time", ""))
        self._create_extra.setText(data.get("extra", ""))
        self._create_selected_tags = list(data.get("tags") or [])
        self._rebuild_create_selected()
        self._rebuild_create_available()
        self._create_content.setPlainText(data.get("content", ""))
        self._update_create_name_preview()

    def _set_subjects(self, tags):
        # Clear all subject rows, then add one per tag (always at least one row).
        while self._create_subjects_layout.count():
            item = self._create_subjects_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._create_id_combos = []
        for _ in (tags or [None]):
            self._add_subject_row()
        for combo, tag in zip(self._create_id_combos, tags or []):
            combo.setCurrentText(tag)
        self._update_create_name_preview()

    # ── Tab: Project Overview ──────────────────────────────────────────────────

    def _build_overview_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Project Overview",
            "Builds a spreadsheet (CSV) of every entry in the selected folder: one row "
            "per document, with the document name in the first column and one column for "
            "each form field (the column header is the field name, the cell is its value). "
            "Useful for scanning a whole project at a glance.")
        form = self._make_form()
        self._overview_folder = self._make_folder_tree()
        form.addRow("Folder:", self._overview_folder)
        self._overview_output, out_row = self._output_folder_row()
        form.addRow("Save to:", out_row)
        layout.addLayout(form)
        btn = QPushButton("Generate Overview")
        btn.clicked.connect(self._run_project_overview)
        layout.addWidget(btn)
        self._overview_open_btn = QPushButton("Open saved CSV…")
        self._overview_open_btn.setEnabled(False)
        self._overview_last_path = None
        self._overview_open_btn.clicked.connect(lambda: self._open_path(self._overview_last_path))
        layout.addWidget(self._overview_open_btn)
        layout.addStretch()
        return w

    def _run_project_overview(self):
        folder_id = self._overview_folder.current_folder_id()
        if folder_id is None:
            self._print("Please select a folder.")
            return
        output_dir = self._overview_output.text().strip()
        if not output_dir:
            self._print("Please choose an output folder ('Save to').")
            return
        self._set_status("Generating overview…")
        self._run(rspace.project_overview, self._show_overview_result, folder_id, output_dir)

    def _show_overview_result(self, path):
        self._overview_last_path = path
        self._overview_open_btn.setEnabled(True)
        self._print(f"Overview CSV saved to:\n{path}")
        self._set_status("Overview created")

    # ── Tab: Rename Files ──────────────────────────────────────────────────────

    def _build_rename_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Rename Files",
            "Rename local files by adding a structured prefix (ID_date_time_) to their names.\n\n"
            "The ID, date, and time can be looked up automatically from RSpace entries, "
            "or typed freely if RSpace is not available.\n\n"
            "Files can optionally be moved into a new organised folder and/or copied to "
            "a raw data server location.")

        # ── RSpace connection status ──
        conn_row = QHBoxLayout()
        self._rn_conn_label = QLabel("● RSpace: checking…")
        self._rn_conn_label.setStyleSheet("color: gray; font-weight: bold;")
        conn_row.addWidget(self._rn_conn_label)
        recheck_btn = QPushButton("Re-check")
        recheck_btn.setFixedWidth(80)
        recheck_btn.clicked.connect(self._check_rspace_connection)
        conn_row.addWidget(recheck_btn)
        conn_row.addStretch()
        layout.addLayout(conn_row)

        # ── Prefix fields ──
        prefix_box = QGroupBox("Prefix")
        pform = self._make_form(prefix_box)

        # Field 1: ID / tag
        id_row = QHBoxLayout()
        self._rn_id = self._make_searchable_combo()
        self._rn_id.setPlaceholderText("e.g. id_OPI111")
        id_row.addWidget(self._rn_id)
        refresh_btn = QPushButton("↺")
        refresh_btn.setFixedWidth(28)
        refresh_btn.setToolTip("Reload tags from RSpace")
        refresh_btn.clicked.connect(self._load_rename_tags)
        id_row.addWidget(refresh_btn)
        pform.addRow("ID (tag):", id_row)

        # Field 2: date
        self._rn_date = self._make_searchable_combo()
        self._rn_date.setPlaceholderText("YYYYMMDD")
        self._rn_date.setEnabled(False)
        pform.addRow("Date:", self._rn_date)

        # Field 3: time
        self._rn_time = self._make_searchable_combo()
        self._rn_time.setPlaceholderText("HHMM")
        self._rn_time.setEnabled(False)
        pform.addRow("Time:", self._rn_time)

        # Live preview
        self._rn_preview = QLabel("Preview: (fill in the fields above)")
        self._rn_preview.setWordWrap(True)
        pform.addRow("Preview:", self._rn_preview)

        layout.addWidget(prefix_box)

        # Debounce API lookups: wait 500 ms after the user stops typing/selecting
        # before firing a network request, to avoid hammering the API on every keystroke.
        self._rn_id_timer = QTimer()
        self._rn_id_timer.setSingleShot(True)
        self._rn_id_timer.setInterval(500)
        self._rn_id_timer.timeout.connect(self._on_rename_id_changed)

        self._rn_date_timer = QTimer()
        self._rn_date_timer.setSingleShot(True)
        self._rn_date_timer.setInterval(500)
        self._rn_date_timer.timeout.connect(self._on_rename_date_changed)

        self._rn_id.currentTextChanged.connect(lambda _: self._rn_id_timer.start())
        self._rn_date.currentTextChanged.connect(lambda _: self._rn_date_timer.start())
        self._rn_time.currentTextChanged.connect(self._update_rename_preview)

        # ── File selection ──
        files_box = QGroupBox("Files to rename")
        fbox_layout = QVBoxLayout(files_box)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add Files…")
        add_btn.clicked.connect(self._rename_add_files)
        btn_row.addWidget(add_btn)
        rm_btn = QPushButton("Remove Selected")
        rm_btn.clicked.connect(self._rename_remove_files)
        btn_row.addWidget(rm_btn)
        btn_row.addStretch()
        fbox_layout.addLayout(btn_row)

        self._rn_file_list = QListWidget()
        self._rn_file_list.setSelectionMode(QListWidget.SelectionMode.ExtendedSelection)
        self._rn_file_list.setMinimumHeight(80)
        self._rn_file_list.model().rowsInserted.connect(self._update_rename_preview)
        self._rn_file_list.model().rowsRemoved.connect(self._update_rename_preview)
        fbox_layout.addWidget(self._rn_file_list)

        layout.addWidget(files_box)

        # ── Options ──
        opts_box = QGroupBox("Options")
        opts_layout = QVBoxLayout(opts_box)

        # Put in new folder
        self._rn_newfolder_chk = QCheckBox("Put renamed files in a new folder")
        self._rn_newfolder_chk.toggled.connect(self._toggle_newfolder_group)
        opts_layout.addWidget(self._rn_newfolder_chk)

        self._rn_newfolder_grp = QGroupBox()
        self._rn_newfolder_grp.setFlat(True)
        self._rn_newfolder_grp.setVisible(False)
        nf_form = self._make_form(self._rn_newfolder_grp)

        nf_loc_row = QHBoxLayout()
        self._rn_nf_location = QLineEdit()
        self._rn_nf_location.setPlaceholderText("Parent folder location")
        self._rn_nf_location.textChanged.connect(self._update_newfolder_preview)
        nf_loc_row.addWidget(self._rn_nf_location)
        nf_browse = QPushButton("Browse…")
        nf_browse.clicked.connect(lambda: self._browse_folder(self._rn_nf_location))
        nf_loc_row.addWidget(nf_browse)
        nf_form.addRow("Location:", nf_loc_row)

        self._rn_nf_ending = QLineEdit()
        self._rn_nf_ending.setPlaceholderText("e.g. raw")
        self._rn_nf_ending.textChanged.connect(self._update_newfolder_preview)
        nf_form.addRow("Name ending:", self._rn_nf_ending)

        self._rn_nf_preview = QLabel("Folder: (fill in location and ending)")
        self._rn_nf_preview.setWordWrap(True)
        nf_form.addRow("Folder will be:", self._rn_nf_preview)

        opts_layout.addWidget(self._rn_newfolder_grp)

        # Save to raw data
        self._rn_rawdata_chk = QCheckBox("Copy to Raw Data folder")
        self._rn_rawdata_chk.toggled.connect(self._toggle_rawdata_group)
        opts_layout.addWidget(self._rn_rawdata_chk)

        self._rn_rawdata_grp = QGroupBox()
        self._rn_rawdata_grp.setFlat(True)
        self._rn_rawdata_grp.setVisible(False)
        rd_form = self._make_form(self._rn_rawdata_grp)

        rd_row = QHBoxLayout()
        self._rn_rd_dest = QLineEdit()
        self._rn_rd_dest.setPlaceholderText("Raw data server folder")
        rd_row.addWidget(self._rn_rd_dest)
        rd_browse = QPushButton("Browse…")
        rd_browse.clicked.connect(lambda: self._browse_folder(self._rn_rd_dest))
        rd_row.addWidget(rd_browse)
        rd_form.addRow("Destination:", rd_row)

        opts_layout.addWidget(self._rn_rawdata_grp)

        # Erase characters from the original file name (front and/or back)
        strip_box = QGroupBox("Erase characters from original name")
        strip_layout = QVBoxLayout(strip_box)

        front_row = QHBoxLayout()
        self._rn_strip_front_chk = QCheckBox("From front:")
        self._rn_strip_front_chk.toggled.connect(self._on_strip_toggle)
        front_row.addWidget(self._rn_strip_front_chk)
        self._rn_strip_front = QSpinBox()
        self._rn_strip_front.setRange(0, 200)
        self._rn_strip_front.setSuffix(" chars")
        self._rn_strip_front.setEnabled(False)
        self._rn_strip_front.valueChanged.connect(self._update_rename_preview)
        front_row.addWidget(self._rn_strip_front)
        front_row.addStretch()
        strip_layout.addLayout(front_row)

        back_row = QHBoxLayout()
        self._rn_strip_back_chk = QCheckBox("From back:")
        self._rn_strip_back_chk.toggled.connect(self._on_strip_toggle)
        back_row.addWidget(self._rn_strip_back_chk)
        self._rn_strip_back = QSpinBox()
        self._rn_strip_back.setRange(0, 200)
        self._rn_strip_back.setSuffix(" chars")
        self._rn_strip_back.setEnabled(False)
        self._rn_strip_back.valueChanged.connect(self._update_rename_preview)
        back_row.addWidget(self._rn_strip_back)
        back_row.addStretch()
        strip_layout.addLayout(back_row)

        strip_box.setToolTip(
            "Erase characters from the start and/or end of each original file "
            "name before the prefix is added. The file extension is always kept."
        )

        self._rn_strip_preview = QLabel("(add a file to preview)")
        self._rn_strip_preview.setWordWrap(True)
        strip_layout.addWidget(self._rn_strip_preview)

        opts_layout.addWidget(strip_box)

        layout.addWidget(opts_box)

        # ── Action ──
        rename_btn = QPushButton("Rename Files")
        rename_btn.clicked.connect(self._run_rename_files)
        layout.addWidget(rename_btn)
        layout.addStretch()
        return w

    # Rename tab — slots

    def _on_tab_changed(self, index):
        if self._tabs.tabText(index) == "Rename Files" and not self._rename_tags_loaded:
            self._check_rspace_connection()
            self._load_rename_tags()

    def _check_rspace_connection(self):
        self._rn_conn_label.setText("● RSpace: checking…")
        self._rn_conn_label.setStyleSheet("color: gray; font-weight: bold;")

        def _update(result):
            ok, msg = result
            if ok:
                self._rn_conn_label.setText(f"● RSpace: connected — {msg}")
                self._rn_conn_label.setStyleSheet("color: green; font-weight: bold;")
            else:
                self._rn_conn_label.setText(f"● RSpace: not connected — {msg}")
                self._rn_conn_label.setStyleSheet("color: red; font-weight: bold;")

        self._run(rspace.check_connection, _update)

    def _load_rename_tags(self):
        self._rename_tags_loaded = True
        self._rn_id.setEnabled(False)
        self._set_status("Loading tags for Rename tab…")

        def _populate(tags):
            id_tags = [t for t in tags if t.startswith("id_")]
            self._rn_id.clear()
            self._rn_id.addItems(id_tags)
            model = QStringListModel(id_tags)
            self._rn_id.completer().setModel(model)
            self._rn_id.setEnabled(True)
            self._set_status(f"Rename tab: {len(id_tags)} subject IDs loaded")

        def _fallback(err):
            self._rn_id.setEnabled(True)
            self._set_status("RSpace unavailable — enter ID freely")

        worker = Worker(rspace.get_tags)
        worker.finished.connect(_populate)
        worker.error.connect(_fallback)
        self._workers.append(worker)
        worker.start()

    def _on_rename_id_changed(self):
        tag = self._rn_id.currentText().strip()
        self._rn_date.clear()
        self._rn_date.setEnabled(False)
        self._rn_time.clear()
        self._rn_time.setEnabled(False)
        self._update_rename_preview()
        if not tag:
            return

        def _populate_dates(dates):
            self._rn_date.clear()
            self._rn_date.addItems(dates)
            model = QStringListModel(dates)
            self._rn_date.completer().setModel(model)
            self._rn_date.setEnabled(True)

        def _fallback_dates(_):
            self._rn_date.setEnabled(True)

        worker = Worker(rspace.get_dates_for_tag, tag)
        worker.finished.connect(_populate_dates)
        worker.error.connect(_fallback_dates)
        self._workers.append(worker)
        worker.start()

    def _on_rename_date_changed(self):
        date = self._rn_date.currentText().strip()
        self._rn_time.clear()
        self._rn_time.setEnabled(False)
        self._update_rename_preview()
        tag = self._rn_id.currentText().strip()
        if not tag or not date:
            return

        def _populate_times(times):
            self._rn_time.clear()
            self._rn_time.addItems(times)
            model = QStringListModel(times)
            self._rn_time.completer().setModel(model)
            self._rn_time.setEnabled(True)

        def _fallback_times(_):
            self._rn_time.setEnabled(True)

        worker = Worker(rspace.get_times_for_tag_and_date, tag, date)
        worker.finished.connect(_populate_times)
        worker.error.connect(_fallback_times)
        self._workers.append(worker)
        worker.start()

    def _strip_front_count(self):
        """Characters to erase from the front, or 0 if the option is off."""
        if getattr(self, "_rn_strip_front_chk", None) and self._rn_strip_front_chk.isChecked():
            return self._rn_strip_front.value()
        return 0

    def _strip_back_count(self):
        """Characters to erase from the back, or 0 if the option is off."""
        if getattr(self, "_rn_strip_back_chk", None) and self._rn_strip_back_chk.isChecked():
            return self._rn_strip_back.value()
        return 0

    def _first_sample_name(self):
        """Name of the first selected file, or None if the list is empty."""
        if self._rn_file_list.count():
            return Path(self._rn_file_list.item(0).data(Qt.ItemDataRole.UserRole)).name
        return None

    def _update_rename_preview(self, *_):
        f1 = rspace.strip_tag_prefix(self._rn_id.currentText().strip())
        f2 = self._rn_date.currentText().strip()
        f3 = self._rn_time.currentText().strip()
        parts = [p for p in (f1, f2, f3) if p]
        prefix = "_".join(parts) if parts else "<prefix>"
        sample = self._first_sample_name() or "<original_filename>"
        self._rn_preview.setText(rspace.build_renamed_name(
            sample, prefix, self._strip_front_count(), self._strip_back_count()))
        self._update_strip_preview()
        self._update_newfolder_preview()

    def _update_strip_preview(self, *_):
        if not getattr(self, "_rn_strip_preview", None):
            return
        sample = self._first_sample_name()
        if sample is None:
            self._rn_strip_preview.setText("(add a file to preview)")
            return
        stripped = rspace.build_renamed_name(
            sample, "", self._strip_front_count(), self._strip_back_count())
        self._rn_strip_preview.setText(f"{sample}  →  {stripped}")

    def _on_strip_toggle(self, *_):
        self._rn_strip_front.setEnabled(self._rn_strip_front_chk.isChecked())
        self._rn_strip_back.setEnabled(self._rn_strip_back_chk.isChecked())
        self._update_rename_preview()

    def _update_newfolder_preview(self, *_):
        f1 = rspace.strip_tag_prefix(self._rn_id.currentText().strip())
        f2 = self._rn_date.currentText().strip()
        f3 = self._rn_time.currentText().strip()
        parts = [p for p in (f1, f2, f3) if p]
        prefix = "_".join(parts) if parts else "<prefix>"
        loc = self._rn_nf_location.text().strip() or "<location>"
        ending = self._rn_nf_ending.text().strip()
        folder_name = f"{prefix}_{ending}" if ending else prefix
        self._rn_nf_preview.setText(str(Path(loc) / folder_name))

    def _toggle_newfolder_group(self, checked):
        self._rn_newfolder_grp.setVisible(checked)

    def _toggle_rawdata_group(self, checked):
        self._rn_rawdata_grp.setVisible(checked)

    def _rename_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Select files to rename", "")
        for p in paths:
            if not any(
                self._rn_file_list.item(i).data(Qt.ItemDataRole.UserRole) == p
                for i in range(self._rn_file_list.count())
            ):
                item = QListWidgetItem(Path(p).name)
                item.setData(Qt.ItemDataRole.UserRole, p)
                item.setToolTip(p)
                self._rn_file_list.addItem(item)

    def _rename_remove_files(self):
        for item in self._rn_file_list.selectedItems():
            self._rn_file_list.takeItem(self._rn_file_list.row(item))

    def _browse_folder(self, line_edit):
        path = QFileDialog.getExistingDirectory(self, "Select folder")
        if path:
            line_edit.setText(path)

    def _run_rename_files(self):
        f1 = rspace.strip_tag_prefix(self._rn_id.currentText().strip())
        f2 = self._rn_date.currentText().strip()
        f3 = self._rn_time.currentText().strip()
        parts = [p for p in (f1, f2, f3) if p]
        if not parts:
            self._print("Please fill in at least the ID field.")
            return
        if self._rn_file_list.count() == 0:
            self._print("Please add at least one file.")
            return

        prefix = "_".join(parts)
        files = [
            Path(self._rn_file_list.item(i).data(Qt.ItemDataRole.UserRole))
            for i in range(self._rn_file_list.count())
        ]

        dest_folder = None
        if self._rn_newfolder_chk.isChecked():
            loc = self._rn_nf_location.text().strip()
            ending = self._rn_nf_ending.text().strip()
            if not loc:
                self._print("Please set a folder location.")
                return
            folder_name = f"{prefix}_{ending}" if ending else prefix
            dest_folder = Path(loc) / folder_name

        raw_data_folder = None
        if self._rn_rawdata_chk.isChecked():
            rd = self._rn_rd_dest.text().strip()
            if not rd:
                self._print("Please set a Raw Data destination.")
                return
            raw_data_folder = Path(rd)

        self._set_status("Renaming files…")
        self._run(
            rspace.rename_and_organize_files,
            self._show_rename_result,
            files, prefix, dest_folder, raw_data_folder,
            self._strip_front_count(), self._strip_back_count(),
        )

    def _show_rename_result(self, final_paths):
        lines = [f"  {p}" for p in final_paths]
        self._print("Renamed files:\n" + "\n".join(lines))
        self._rn_file_list.clear()
        self._set_status(f"{len(final_paths)} file(s) renamed")

    # ── Tab: Results Entry ───────────────────────────────────────────────────────

    def _build_results_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Results Entry",
            "Create an RSpace entry for a folder of analysis results. Browse to the local "
            "results folder (its name becomes the entry name), choose where to create the "
            "entry in RSpace, and describe what you did. The entry is tagged 'results', so the "
            "File Paths tab reproduces its location as "
            "processed_data/<lab>/<your name>/results/<folder name>.")
        form = self._make_form()

        # Local results folder → entry name
        self._results_folder_path = QLineEdit()
        self._results_folder_path.setPlaceholderText("Browse to your results subfolder…")
        self._results_folder_path.textChanged.connect(self._update_results_preview)
        browse = QPushButton("Browse…")
        browse.clicked.connect(lambda: self._browse_folder(self._results_folder_path))
        rrow = QHBoxLayout()
        rrow.addWidget(self._results_folder_path)
        rrow.addWidget(browse)
        form.addRow("Results folder:", rrow)

        # RSpace destination
        self._results_target = self._make_folder_tree()
        form.addRow("Create in:", self._results_target)

        self._results_name_preview = QLabel("<choose a folder>")
        self._results_name_preview.setWordWrap(True)
        form.addRow("Will be created as:", self._results_name_preview)

        self._results_comment = QPlainTextEdit()
        self._results_comment.setPlaceholderText("Describe how these results were obtained…")
        self._results_comment.setMaximumHeight(140)
        form.addRow("Comment:", self._results_comment)

        layout.addLayout(form)
        btn = QPushButton("Create Results Entry")
        btn.clicked.connect(self._run_create_results)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    def _update_results_preview(self, *_):
        name = Path(self._results_folder_path.text().strip()).name if self._results_folder_path.text().strip() else ""
        self._results_name_preview.setText(f"{name}   (tag: results)" if name else "<choose a folder>")

    def _run_create_results(self):
        folder_id = self._results_target.current_folder_id()
        path = self._results_folder_path.text().strip()
        name = Path(path).name if path else ""
        if folder_id is None or not name:
            self._print("Please choose a results folder and an RSpace destination.")
            return
        comment = self._results_comment.toPlainText().strip()
        self._set_status("Creating results entry…")
        self._run(rspace.create_entry, self._show_results_result,
                  folder_id, ["results"], name, comment)

    def _show_results_result(self, data):
        self._print(
            f"Created results entry:\n"
            f"  {data.get('globalId')}  {data.get('name')}  [tags: {data.get('tags')}]")
        self._set_status(f"Results entry created: {data.get('globalId')}")

    # ── Tab: Settings ────────────────────────────────────────────────────────────

    def _build_settings_tab(self):
        w, layout = self._tab_widget()
        self._tab_header(layout, "Settings",
            "Enter your RSpace API key here. It is stored only on this computer "
            "(in your user config folder) and is used to connect to RSpace.\n\n"
            "Find your key in RSpace:  My RSpace → My Profile → API Key.\n\n"
            "If your key ever changes, just paste the new one and click Save.")

        key, url = rspace.load_credentials()

        form = self._make_form()

        self._settings_key = QLineEdit(key)
        self._settings_key.setEchoMode(QLineEdit.EchoMode.Password)
        self._settings_key.setPlaceholderText("Paste your RSpace API key")
        form.addRow("API key:", self._settings_key)

        self._settings_show_key = QCheckBox("Show API key")
        self._settings_show_key.toggled.connect(self._toggle_key_visibility)
        form.addRow("", self._settings_show_key)

        self._settings_url = QLineEdit(url or rspace.DEFAULT_RSPACE_URL)
        self._settings_url.setPlaceholderText(rspace.DEFAULT_RSPACE_URL)
        form.addRow("Server URL:", self._settings_url)

        self._settings_lab_group = QLineEdit(rspace.load_lab_group())
        self._settings_lab_group.setPlaceholderText(rspace.LAB_GROUP)
        self._settings_lab_group.setToolTip(
            "Lab group used in processed-data file paths: "
            "processed_data/<lab group>/<experimenter>/…")
        form.addRow("Lab group:", self._settings_lab_group)

        layout.addLayout(form)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test connection")
        test_btn.clicked.connect(self._test_settings)
        btn_row.addWidget(test_btn)
        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self._save_settings)
        btn_row.addWidget(save_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._settings_status = QLabel("")
        self._settings_status.setWordWrap(True)
        layout.addWidget(self._settings_status)

        layout.addStretch()
        return w

    def _toggle_key_visibility(self, shown):
        self._settings_key.setEchoMode(
            QLineEdit.EchoMode.Normal if shown else QLineEdit.EchoMode.Password)

    def _test_settings(self):
        key = self._settings_key.text().strip()
        url = self._settings_url.text().strip() or rspace.DEFAULT_RSPACE_URL
        self._settings_status.setText("Testing connection…")
        self._set_status("Testing connection…")
        self._run(rspace.test_credentials, self._show_settings_test, key, url)

    def _show_settings_test(self, result):
        ok, msg = result
        if ok:
            self._settings_status.setText(f"✓ Connected — {msg}")
            self._set_status("Connection OK")
        else:
            self._settings_status.setText(f"✗ Could not connect — {msg}")
            self._set_status("Connection failed")

    def _save_settings(self):
        key = self._settings_key.text().strip()
        url = self._settings_url.text().strip() or rspace.DEFAULT_RSPACE_URL
        if not key:
            self._settings_status.setText("Please enter an API key before saving.")
            return
        rspace.save_credentials(key, url)
        rspace.save_lab_group(self._settings_lab_group.text().strip() or rspace.LAB_GROUP)
        self._settings_status.setText("Saved. Reloading folders…")
        self._set_status("Credentials saved — reloading folders…")
        self._run(rspace.create_tree, self._on_folders_loaded)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("RSpace Interface")
    # Use the Fusion style on every OS so the layout and widget sizes look the
    # same on macOS, Windows and Linux (the native macOS style in particular
    # sized form fields and fonts very differently).
    app.setStyle("Fusion")
    win = RSpaceGUI()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
