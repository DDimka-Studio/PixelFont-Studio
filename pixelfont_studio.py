#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PixelFont Studio — a pixel font editor for 8x8 / 16x16 / 32x32 fonts.

Glyphs are NOT auto-generated for a fixed alphabet. Each project keeps an
explicit glyph registry (Unicode code point -> file name) that the user
builds by hand: add a letter, a punctuation mark, a quote, a space glyph,
or any other Unicode character via the "+ Add" button in the left panel,
picking it either by typing it, by its hex code point, or by browsing a
Unicode table grouped by block/category.

Every glyph is stored as a separate .svg file, which can be edited with
any editor and loaded back in.
Export formats: .otf, .ttf, .ttc, .bdf, .h

Existing fonts (e.g. Monocraft) can also be imported: pick a .ttf/.otf
file via "⬇ Import Font", choose a size and a set of characters, and
each imported glyph is rasterized into the grid so it can be edited and
saved like any hand-drawn glyph. See README.md for details.

Dependencies:
    pip install -r requirements.txt
    (PyQt6, fonttools, Pillow — see requirements.txt)

Run:
    python pixelfont_studio.py
"""

import json
import os
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QKeySequence, QPalette, QPainter
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QMessageBox,
    QPushButton, QSplitter, QVBoxLayout, QWidget,
)

try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

SVG_NS = "http://www.w3.org/2000/svg"
SIZES = [8, 16, 32]

# The starting glyph set for a brand-new project — a convenient default,
# not a hard limit. Anything else (punctuation, quotes, space, currency
# signs, other scripts...) is added on demand through the "+ Add" dialog.
DEFAULT_LATIN = [chr(c) for c in range(65, 91)] + [chr(c) for c in range(97, 123)]

# Unicode blocks offered in the "Browse Unicode table" picker, grouped
# roughly by script/category so the user can find a symbol by "language
# or category" instead of hunting for the exact code point.
UNICODE_BLOCKS = [
    ("Basic Latin (ASCII)", 0x0020, 0x007E),
    ("Latin-1 Supplement", 0x00A0, 0x00FF),
    ("Latin Extended-A", 0x0100, 0x017F),
    ("Latin Extended-B", 0x0180, 0x024F),
    ("Greek and Coptic", 0x0370, 0x03FF),
    ("Cyrillic", 0x0400, 0x04FF),
    ("Cyrillic Supplement", 0x0500, 0x052F),
    ("Hebrew", 0x0590, 0x05FF),
    ("Arabic", 0x0600, 0x06FF),
    ("General Punctuation", 0x2000, 0x206F),
    ("Superscripts and Subscripts", 0x2070, 0x209F),
    ("Currency Symbols", 0x20A0, 0x20CF),
    ("Letterlike Symbols", 0x2100, 0x214F),
    ("Number Forms", 0x2150, 0x218F),
    ("Arrows", 0x2190, 0x21FF),
    ("Mathematical Operators", 0x2200, 0x22FF),
    ("Box Drawing", 0x2500, 0x257F),
    ("Block Elements", 0x2580, 0x259F),
    ("Geometric Shapes", 0x25A0, 0x25FF),
    ("Miscellaneous Symbols", 0x2600, 0x26FF),
    ("Dingbats", 0x2700, 0x27BF),
]

_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_LEGACY_SVG_RE = re.compile(r'^([0-9A-Fa-f]+)_(.+)\.svg$')


def sanitize_filename(name):
    name = _BAD_FILENAME_CHARS.sub("_", name.strip())
    return name.strip(". ")


def default_filename(cp):
    """A readable, collision-safe default name: hex code point + a hint."""
    ch = chr(cp)
    if ch == " ":
        hint = "space"
    elif ch.isprintable() and not _BAD_FILENAME_CHARS.search(ch):
        hint = ch
    else:
        hint = f"u{cp:04X}"
    return f"{cp:04X}_{hint}"


def default_glyph_entries():
    return [{"codepoint": ord(ch), "filename": default_filename(ord(ch))} for ch in DEFAULT_LATIN]


def discover_legacy_glyphs(project_dir):
    """Older projects had no glyph registry — their .svg files were named
    '{HEX}_{char}.svg'. Reconstruct a registry from those file names so
    existing projects keep working after upgrading."""
    found = {}
    for s in SIZES:
        d = os.path.join(project_dir, f"size_{s}")
        if not os.path.isdir(d):
            continue
        for fname in os.listdir(d):
            m = _LEGACY_SVG_RE.match(fname)
            if m:
                cp = int(m.group(1), 16)
                found[cp] = fname[:-4]  # strip ".svg"
    return [{"codepoint": cp, "filename": base} for cp, base in sorted(found.items())]


# ================================================================ theme / appearance settings

SETTINGS_DIR = os.path.join(os.path.expanduser("~"), ".pixelfont_studio")
SETTINGS_PATH = os.path.join(SETTINGS_DIR, "settings.json")

DEFAULT_THEME = {
    "accent": "#6d4aff",       # accent / button color
    "bg_window": "#0d0d14",    # window background
    "bg_base": "#15151f",      # input field background
    "bg_panel": "#1a1a27",     # panel/card background
    "border": "#2a2a40",
    "text": "#e8e8f2",
    "text_dim": "#8a8aa0",
    # colors of the drawing canvas
    "canvas_bg": "#ffffff",        # background = "nothing selected"
    "canvas_fg": "#000000",        # filled-in pixel
    "canvas_grid": "#d5d5d5",      # regular grid lines
    "canvas_grid_major": "#9a9aa5",  # grid lines every 8 cells
    "canvas_hover": "#cfe3ff",     # highlight for the cell under the cursor
}


def load_theme():
    theme = DEFAULT_THEME.copy()
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in theme:
                    theme[k] = v
        except (OSError, json.JSONDecodeError):
            pass
    return theme


def save_theme(theme):
    os.makedirs(SETTINGS_DIR, exist_ok=True)
    with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
        json.dump(theme, f, ensure_ascii=False, indent=2)


# THEME — a shared mutable dict: widgets read colors from it on every
# repaint, so changing settings is reflected in the UI immediately.
THEME = load_theme()


def build_stylesheet(t):
    return f"""
    QMainWindow, QDialog {{
        background-color: {t['bg_window']};
    }}
    QWidget {{
        color: {t['text']};
        font-size: 13px;
    }}
    QFrame.card {{
        background-color: {t['bg_panel']};
        border: 1px solid {t['border']};
        border-radius: 10px;
    }}
    QGroupBox {{
        background-color: {t['bg_panel']};
        border: 1px solid {t['border']};
        border-radius: 10px;
        margin-top: 14px;
        padding: 10px 8px 8px 8px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 4px;
        color: {t['text_dim']};
    }}
    QLabel {{
        background: transparent;
        border: none;
    }}
    QLabel[role="dim"] {{
        color: {t['text_dim']};
    }}
    QPushButton {{
        background-color: {t['bg_base']};
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 7px 14px;
    }}
    QPushButton:hover {{
        border-color: {t['accent']};
        background-color: #201f33;
    }}
    QPushButton:pressed {{
        background-color: #282743;
    }}
    QPushButton:disabled {{
        color: {t['text_dim']};
        border-color: {t['border']};
    }}
    QPushButton[role="accent"] {{
        background-color: {t['accent']};
        color: white;
        border: none;
        font-weight: 700;
        padding: 8px 20px;
    }}
    QPushButton[role="accent"]:hover {{
        background-color: #825fff;
    }}
    QPushButton[role="ghost"] {{
        background: transparent;
        border: none;
        color: {t['text_dim']};
        padding: 7px 8px;
    }}
    QPushButton[role="ghost"]:hover {{
        color: {t['text']};
        border: 1px solid {t['border']};
        border-radius: 8px;
    }}
    QComboBox, QLineEdit {{
        background-color: {t['bg_base']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        padding: 6px 10px;
        selection-background-color: {t['accent']};
    }}
    QComboBox:focus, QLineEdit:focus {{
        border-color: {t['accent']};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {t['bg_base']};
        border: 1px solid {t['border']};
        selection-background-color: #2b2b47;
    }}
    QListWidget {{
        background-color: {t['bg_base']};
        border: 1px solid {t['border']};
        border-radius: 8px;
        outline: none;
    }}
    QListWidget::item {{
        padding: 4px 6px;
        border-radius: 4px;
    }}
    QListWidget::item:selected {{
        background-color: {t['accent']};
        color: white;
    }}
    QCheckBox {{
        spacing: 8px;
        padding: 2px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {t['border']};
        background-color: {t['bg_base']};
    }}
    QCheckBox::indicator:checked {{
        background-color: {t['accent']};
        border-color: {t['accent']};
    }}
    QStatusBar {{
        background-color: {t['bg_panel']};
        border-top: 1px solid {t['border']};
        color: {t['text_dim']};
    }}
    QSplitter::handle {{
        background-color: {t['bg_window']};
    }}
    """


def apply_theme(app, theme):
    pal = QPalette()
    pal.setColor(QPalette.ColorRole.Window, QColor(theme["bg_window"]))
    pal.setColor(QPalette.ColorRole.Base, QColor(theme["bg_base"]))
    pal.setColor(QPalette.ColorRole.Text, QColor(theme["text"]))
    pal.setColor(QPalette.ColorRole.Button, QColor(theme["bg_panel"]))
    pal.setColor(QPalette.ColorRole.ButtonText, QColor(theme["text"]))
    pal.setColor(QPalette.ColorRole.Highlight, QColor(theme["accent"]))
    pal.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    pal.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(theme["text_dim"]))
    app.setPalette(pal)
    app.setStyleSheet(build_stylesheet(theme))


# ================================================================ settings dialog

class SettingsDialog(QDialog):
    """Lets the user change button, background, and canvas colors."""

    FIELDS = [
        ("accent", "Accent / buttons"),
        ("bg_window", "Window background"),
        ("bg_panel", "Panel background"),
        ("bg_base", "Input field background"),
        ("border", "Element border"),
        ("text", "Text"),
        ("canvas_bg", "Canvas background"),
        ("canvas_fg", "Filled pixel color"),
    ]

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Appearance Settings")
        self.setMinimumWidth(360)
        self.theme = theme.copy()
        self.swatches = {}

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        hint = QLabel("Click a color swatch to change it.")
        hint.setProperty("role", "dim")
        lay.addWidget(hint)

        for key, label in self.FIELDS:
            row = QHBoxLayout()
            lab = QLabel(label)
            row.addWidget(lab, 1)
            swatch = QPushButton()
            swatch.setFixedSize(64, 26)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.clicked.connect(lambda _checked, k=key: self._pick_color(k))
            self._paint_swatch(swatch, self.theme[key])
            self.swatches[key] = swatch
            row.addWidget(swatch)
            lay.addLayout(row)

        reset_btn = QPushButton("Reset to defaults")
        reset_btn.setProperty("role", "ghost")
        reset_btn.clicked.connect(self._reset)
        lay.addWidget(reset_btn)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "accent")
        lay.addWidget(bb)

    def _paint_swatch(self, btn, color_hex):
        btn.setStyleSheet(
            f"background-color: {color_hex}; border: 1px solid #444; border-radius: 6px;"
        )

    def _pick_color(self, key):
        current = QColor(self.theme[key])
        c = QColorDialog.getColor(current, self, "Choose a color")
        if c.isValid():
            self.theme[key] = c.name()
            self._paint_swatch(self.swatches[key], c.name())

    def _reset(self):
        self.theme = DEFAULT_THEME.copy()
        for key, btn in self.swatches.items():
            self._paint_swatch(btn, self.theme[key])

    def get_theme(self):
        return self.theme


# ================================================================ Unicode table picker

class UnicodeLookupDialog(QDialog):
    """Browse Unicode characters by block/category, with a name search,
    so the user can find the exact code point of a symbol without
    knowing it up front."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Unicode Character Table")
        self.resize(480, 520)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        row = QHBoxLayout()
        lab = QLabel("Category:")
        lab.setProperty("role", "dim")
        row.addWidget(lab)
        self.block_combo = QComboBox()
        for name, start, end in UNICODE_BLOCKS:
            self.block_combo.addItem(name, (start, end))
        row.addWidget(self.block_combo, 1)
        lay.addLayout(row)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Search by Unicode name (e.g. \"quote\", \"arrow\")…")
        lay.addWidget(self.search_edit)

        self.list = QListWidget()
        lay.addWidget(self.list, 1)

        self.count_label = QLabel()
        self.count_label.setProperty("role", "dim")
        lay.addWidget(self.count_label)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "accent")
        lay.addWidget(bb)

        self.block_combo.currentIndexChanged.connect(self._refresh)
        self.search_edit.textChanged.connect(self._refresh)
        self.list.itemDoubleClicked.connect(self.accept)
        self._refresh()

    def _refresh(self):
        self.list.clear()
        start, end = self.block_combo.currentData()
        query = self.search_edit.text().strip().lower()
        shown = 0
        for cp in range(start, end + 1):
            ch = chr(cp)
            try:
                name = unicodedata.name(ch)
            except ValueError:
                continue  # unassigned code point
            if unicodedata.category(ch).startswith("C"):
                continue  # control / format / surrogate / unassigned-ish
            if query and query not in name.lower():
                continue
            item = QListWidgetItem(f"U+{cp:04X}   {ch}   {name}")
            item.setData(Qt.ItemDataRole.UserRole, cp)
            self.list.addItem(item)
            shown += 1
        self.count_label.setText(f"{shown} character(s)")
        if self.list.count():
            self.list.setCurrentRow(0)

    def selected_char(self):
        item = self.list.currentItem()
        if item:
            return chr(item.data(Qt.ItemDataRole.UserRole))
        return None


# ================================================================ add-glyph dialog

class AddGlyphDialog(QDialog):
    """Lets the user pick a Unicode character (by typing it, by hex code
    point, or via the Unicode table) and give the underlying .svg file a
    name of their choosing."""

    def __init__(self, existing_codepoints, existing_filenames, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Glyph")
        self.setMinimumWidth(380)
        self.existing_codepoints = existing_codepoints
        self.existing_filenames = existing_filenames

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        lab = QLabel("Character:")
        lab.setProperty("role", "dim")
        lay.addWidget(lab)
        char_row = QHBoxLayout()
        self.char_edit = QLineEdit()
        self.char_edit.setMaxLength(1)
        self.char_edit.setFixedWidth(60)
        char_row.addWidget(self.char_edit)
        self.info_label = QLabel("—")
        char_row.addWidget(self.info_label, 1)
        lay.addLayout(char_row)

        hex_row = QHBoxLayout()
        lab = QLabel("…or code point U+")
        lab.setProperty("role", "dim")
        hex_row.addWidget(lab)
        self.hex_edit = QLineEdit()
        self.hex_edit.setPlaceholderText("2022")
        self.hex_edit.setFixedWidth(80)
        hex_row.addWidget(self.hex_edit)
        use_hex_btn = QPushButton("Use")
        use_hex_btn.clicked.connect(self._use_hex)
        hex_row.addWidget(use_hex_btn)
        hex_row.addStretch()
        lay.addLayout(hex_row)

        browse_btn = QPushButton("🔎 Browse Unicode table…")
        browse_btn.clicked.connect(self._open_lookup)
        lay.addWidget(browse_btn)

        lab = QLabel("File name (used on disk, not shown to font users):")
        lab.setProperty("role", "dim")
        lay.addWidget(lab)
        self.filename_edit = QLineEdit()
        lay.addWidget(self.filename_edit)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        self.ok_button = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "accent")
        lay.addWidget(bb)

        self.char_edit.textChanged.connect(self._char_changed)
        self.filename_edit.textChanged.connect(self._validate)
        self._validate()

    def _char_changed(self, text):
        if text:
            cp = ord(text)
            try:
                name = unicodedata.name(text)
            except ValueError:
                name = "(unnamed code point)"
            self.info_label.setText(f"U+{cp:04X}  {name}")
            if not self.filename_edit.text().strip():
                self.filename_edit.setText(default_filename(cp))
        else:
            self.info_label.setText("—")
        self._validate()

    def _use_hex(self):
        text = self.hex_edit.text().strip().lstrip("Uu+")
        try:
            cp = int(text, 16)
            if not (0 <= cp <= 0xFFFF):
                raise ValueError
        except ValueError:
            QMessageBox.warning(self, "Invalid code point",
                               "Enter a valid hexadecimal code point in the Basic "
                               "Multilingual Plane, e.g. 2022 for •.")
            return
        self.char_edit.setText(chr(cp))

    def _open_lookup(self):
        dlg = UnicodeLookupDialog(self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            ch = dlg.selected_char()
            if ch:
                self.char_edit.setText(ch)

    def _validate(self):
        text = self.char_edit.text()
        ok = bool(text)
        msg = ""
        if ok:
            cp = ord(text)
            if cp in self.existing_codepoints:
                ok = False
                msg = "This character is already in the project's glyph list."
        fname = sanitize_filename(self.filename_edit.text())
        if ok and not fname:
            ok = False
            msg = "Enter a file name."
        self.error_label.setText(msg)
        self.ok_button.setEnabled(ok)

    def get_result(self):
        cp = ord(self.char_edit.text())
        fname = sanitize_filename(self.filename_edit.text()) or default_filename(cp)
        base, i = fname, 1
        while fname.lower() in self.existing_filenames:
            i += 1
            fname = f"{base}_{i}"
        return cp, fname


# ================================================================ startup dialogs

# ================================================================ import-font dialog

class ImportFontDialog(QDialog):
    """Lets the user pick an existing .ttf/.otf font file, a target grid
    size, and a set of characters. Only used to *collect the request* —
    the actual rasterization happens in MainWindow.import_font()."""

    def __init__(self, current_size, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Import Font")
        self.setMinimumWidth(420)

        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        lab = QLabel("Font file (.ttf / .otf):")
        lab.setProperty("role", "dim")
        lay.addWidget(lab)
        file_row = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("e.g. Monocraft.ttf")
        file_row.addWidget(self.file_edit, 1)
        browse_btn = QPushButton("…")
        browse_btn.clicked.connect(self._browse)
        file_row.addWidget(browse_btn)
        lay.addLayout(file_row)

        lab = QLabel("Grid size:")
        lab.setProperty("role", "dim")
        lay.addWidget(lab)
        self.size_combo = QComboBox()
        for s in SIZES:
            self.size_combo.addItem(f"{s}×{s}", s)
        idx = self.size_combo.findData(current_size)
        if idx >= 0:
            self.size_combo.setCurrentIndex(idx)
        lay.addWidget(self.size_combo)

        lab = QLabel("Characters to import:")
        lab.setProperty("role", "dim")
        lay.addWidget(lab)
        self.chars_edit = QLineEdit("".join(IMPORT_DEFAULT_CHARS))
        lay.addWidget(self.chars_edit)
        hint = QLabel("Each character here becomes one glyph. Remove or add "
                      "characters freely — duplicates and characters missing "
                      "from the font are skipped automatically.")
        hint.setProperty("role", "dim")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.skip_existing = QCheckBox("Skip characters already in the project")
        self.skip_existing.setChecked(True)
        lay.addWidget(self.skip_existing)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.setWordWrap(True)
        lay.addWidget(self.error_label)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self._try_accept)
        bb.rejected.connect(self.reject)
        self.ok_button = bb.button(QDialogButtonBox.StandardButton.Ok)
        self.ok_button.setProperty("role", "accent")
        lay.addWidget(bb)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a font file", "", "Fonts (*.ttf *.otf);;All files (*)")
        if path:
            self.file_edit.setText(path)

    def _try_accept(self):
        if not PIL_AVAILABLE:
            self.error_label.setText(
                "Pillow is not installed. Run: pip install Pillow "
                "(or: pip install -r requirements.txt)")
            return
        path = self.file_edit.text().strip()
        if not path or not os.path.isfile(path):
            self.error_label.setText("Choose a valid font file.")
            return
        if not self.chars_edit.text():
            self.error_label.setText("Enter at least one character to import.")
            return
        self.accept()

    def get_result(self):
        # De-duplicate while preserving order.
        seen = set()
        chars = []
        for ch in self.chars_edit.text():
            if ch not in seen:
                seen.add(ch)
                chars.append(ch)
        return {
            "font_path": self.file_edit.text().strip(),
            "size": self.size_combo.currentData(),
            "chars": chars,
            "skip_existing": self.skip_existing.isChecked(),
        }


class StartDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("PixelFont Studio — Get Started")
        self.setFixedSize(400, 240)
        self.last_config = None

        # Widgets
        self.label = QLabel("Choose an action:")
        self.new_project_btn = QPushButton("Create a new project")
        self.new_project_btn.setProperty("role", "accent")
        self.open_project_btn = QPushButton("Open an existing project")
        self.settings_btn = QPushButton("⚙ Settings")
        self.settings_btn.setProperty("role", "ghost")

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.label)
        layout.addWidget(self.new_project_btn)
        layout.addWidget(self.open_project_btn)
        layout.addStretch()
        layout.addWidget(self.settings_btn)
        self.setLayout(layout)

        # Connections
        self.new_project_btn.clicked.connect(self.create_new_project)
        self.open_project_btn.clicked.connect(self.open_existing_project)
        self.settings_btn.clicked.connect(self.open_settings)

    def open_settings(self):
        dlg = SettingsDialog(THEME, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            THEME.update(dlg.get_theme())
            save_theme(THEME)
            app = QApplication.instance()
            if app is not None:
                apply_theme(app, THEME)

    def create_new_project(self):
        dialog = NewProjectDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            project_name, base_path, font_size = dialog.get_project_info()
            if project_name and base_path:
                project_path = os.path.join(base_path, project_name)
                self.create_directories(base_path, project_name)
                self.save_config(project_path, project_name, font_size)
                # STORE THE RESULT SO THE MAIN WINDOW CAN OPEN THE PROJECT RIGHT AWAY
                self.last_config = {"project_path": project_path, "font_size": font_size}
                self.accept()

    def open_existing_project(self):
        project_path = QFileDialog.getExistingDirectory(self, "Select the project directory")
        if project_path:
            if self.validate_project_structure(project_path):
                config = self.load_config(project_path) or {}
                self.last_config = {"project_path": project_path,
                                    "font_size": config.get("font_size")}
                self.accept()
            else:
                QMessageBox.warning(self, "Error", "The selected directory does not contain an out folder.")

    def save_config(self, project_path, project_name, font_size):
        # The config is stored inside the project folder itself (project_path),
        # not in the parent folder — otherwise it wouldn't match the out folder.
        os.makedirs(project_path, exist_ok=True)
        config = {
            "project_name": project_name,
            "project_path": project_path,
            "font_size": font_size,
            "glyphs": default_glyph_entries(),
        }
        config_path = os.path.join(project_path, "config.json")
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, ensure_ascii=False, indent=4)

    def load_config(self, project_path):
        config_path = os.path.join(project_path, "config.json")
        if os.path.exists(config_path):
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        return None

    def create_directories(self, base_path, project_name):
        project_path = os.path.join(base_path, project_name)
        os.makedirs(os.path.join(project_path, "out"), exist_ok=True)

    def validate_project_structure(self, project_path):
        return os.path.exists(os.path.join(project_path, "out"))


class NewProjectDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Create a New Project")
        self.setFixedSize(400, 220)

        # Widgets
        self.name_label = QLabel("Project name:")
        self.name_edit = QLineEdit()

        self.path_label = QLabel("Directory:")
        self.path_edit = QLineEdit()
        self.path_btn = QPushButton("...")

        self.size_label = QLabel("Font size:")
        self.size_combo = QComboBox()
        self.size_combo.addItems([str(s) for s in SIZES])

        self.ok_btn = QPushButton("Create")
        self.ok_btn.setProperty("role", "accent")
        self.cancel_btn = QPushButton("Cancel")

        # Layout
        layout = QVBoxLayout()
        layout.addWidget(self.name_label)
        layout.addWidget(self.name_edit)
        layout.addWidget(self.path_label)

        path_layout = QHBoxLayout()
        path_layout.addWidget(self.path_edit)
        path_layout.addWidget(self.path_btn)
        layout.addLayout(path_layout)

        layout.addWidget(self.size_label)
        layout.addWidget(self.size_combo)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.ok_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # Connections
        self.path_btn.clicked.connect(self.choose_directory)
        self.ok_btn.clicked.connect(self.accept)
        self.cancel_btn.clicked.connect(self.reject)

    def choose_directory(self):
        directory = QFileDialog.getExistingDirectory(self, "Choose a directory")
        if directory:
            self.path_edit.setText(directory)

    def get_project_info(self):
        return (
            self.name_edit.text().strip(),
            self.path_edit.text().strip(),
            int(self.size_combo.currentText()),
        )


# ================================================================ glyph grid

class GlyphGrid:
    def __init__(self, size):
        self.size = size
        self.px = [[False] * size for _ in range(size)]

    def set(self, x, y, v):
        if 0 <= x < self.size and 0 <= y < self.size:
            self.px[y][x] = v

    def get(self, x, y):
        return self.px[y][x]

    def clone(self):
        g = GlyphGrid(self.size)
        g.px = [row[:] for row in self.px]
        return g

    def invert(self):
        self.px = [[not v for v in row] for row in self.px]

    def shift(self, dx, dy):
        new = [[False] * self.size for _ in range(self.size)]
        for y in range(self.size):
            for x in range(self.size):
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.size and 0 <= ny < self.size:
                    new[ny][nx] = self.px[y][x]
        self.px = new


# ================================================================ SVG

def glyph_to_svg(grid, char):
    ET.register_namespace("", SVG_NS)
    root = ET.Element("svg", {
        "xmlns": SVG_NS,
        "width": str(grid.size),
        "height": str(grid.size),
        "viewBox": f"0 0 {grid.size} {grid.size}",
        "shape-rendering": "crispEdges",
    })
    # Use a safe label in the comment: some glyphs (space, control-ish
    # punctuation) don't render usefully as a literal character.
    label = char if char.isprintable() and not char.isspace() else f"U+{ord(char):04X}"
    root.append(ET.Comment(f" Glyph '{label}' ({grid.size}x{grid.size}) "))
    for y in range(grid.size):
        for x in range(grid.size):
            if grid.get(x, y):
                ET.SubElement(root, "rect", {
                    "x": str(x), "y": str(y), "width": "1", "height": "1",
                })
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def svg_to_glyph(path, expected_size):
    root = ET.parse(path).getroot()
    vb = (root.get("viewBox") or f"0 0 {expected_size} {expected_size}").split()
    scale = expected_size / (float(vb[2]) or 1)
    grid = GlyphGrid(expected_size)
    for r in root.iter(f"{{{SVG_NS}}}rect"):
        x = float(r.get("x", 0)) * scale
        y = float(r.get("y", 0)) * scale
        x1 = x + float(r.get("width", 1)) * scale
        y1 = y + float(r.get("height", 1)) * scale
        for gx in range(max(0, int(round(x))), min(expected_size, int(round(x1)))):
            for gy in range(max(0, int(round(y))), min(expected_size, int(round(y1)))):
                grid.px[gy][gx] = True
    return grid


# ================================================================ font import

# A reasonable default character set for a first import pass: the same
# Latin letters new projects start with, plus digits and the punctuation
# a monospace/pixel font like Monocraft typically ships with. The user
# can edit this list freely in the Import Font dialog.
IMPORT_DEFAULT_CHARS = (
    DEFAULT_LATIN
    + list("0123456789")
    + list(" .,:;!?'\"-_/\\()[]{}+=*<>@#$%^&~`|")
)


def font_cmap_codepoints(font_path):
    """Code points the font actually has glyphs for, via its cmap.
    Used to skip characters that would just import as a blank/notdef box."""
    from fontTools.ttLib import TTFont
    font = TTFont(font_path, fontNumber=0, lazy=True)
    try:
        cmap = font.getBestCmap() or {}
        return set(cmap.keys())
    finally:
        font.close()


def rasterize_char(font_path, ch, size, supersample=8):
    """Render one character from an installed/loaded font file into a
    size x size boolean grid. Renders at a supersampled resolution and
    box-downsamples, which handles both smooth and already-pixelated
    source fonts reasonably well; the result is a starting point meant
    to be touched up by hand, not a pixel-perfect conversion."""
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is not installed (pip install Pillow)")
    px = max(size * supersample, 8)
    font = ImageFont.truetype(font_path, px)
    img = Image.new("L", (px, px), 0)
    draw = ImageDraw.Draw(img)
    bbox = draw.textbbox((0, 0), ch, font=font)
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (px - w) // 2 - bbox[0]
    y = (px - h) // 2 - bbox[1]
    draw.text((x, y), ch, font=font, fill=255)
    img = img.resize((size, size), Image.LANCZOS)
    data = img.load()
    grid = GlyphGrid(size)
    for gy in range(size):
        for gx in range(size):
            grid.px[gy][gx] = data[gx, gy] > 127
    return grid


# ================================================================ bit packing

def _packed_rows(grid):
    """Pixel rows top to bottom, MSB-first, byte-aligned."""
    bpr = grid.size // 8
    out = []
    for row in grid.px:
        b = bytearray(bpr)
        for x, v in enumerate(row):
            if v:
                b[x // 8] |= 0x80 >> (x % 8)
        out.append(bytes(b))
    return out


# ================================================================ export: .h

def export_h(entries, grids_by_size, path):
    L = [
        "// Generated by PixelFont Studio",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "// Rows go top->bottom, bits packed MSB-first.",
        "// Glyph order matches the *_codepoints[] array below — the",
        "// glyph set is project-defined, not a fixed alphabet.",
        "",
    ]
    n = len(entries)
    for s in SIZES:
        grids = grids_by_size[s]
        total = s * s // 8
        L += [
            f"#define PIXFONT_{s}x{s}_CHARS {n}",
            f"#define PIXFONT_{s}x{s}_W {s}",
            f"#define PIXFONT_{s}x{s}_H {s}",
            f"static const uint32_t pixfont_{s}x{s}_codepoints[{n}] = {{",
            "    " + ", ".join(f"0x{e['codepoint']:04X}" for e in entries),
            "};",
            f"static const uint8_t pixfont_{s}x{s}[{n}][{total}] = {{",
        ]
        for e in entries:
            cp = e["codepoint"]
            grid = grids.get(cp) or GlyphGrid(s)
            rows = ["0x" + "".join(f"{b:02X}" for b in r) for r in _packed_rows(grid)]
            ch = chr(cp)
            label = ch if ch.isprintable() and not ch.isspace() else f"U+{cp:04X}"
            L.append(f"    /* '{label}' 0x{cp:04X} */ {{ {','.join(rows)} }},")
        L += ["};", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ================================================================ export: .bdf

def export_bdf(entries, size, grids, path):
    L = [
        "STARTFONT 2.1",
        f"FONT -PixelFont-Regular-R-Normal--{size}-{size * 10}-75-75-P-{size * 10}-ISO10646-1",
        f"SIZE {size} 75 75",
        f"FONTBOUNDINGBOX {size} {size} 0 0",
        "STARTPROPERTIES 2",
        f"FONT_ASCENT {size}",
        "FONT_DESCENT 0",
        "ENDPROPERTIES",
        f"CHARS {len(entries)}",
    ]
    for e in entries:
        cp = e["codepoint"]
        grid = grids.get(cp, GlyphGrid(size))
        # Always use a "uniXXXX" glyph name: literal characters (spaces,
        # quotes, non-ASCII symbols) are not valid/safe BDF glyph names.
        L += [
            f"STARTCHAR uni{cp:04X}",
            f"ENCODING {cp}",
            "SWIDTH 1000 0",
            f"DWIDTH {size} 0",
            f"BBX {size} {size} 0 0",
            "BITMAP",
        ]
        L += ["0x" + "".join(f"{b:02X}" for b in row) for row in _packed_rows(grid)]
        L.append("ENDCHAR")
    L.append("ENDFONT")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")


# ================================================================ export: .otf / .ttf / .ttc

def export_vector_font(entries, size, grids, path):
    try:
        from fontTools.fontBuilder import FontBuilder
        from fontTools.pens.ttGlyphPen import TTGlyphPen
        from fontTools.pens.t2CharStringPen import T2CharStringPen
    except ImportError:
        raise RuntimeError("fonttools is required:  pip install fonttools")

    is_ttf = not path.lower().endswith(".otf")
    upem = 1024
    k = upem / size
    order, cmap, hm, glyphs = [], {}, {}, {}
    for e in entries:
        cp = e["codepoint"]
        name = f"uni{cp:04X}"
        order.append(name)
        cmap[cp] = name
        hm[name] = (upem, 0)
        grid = grids.get(cp, GlyphGrid(size))
        rects = []
        for y in range(size):
            for x in range(size):
                if grid.get(x, y):
                    rects.append((round(x * k), round((size - 1 - y) * k),
                                  round((x + 1) * k), round((size - y) * k)))
        if is_ttf:
            pen = TTGlyphPen(None)
            for x0, y0, x1, y1 in rects:
                pen.moveTo((x0, y0)); pen.lineTo((x1, y0))
                pen.lineTo((x1, y1)); pen.lineTo((x0, y1))
                pen.closePath()
            glyphs[name] = pen.glyph()
        else:
            cs_pen = T2CharStringPen(upem, None)
            for x0, y0, x1, y1 in rects:
                cs_pen.moveTo((x0, y0)); cs_pen.lineTo((x1, y0))
                cs_pen.lineTo((x1, y1)); cs_pen.lineTo((x0, y1))
                cs_pen.closePath()
            glyphs[name] = cs_pen.getCharString()

    fb = FontBuilder(upem, isTTF=is_ttf)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    if is_ttf:
        fb.setupGlyf(glyphs)
    else:
        fb.setupCFF("PixelFont", {}, glyphs, {})
    fb.setupHorizontalMetrics(hm)
    fb.setupHorizontalHeader(ascent=upem, descent=0)
    fb.setupNameTable({"familyName": f"PixelFont {size}px", "styleName": "Regular"})
    fb.setupOS2(sTypoAscender=upem, sTypoDescender=0, usWinAscent=upem, usWinDescent=0)
    fb.setupPost()
    fb.save(path)


def export_ttf(entries, size, grids, path):
    """Plain .ttf — same engine, correct extension."""
    export_vector_font(entries, size, grids, path)


def build_ttc(ttf_paths, out_path):
    """Merges several .ttf files into a single .ttc (TrueType Collection)."""
    try:
        from fontTools.ttLib import TTFont, TTCollection
    except ImportError:
        raise RuntimeError("fonttools is required:  pip install fonttools")
    coll = TTCollection()
    coll.fonts = [TTFont(p) for p in ttf_paths]
    coll.save(out_path)


# ================================================================ grid editor

class GridEditor(QWidget):
    gridChanged = pyqtSignal()
    strokeStarted = pyqtSignal()  # emitted once at the start of drawing/erasing — used for undo

    def __init__(self):
        super().__init__()
        self.setMinimumSize(360, 360)
        self.setMouseTracking(True)
        self.grid = GlyphGrid(8)
        self.hover = None  # (x, y) cell under the cursor
        self._drawing = False

    def set_grid(self, g):
        self.grid = g.clone()
        self.update()

    def get_grid(self):
        return self.grid.clone()

    def _geometry(self):
        n = self.grid.size
        cw = min(self.width(), self.height()) / n
        ox = (self.width() - cw * n) / 2
        oy = (self.height() - cw * n) / 2
        return n, cw, ox, oy

    def _cell(self, pos):
        n, cw, ox, oy = self._geometry()
        x, y = int((pos.x() - ox) // cw), int((pos.y() - oy) // cw)
        return (x, y) if 0 <= x < n and 0 <= y < n else None

    def mousePressEvent(self, e):
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
            # A single signal at the start of the stroke — MainWindow snapshots
            # the state beforehand, so Ctrl+Z can undo the drawing too.
            self._drawing = True
            self.strokeStarted.emit()
        self._paint(e)

    def mouseReleaseEvent(self, e):
        self._drawing = False

    def mouseMoveEvent(self, e):
        c = self._cell(e.position())
        if c != self.hover:
            self.hover = c
            self.update()
        self._paint(e)

    def leaveEvent(self, _):
        self.hover = None
        self.update()

    def _paint(self, e):
        if e.buttons() & Qt.MouseButton.LeftButton:
            v = True
        elif e.buttons() & Qt.MouseButton.RightButton:
            v = False
        else:
            return
        c = self._cell(e.position())
        if c:
            self.grid.set(*c, v)
            self.update()
            self.gridChanged.emit()

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME["bg_window"]))
        n, cw, ox, oy = self._geometry()

        # the canvas itself: white background = nothing selected
        p.fillRect(int(ox), int(oy), int(cw * n), int(cw * n), QColor(THEME["canvas_bg"]))

        # highlight the cell under the cursor
        if self.hover:
            hx, hy = self.hover
            p.fillRect(int(ox + hx * cw), int(oy + hy * cw),
                      int(cw), int(cw), QColor(THEME["canvas_hover"]))

        # filled-in pixels — black (or whatever the settings define)
        for y in range(n):
            for x in range(n):
                if self.grid.get(x, y):
                    p.fillRect(int(ox + x * cw), int(oy + y * cw),
                               int(cw) + 1, int(cw) + 1, QColor(THEME["canvas_fg"]))

        # grid lines: adapt to the current size (8/16/32...),
        # every 8th line is bolder to help with orientation on large grids
        for i in range(n + 1):
            col = QColor(THEME["canvas_grid_major"]) if i % 8 == 0 else QColor(THEME["canvas_grid"])
            p.setPen(col)
            p.drawLine(int(ox), int(oy + i * cw), int(ox + n * cw), int(oy + i * cw))
            p.drawLine(int(ox + i * cw), int(oy), int(ox + i * cw), int(oy + n * cw))


# ================================================================ preview

class PreviewWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumHeight(160)
        self.provider = lambda ch, s: None
        self.size_variant = 8
        self.text = "Hello!"

    def paintEvent(self, _):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(THEME["canvas_bg"]))
        n = self.size_variant
        scale = max(1, min(8, (self.width() - 16) // max(1, len(self.text)) // n))
        cell = n * scale
        x = 8
        for ch in self.text:
            g = self.provider(ch, n)
            if g:
                for gy in range(n):
                    for gx in range(n):
                        if g.get(gx, gy):
                            p.fillRect(x + gx * scale, 12 + gy * scale,
                                       scale, scale, QColor(THEME["canvas_fg"]))
            x += cell + scale
            if x > self.width() - cell:
                break


# ================================================================ build dialog

class BuildDialog(QDialog):
    def __init__(self, default_out=""):
        super().__init__()
        self.setWindowTitle("Build Font")
        self.setMinimumWidth(480)
        lay = QVBoxLayout(self)
        lay.setSpacing(12)

        head = QLabel("Export formats")
        head.setProperty("role", "dim")
        lay.addWidget(head)

        fmt_box = QGroupBox("Output formats (at least one)")
        fbl = QVBoxLayout(fmt_box)
        fbl.setSpacing(6)
        self.cb_otf = QCheckBox(".otf — vector font (one file per size)")
        self.cb_ttf = QCheckBox(".ttf — TrueType (one file per size)")
        self.cb_ttc = QCheckBox(".ttc — TrueType Collection (all sizes in one file)")
        self.cb_bdf = QCheckBox(".bdf — bitmap font (one file per size)")
        self.cb_h = QCheckBox(".h — C header with arrays (for OS / microcontrollers)")
        self.checkboxes = [self.cb_otf, self.cb_ttf, self.cb_ttc, self.cb_bdf, self.cb_h]
        for cb in self.checkboxes:
            cb.setChecked(True)
            cb.toggled.connect(self._validate)
            fbl.addWidget(cb)
        lay.addWidget(fmt_box)

        dir_box = QGroupBox("Output folder")
        dbl = QHBoxLayout(dir_box)
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("Choose a folder for the build results…")
        # Pre-fill with the project's own "out" folder, since it already
        # exists for every project — no need to make the user pick it by hand.
        if default_out:
            self.dir_edit.setText(default_out)
        b = QPushButton("Browse…")
        b.clicked.connect(self._browse)
        dbl.addWidget(self.dir_edit, 1)
        dbl.addWidget(b)
        lay.addWidget(dir_box)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok |
                              QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "accent")
        lay.addWidget(bb)
        self._validate()

    def _validate(self):
        ok = any(cb.isChecked() for cb in self.checkboxes)
        for bb in self.findChildren(QDialogButtonBox):
            bb.button(QDialogButtonBox.StandardButton.Ok).setEnabled(ok)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Output folder")
        if d:
            self.dir_edit.setText(d)

    def results(self):
        return {
            "otf": self.cb_otf.isChecked(),
            "ttf": self.cb_ttf.isChecked(),
            "ttc": self.cb_ttc.isChecked(),
            "bdf": self.cb_bdf.isChecked(),
            "h": self.cb_h.isChecked(),
            "out": self.dir_edit.text(),
        }


# ================================================================ main window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PixelFont Studio")
        self.resize(1150, 720)
        self.project_dir = ""
        self.grids = {}            # (codepoint, size) -> GlyphGrid
        self.glyph_entries = []    # [{"codepoint": int, "filename": str}, ...]
        self.undo_stack = []
        # The glyph/size actually loaded into the editor right now. Kept
        # separately from the widgets' live state so that switching the
        # selection can flush edits to the *previous* glyph, not the new
        # one (see on_selection_change / store_current).
        self._current_key = (None, SIZES[0])

        self._build_ui()
        self._build_shortcuts()
        self.load_project_glyphs()
        self.load_current()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(12)

        # --- toolbar
        tools = QFrame()
        tools.setProperty("class", "card")
        tl = QHBoxLayout(tools)
        tl.setContentsMargins(8, 6, 8, 6)
        tl.setSpacing(4)
        for label, slot, role in [
            ("💾 Save .svg", self.save_glyph, ""),
            ("📂 Open .svg", self.load_glyph, ""),
            ("📁 Project folder…", self.open_project, ""),
            ("⬇ Import Font…", self.import_font, ""),
        ]:
            b = QPushButton(label)
            if role:
                b.setProperty("role", role)
            b.clicked.connect(slot)
            tl.addWidget(b)
        sep = self._vsep()
        tl.addWidget(sep)
        for label, slot in [
            ("⌫ Clear", self.clear_glyph),
            ("⇄ Invert", self.invert_glyph),
            ("◀", lambda: self.do_shift(-1, 0)),
            ("▶", lambda: self.do_shift(1, 0)),
            ("▲", lambda: self.do_shift(0, -1)),
            ("▼", lambda: self.do_shift(0, 1)),
            ("↶ Undo", self.undo_last),
        ]:
            b = QPushButton(label)
            b.setProperty("role", "ghost")
            b.clicked.connect(slot)
            tl.addWidget(b)
        tl.addStretch()

        build_btn = QPushButton("🔨 Build Font")
        build_btn.setProperty("role", "accent")
        build_btn.setShortcut("Ctrl+B")
        build_btn.clicked.connect(self.build_font)
        tl.addWidget(build_btn)
        root.addWidget(tools)

        # --- left panel (glyph/size selection) + editor + preview
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(10)

        # left: size selector + glyph registry list
        glyph_panel = QFrame()
        glyph_panel.setProperty("class", "card")
        gpl = QVBoxLayout(glyph_panel)
        gpl.setContentsMargins(12, 12, 12, 12)
        gpl.setSpacing(8)

        size_row = QHBoxLayout()
        lab = QLabel("Size:")
        lab.setProperty("role", "dim")
        size_row.addWidget(lab)
        self.size_combo = QComboBox()
        for s in SIZES:
            self.size_combo.addItem(f"{s}×{s}", s)
        self.size_combo.currentIndexChanged.connect(self.on_selection_change)
        size_row.addWidget(self.size_combo, 1)
        gpl.addLayout(size_row)

        lab = QLabel("Glyphs")
        lab.setProperty("role", "dim")
        gpl.addWidget(lab)

        self.glyph_search = QLineEdit()
        self.glyph_search.setPlaceholderText("Filter…")
        self.glyph_search.textChanged.connect(lambda _t: self.refresh_glyph_list())
        gpl.addWidget(self.glyph_search)

        self.glyph_list = QListWidget()
        self.glyph_list.currentItemChanged.connect(lambda _c, _p: self.on_selection_change())
        gpl.addWidget(self.glyph_list, 1)

        glyph_btns = QHBoxLayout()
        add_btn = QPushButton("+ Add")
        add_btn.setProperty("role", "accent")
        add_btn.clicked.connect(self.add_glyph)
        remove_btn = QPushButton("− Remove")
        remove_btn.setProperty("role", "ghost")
        remove_btn.clicked.connect(self.remove_glyph)
        glyph_btns.addWidget(add_btn)
        glyph_btns.addWidget(remove_btn)
        gpl.addLayout(glyph_btns)

        split.addWidget(glyph_panel)

        # middle: the drawing canvas
        editor_card = QFrame()
        editor_card.setProperty("class", "card")
        ecl = QVBoxLayout(editor_card)
        ecl.setContentsMargins(10, 10, 10, 10)
        self.editor = GridEditor()
        self.editor.gridChanged.connect(self._edited)
        self.editor.strokeStarted.connect(self.push_undo)
        ecl.addWidget(self.editor, 1)
        split.addWidget(editor_card)

        # right: preview + tips
        side = QFrame()
        side.setProperty("class", "card")
        sdl = QVBoxLayout(side)
        sdl.setContentsMargins(12, 12, 12, 12)
        sdl.setSpacing(8)

        lab = QLabel("Preview")
        lab.setProperty("role", "dim")
        sdl.addWidget(lab)
        self.preview = PreviewWidget()
        self.preview.provider = self.render_char
        sdl.addWidget(self.preview)

        lab = QLabel("Preview text:")
        lab.setProperty("role", "dim")
        sdl.addWidget(lab)
        self.sample = QLineEdit("Hello World!")
        self.sample.textChanged.connect(self._sample_changed)
        sdl.addWidget(self.sample)

        tip = QLabel("Left click — draw, right click — erase.\nCtrl+S — save, Ctrl+Z — undo.")
        tip.setProperty("role", "dim")
        tip.setWordWrap(True)
        sdl.addWidget(tip)
        sdl.addStretch()
        split.addWidget(side)

        split.setSizes([260, 640, 320])
        root.addWidget(split, 1)

        self.statusBar().showMessage("Ready")

    def _vsep(self):
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setStyleSheet(f"color: {THEME['border']};")
        return f

    def _build_shortcuts(self):
        act_save = QAction(self)
        act_save.setShortcut(QKeySequence("Ctrl+S"))
        act_save.triggered.connect(self.save_glyph)
        self.addAction(act_save)
        act_undo = QAction(self)
        act_undo.setShortcut(QKeySequence("Ctrl+Z"))
        act_undo.triggered.connect(self.undo_last)
        self.addAction(act_undo)

    def status(self, msg):
        self.statusBar().showMessage(msg)

    # ---------- glyph registry ----------

    def load_project_glyphs(self):
        entries = None
        if self.project_dir:
            config_path = os.path.join(self.project_dir, "config.json")
            if os.path.exists(config_path):
                try:
                    with open(config_path, "r", encoding="utf-8") as f:
                        cfg = json.load(f)
                    entries = cfg.get("glyphs")
                except (OSError, json.JSONDecodeError):
                    entries = None
            if not entries:
                entries = discover_legacy_glyphs(self.project_dir)
        if not entries:
            entries = default_glyph_entries()
        self.glyph_entries = entries
        self.refresh_glyph_list()

    def save_project_glyphs(self):
        if not self.project_dir:
            return
        os.makedirs(self.project_dir, exist_ok=True)
        config_path = os.path.join(self.project_dir, "config.json")
        cfg = {}
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
            except (OSError, json.JSONDecodeError):
                cfg = {}
        cfg["glyphs"] = self.glyph_entries
        cfg.setdefault("project_path", self.project_dir)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=4)

    def entry_for(self, cp):
        for e in self.glyph_entries:
            if e["codepoint"] == cp:
                return e
        return None

    def refresh_glyph_list(self):
        prev_cp = self._current_key[0]
        query = self.glyph_search.text().strip().lower()
        self.glyph_list.blockSignals(True)
        self.glyph_list.clear()
        for entry in sorted(self.glyph_entries, key=lambda e: e["codepoint"]):
            cp = entry["codepoint"]
            ch = chr(cp)
            shown = ch if ch.isprintable() and not ch.isspace() else "·"
            label = f"U+{cp:04X}   {shown}   {entry['filename']}"
            if query and query not in label.lower():
                continue
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, cp)
            self.glyph_list.addItem(item)
        self.glyph_list.blockSignals(False)

        restored = False
        if prev_cp is not None:
            for i in range(self.glyph_list.count()):
                if self.glyph_list.item(i).data(Qt.ItemDataRole.UserRole) == prev_cp:
                    self.glyph_list.setCurrentRow(i)
                    restored = True
                    break
        if not restored and self.glyph_list.count():
            self.glyph_list.setCurrentRow(0)
        elif not self.glyph_list.count():
            # nothing left to select — make sure stale state doesn't linger
            self._current_key = (None, self._current_key[1])

    def add_glyph(self):
        existing_cps = {e["codepoint"] for e in self.glyph_entries}
        existing_names = {e["filename"].lower() for e in self.glyph_entries}
        dlg = AddGlyphDialog(existing_cps, existing_names, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cp, fname = dlg.get_result()
            self.glyph_entries.append({"codepoint": cp, "filename": fname})
            self.save_project_glyphs()
            self._current_key = (cp, self._current_key[1])  # select the new glyph on refresh
            self.refresh_glyph_list()
            self.status(f"Added glyph U+{cp:04X}")

    def remove_glyph(self):
        cp, size = self.current_key()
        if cp is None:
            return
        entry = self.entry_for(cp)
        label = entry["filename"] if entry else f"U+{cp:04X}"
        reply = QMessageBox.question(
            self, "Remove Glyph",
            f"Remove '{label}' (U+{cp:04X}) from the project's glyph list?\n"
            "This only removes it from the list — any .svg files already "
            "saved to disk are left untouched.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.glyph_entries = [e for e in self.glyph_entries if e["codepoint"] != cp]
        for s in SIZES:
            self.grids.pop((cp, s), None)
        self._current_key = (None, size)  # prevent a stale flush from re-adding it
        self.save_project_glyphs()
        self.refresh_glyph_list()
        self.load_current()
        self.status(f"Removed U+{cp:04X} from the glyph list")

    # ---------- glyph handling ----------

    def current_key(self):
        item = self.glyph_list.currentItem()
        cp = item.data(Qt.ItemDataRole.UserRole) if item else None
        return cp, self.size_combo.currentData()

    def get_grid(self, cp, size, create=False):
        if cp is None:
            return GlyphGrid(size) if create else None
        key = (cp, size)
        if key in self.grids:
            return self.grids[key]
        entry = self.entry_for(cp)
        if self.project_dir and entry:
            path = os.path.join(self.project_dir, f"size_{size}", f"{entry['filename']}.svg")
            if os.path.exists(path):
                try:
                    g = svg_to_glyph(path, size)
                    self.grids[key] = g
                    return g
                except Exception:
                    pass
        if create:
            self.grids[key] = GlyphGrid(size)
            return self.grids[key]
        return None

    def render_char(self, ch, size):
        g = self.get_grid(ord(ch), size)
        return g if g else GlyphGrid(size)

    def load_current(self):
        # Reads the *new* widget state and adopts it as the current key.
        cp, size = self.current_key()
        self._current_key = (cp, size)
        g = self.get_grid(cp, size, create=True)
        self.editor.set_grid(g)
        self.undo_stack.clear()
        self.preview.size_variant = size
        self.preview.update()

    def on_selection_change(self):
        # IMPORTANT: store_current() must run BEFORE the widgets' new
        # selection is adopted, using the key that was active a moment
        # ago — otherwise the just-edited pixels get written under the
        # *new* glyph's key/file instead of the old one.
        self.store_current()
        self.load_current()

    def store_current(self):
        cp, size = self._current_key
        if cp is None:
            return
        self.grids[(cp, size)] = self.editor.get_grid()
        if self.project_dir:
            self.write_svg(cp, size)

    # ---------- events ----------

    def _edited(self):
        self.preview.update()

    def _sample_changed(self, t):
        self.preview.text = t
        self.preview.update()

    # ---------- SVG ----------

    def save_glyph(self):
        cp, size = self.current_key()
        if cp is None:
            self.status("No glyph selected")
            return
        if not self.project_dir:
            d = QFileDialog.getExistingDirectory(self, "Select the project folder")
            if not d:
                return
            self.project_dir = d
        self.grids[(cp, size)] = self.editor.get_grid()
        self.write_svg(cp, size)
        self.status(f"Saved: U+{cp:04X} {size}×{size} → size_{size}/")

    def write_svg(self, cp, size):
        entry = self.entry_for(cp)
        if not entry:
            return
        d = os.path.join(self.project_dir, f"size_{size}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{entry['filename']}.svg"), "wb") as f:
            f.write(glyph_to_svg(self.grids[(cp, size)], chr(cp)))

    def load_glyph(self):
        cp, size = self.current_key()
        if cp is None:
            self.status("No glyph selected")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open .svg", "", "SVG (*.svg)")
        if not path:
            return
        try:
            g = svg_to_glyph(path, size)
            self.editor.set_grid(g)
            self.grids[(cp, size)] = g
            self.status(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to parse SVG:\n{e}")

    def open_project(self):
        d = QFileDialog.getExistingDirectory(self, "Project folder")
        if not d:
            return
        self.project_dir = d
        self.grids.clear()
        self.load_project_glyphs()
        self.load_current()
        self.status(f"Project opened: {d}")

    def import_font(self):
        """Import glyphs from an existing font file (e.g. Monocraft.ttf):
        each requested character is rasterized into a grid at the chosen
        size, added to the project's glyph registry, and written out as
        an editable .svg — same as any hand-drawn glyph from then on."""
        if not PIL_AVAILABLE:
            QMessageBox.warning(
                self, "Import Font",
                "Pillow is not installed.\n\nRun:\n  pip install Pillow\n"
                "(or: pip install -r requirements.txt)")
            return
        if not self.project_dir:
            d = QFileDialog.getExistingDirectory(self, "Select the project folder")
            if not d:
                return
            self.project_dir = d
            os.makedirs(os.path.join(self.project_dir, "out"), exist_ok=True)

        dlg = ImportFontDialog(self.size_combo.currentData(), self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        r = dlg.get_result()
        font_path, size, chars = r["font_path"], r["size"], r["chars"]

        try:
            available_cps = font_cmap_codepoints(font_path)
        except Exception as e:
            QMessageBox.critical(self, "Import Font",
                                 f"Could not read the font's character map:\n{e}")
            return

        existing_cps = {e["codepoint"] for e in self.glyph_entries}
        existing_names = {e["filename"].lower() for e in self.glyph_entries}

        imported, skipped_missing, skipped_existing, failed = [], 0, 0, []
        for ch in chars:
            cp = ord(ch)
            if cp not in available_cps:
                skipped_missing += 1
                continue
            if r["skip_existing"] and cp in existing_cps:
                skipped_existing += 1
                continue
            try:
                grid = rasterize_char(font_path, ch, size)
            except Exception as e:
                failed.append(f"U+{cp:04X}: {e}")
                continue
            entry = self.entry_for(cp)
            if entry is None:
                fname = default_filename(cp)
                base = fname
                n = 1
                while fname.lower() in existing_names:
                    n += 1
                    fname = f"{base}_{n}"
                existing_names.add(fname.lower())
                entry = {"codepoint": cp, "filename": fname}
                self.glyph_entries.append(entry)
                existing_cps.add(cp)
            self.grids[(cp, size)] = grid
            self.write_svg(cp, size)
            imported.append(cp)

        self.save_project_glyphs()
        self.refresh_glyph_list()
        if imported:
            self._current_key = (imported[0], size)
            idx = self.size_combo.findData(size)
            if idx >= 0:
                self.size_combo.setCurrentIndex(idx)
            self.refresh_glyph_list()
            self.load_current()

        summary = (f"Imported {len(imported)} glyph(s) from "
                  f"{os.path.basename(font_path)} at {size}×{size}.")
        details = []
        if skipped_missing:
            details.append(f"{skipped_missing} skipped (not in the font)")
        if skipped_existing:
            details.append(f"{skipped_existing} skipped (already in the project)")
        if failed:
            details.append(f"{len(failed)} failed")
        if details:
            summary += "\n" + ", ".join(details) + "."
        if failed:
            summary += "\n\n" + "\n".join(failed[:10])
        QMessageBox.information(self, "Import Font", summary)
        self.status(f"Imported {len(imported)} glyph(s) from {os.path.basename(font_path)}")

    # ---------- glyph operations ----------

    def push_undo(self):
        self.undo_stack.append(self.editor.get_grid())
        if len(self.undo_stack) > 50:
            self.undo_stack.pop(0)

    def clear_glyph(self):
        self.push_undo()
        self.editor.set_grid(GlyphGrid(self.size_combo.currentData()))

    def invert_glyph(self):
        self.push_undo()
        g = self.editor.get_grid()
        g.invert()
        self.editor.set_grid(g)

    def do_shift(self, dx, dy):
        self.push_undo()
        g = self.editor.get_grid()
        g.shift(dx, dy)
        self.editor.set_grid(g)

    def undo_last(self):
        if self.undo_stack:
            self.editor.set_grid(self.undo_stack.pop())
        else:
            self.status("Undo history is empty")

    # ---------- build ----------

    def build_font(self):
        if not self.glyph_entries:
            QMessageBox.warning(self, "Build Font", "The glyph list is empty — add at least one glyph first.")
            return

        # Default the output folder to <project>/out — it's already created
        # for every project, so the user shouldn't have to pick it manually.
        default_out = os.path.join(self.project_dir, "out") if self.project_dir else ""
        dlg = BuildDialog(default_out)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        r = dlg.results()
        out = r["out"].strip()
        if not out:
            QMessageBox.warning(self, "Build Font", "Please specify an output folder.")
            return
        if not os.path.isdir(out):
            try:
                os.makedirs(out, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "Build Font", f"Could not create the output folder:\n{e}")
                return

        self.store_current()
        entries = sorted(self.glyph_entries, key=lambda e: e["codepoint"])
        by_size = {s: {e["codepoint"]: self.get_grid(e["codepoint"], s, create=True) for e in entries}
                  for s in SIZES}

        try:
            if r["h"]:
                export_h(entries, by_size, os.path.join(out, "pixelfont.h"))

            if r["bdf"]:
                for s in SIZES:
                    export_bdf(entries, s, by_size[s], os.path.join(out, f"pixelfont_{s}px.bdf"))

            # separate vector files (also needed for .ttc)
            ttf_paths = {}
            if r["otf"] or r["ttf"]:
                for s in SIZES:
                    if r["otf"]:
                        export_vector_font(entries, s, by_size[s],
                                           os.path.join(out, f"pixelfont_{s}px.otf"))
                    if r["ttf"]:
                        p = os.path.join(out, f"pixelfont_{s}px.ttf")
                        export_ttf(entries, s, by_size[s], p)
                        if r["ttc"]:
                            ttf_paths[s] = p

            if r["ttc"]:
                # reuse already-built .ttf files if present
                paths = []
                for s in SIZES:
                    p = ttf_paths.get(s, os.path.join(out, f"pixelfont_{s}px.ttf"))
                    if not os.path.exists(p):
                        export_ttf(entries, s, by_size[s], p)
                    paths.append(p)
                build_ttc(paths, os.path.join(out, "pixelfont.ttc"))
        except Exception as e:
            QMessageBox.critical(self, "Build Font", f"Error: {e}")
            return

        made = []
        if r["h"]:
            made.append("pixelfont.h")
        if r["otf"]:
            made.append("pixelfont_8px.otf / pixelfont_16px.otf / pixelfont_32px.otf")
        if r["ttf"]:
            made.append("pixelfont_8px.ttf / pixelfont_16px.ttf / pixelfont_32px.ttf")
        if r["ttc"]:
            made.append("pixelfont.ttc")
        if r["bdf"]:
            made.append("pixelfont_8px.bdf / pixelfont_16px.bdf / pixelfont_32px.bdf")

        QMessageBox.information(self, "Build Font",
                                "Build complete!\nCreated in "
                                f"{out}:\n" + "\n".join(made))
        self.status(f"Build complete: {out}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    apply_theme(app, THEME)

    start = StartDialog()
    if start.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)

    w = MainWindow()
    cfg = start.last_config
    if cfg and os.path.isdir(cfg.get("project_path", "")):
        w.project_dir = cfg["project_path"]
        w.grids.clear()
        w.load_project_glyphs()
        font_size = cfg.get("font_size")
        if font_size in SIZES:
            idx = w.size_combo.findData(font_size)
            if idx >= 0:
                w.size_combo.setCurrentIndex(idx)
        w.load_current()
    w.show()
    sys.exit(app.exec())
