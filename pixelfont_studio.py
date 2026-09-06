#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PixelFont Studio — a pixel font editor for 8x8 / 16x16 / 32x32 fonts.

Every glyph (uppercase and lowercase) is stored as a separate .svg file,
which can be edited with any editor and loaded back in.
Export formats: .otf, .ttf, .ttc, .bdf, .h

Dependencies:
    pip install PyQt6 fonttools

Run:
    python pixelfont_studio.py
"""

import json
import os
import sys
import xml.etree.ElementTree as ET

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QColor, QKeySequence, QPalette, QPainter
from PyQt6.QtWidgets import (
    QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QMessageBox, QPushButton, QSplitter,
    QVBoxLayout, QWidget,
)

SVG_NS = "http://www.w3.org/2000/svg"
GLYPHS = [chr(c) for c in range(65, 91)] + [chr(c) for c in range(97, 123)]  # A-Z, a-z
SIZES = [8, 16, 32]

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


# ================================================================ startup dialogs

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
                QMessageBox.warning(self, "Error", "The selected directory does not contain src and out folders.")

    def save_config(self, project_path, project_name, font_size):
        # The config is stored inside the project folder itself (project_path),
        # not in the parent folder — otherwise it wouldn't match the src/out folders.
        os.makedirs(project_path, exist_ok=True)
        config = {
            "project_name": project_name,
            "project_path": project_path,
            "font_size": font_size,
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
        os.makedirs(os.path.join(project_path, "src"), exist_ok=True)
        os.makedirs(os.path.join(project_path, "out"), exist_ok=True)

    def validate_project_structure(self, project_path):
        return os.path.exists(os.path.join(project_path, "src")) and os.path.exists(os.path.join(project_path, "out"))


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
    root.append(ET.Comment(f" Glyph '{char}' ({grid.size}x{grid.size}) "))
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

def export_h(grids_by_size, path):
    L = [
        "// Generated by PixelFont Studio",
        "#pragma once",
        "#include <stdint.h>",
        "",
        "// Rows go top->bottom, bits packed MSB-first.",
        "// Glyph order: A..Z, a..z.",
        "",
    ]
    for s in SIZES:
        grids = grids_by_size[s]
        total = s * s // 8
        L += [
            f"#define PIXFONT_{s}x{s}_CHARS {len(GLYPHS)}",
            f"#define PIXFONT_{s}x{s}_W {s}",
            f"#define PIXFONT_{s}x{s}_H {s}",
            f"static const uint8_t pixfont_{s}x{s}[{len(GLYPHS)}][{total}] = {{",
        ]
        for ch in GLYPHS:
            grid = grids.get(ch) or GlyphGrid(s)
            rows = ["0x" + "".join(f"{b:02X}" for b in r) for r in _packed_rows(grid)]
            L.append(f"    /* '{ch}' 0x{ord(ch):02X} */ {{ {','.join(rows)} }},")
        L += ["};", ""]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(L))


# ================================================================ export: .bdf

def export_bdf(size, grids, path):
    L = [
        "STARTFONT 2.1",
        f"FONT -PixelFont-Regular-R-Normal--{size}-{size * 10}-75-75-P-{size * 10}-ISO10646-1",
        f"SIZE {size} 75 75",
        f"FONTBOUNDINGBOX {size} {size} 0 0",
        "STARTPROPERTIES 2",
        f"FONT_ASCENT {size}",
        "FONT_DESCENT 0",
        "ENDPROPERTIES",
        f"CHARS {len(GLYPHS)}",
    ]
    for ch in GLYPHS:
        grid = grids.get(ch, GlyphGrid(size))
        L += [
            f"STARTCHAR {ch}",
            f"ENCODING {ord(ch)}",
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

def export_vector_font(size, grids, path):
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
    for ch in GLYPHS:
        name = f"uni{ord(ch):04X}"
        order.append(name)
        cmap[ord(ch)] = name
        hm[name] = (upem, 0)
        grid = grids.get(ch, GlyphGrid(size))
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


def export_ttf(size, grids, path):
    """Plain .ttf — same engine, correct extension."""
    export_vector_font(size, grids, path)


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
        self.resize(1100, 720)
        self.project_dir = ""
        self.grids = {}          # (char, size) -> GlyphGrid
        self.undo_stack = []

        self._build_ui()
        self._build_shortcuts()
        self.load_current()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(14, 14, 14, 10)
        root.setSpacing(12)

        # --- glyph/size selector row
        sel = QFrame()
        sel.setProperty("class", "card")
        sel.setProperty("role", "selector")
        sl = QHBoxLayout(sel)
        sl.setContentsMargins(12, 10, 12, 10)
        sl.setSpacing(10)
        lab = QLabel("Glyph:")
        lab.setProperty("role", "dim")
        sl.addWidget(lab)
        self.glyph_combo = QComboBox()
        for ch in GLYPHS:
            self.glyph_combo.addItem(f"{ch}  (U+{ord(ch):04X})", ch)
        self.glyph_combo.setMinimumWidth(150)
        sl.addWidget(self.glyph_combo)
        lab = QLabel("Size:")
        lab.setProperty("role", "dim")
        sl.addWidget(lab)
        self.size_combo = QComboBox()
        for s in SIZES:
            self.size_combo.addItem(f"{s}×{s}", s)
        sl.addWidget(self.size_combo)
        sl.addStretch()
        root.addWidget(sel)

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

        # --- editor + side panel (splitter lets you resize the proportions)
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setHandleWidth(10)

        editor_card = QFrame()
        editor_card.setProperty("class", "card")
        ecl = QVBoxLayout(editor_card)
        ecl.setContentsMargins(10, 10, 10, 10)
        self.editor = GridEditor()
        self.editor.gridChanged.connect(self._edited)
        self.editor.strokeStarted.connect(self.push_undo)
        ecl.addWidget(self.editor, 1)
        split.addWidget(editor_card)

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

        split.setSizes([700, 350])
        root.addWidget(split, 1)

        self.glyph_combo.currentIndexChanged.connect(self.on_selection_change)
        self.size_combo.currentIndexChanged.connect(self.on_selection_change)

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

    # ---------- glyph handling ----------

    def current_key(self):
        return self.glyph_combo.currentData(), self.size_combo.currentData()

    def get_grid(self, ch, size, create=False):
        key = (ch, size)
        if key in self.grids:
            return self.grids[key]
        if self.project_dir:
            path = os.path.join(self.project_dir, f"size_{size}", f"{ord(ch):02X}_{ch}.svg")
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
        g = self.get_grid(ch, size)
        return g if g else GlyphGrid(size)

    def load_current(self):
        ch, size = self.current_key()
        g = self.get_grid(ch, size, create=True)
        self.editor.set_grid(g)
        self.undo_stack.clear()
        self.preview.size_variant = size
        self.preview.update()

    def on_selection_change(self):
        self.store_current()
        self.load_current()

    def store_current(self):
        ch, size = self.current_key()
        self.grids[(ch, size)] = self.editor.get_grid()
        if self.project_dir:
            self.write_svg(ch, size)

    # ---------- events ----------

    def _edited(self):
        self.preview.update()

    def _sample_changed(self, t):
        self.preview.text = t
        self.preview.update()

    # ---------- SVG ----------

    def save_glyph(self):
        ch, size = self.current_key()
        if not self.project_dir:
            d = QFileDialog.getExistingDirectory(self, "Select the project folder")
            if not d:
                return
            self.project_dir = d
        self.grids[(ch, size)] = self.editor.get_grid()
        self.write_svg(ch, size)
        self.status(f"Saved: {ch} {size}×{size} → size_{size}/")

    def write_svg(self, ch, size):
        d = os.path.join(self.project_dir, f"size_{size}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"{ord(ch):02X}_{ch}.svg"), "wb") as f:
            f.write(glyph_to_svg(self.grids[(ch, size)], ch))

    def load_glyph(self):
        ch, size = self.current_key()
        path, _ = QFileDialog.getOpenFileName(self, "Open .svg", "", "SVG (*.svg)")
        if not path:
            return
        try:
            g = svg_to_glyph(path, size)
            self.editor.set_grid(g)
            self.grids[(ch, size)] = g
            self.status(f"Loaded: {os.path.basename(path)}")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to parse SVG:\n{e}")

    def open_project(self):
        d = QFileDialog.getExistingDirectory(self, "Project folder")
        if not d:
            return
        self.project_dir = d
        self.grids.clear()
        self.load_current()
        self.status(f"Project opened: {d}")

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
        by_size = {s: {c: self.get_grid(c, s, create=True) for c in GLYPHS} for s in SIZES}

        try:
            if r["h"]:
                export_h(by_size, os.path.join(out, "pixelfont.h"))

            if r["bdf"]:
                for s in SIZES:
                    export_bdf(s, by_size[s], os.path.join(out, f"pixelfont_{s}px.bdf"))

            # separate vector files (also needed for .ttc)
            ttf_paths = {}
            if r["otf"] or r["ttf"]:
                for s in SIZES:
                    if r["otf"]:
                        export_vector_font(s, by_size[s],
                                           os.path.join(out, f"pixelfont_{s}px.otf"))
                    if r["ttf"]:
                        p = os.path.join(out, f"pixelfont_{s}px.ttf")
                        export_ttf(s, by_size[s], p)
                        if r["ttc"]:
                            ttf_paths[s] = p

            if r["ttc"]:
                # reuse already-built .ttf files if present
                paths = []
                for s in SIZES:
                    p = ttf_paths.get(s, os.path.join(out, f"pixelfont_{s}px.ttf"))
                    if not os.path.exists(p):
                        export_ttf(s, by_size[s], p)
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
        font_size = cfg.get("font_size")
        if font_size in SIZES:
            idx = w.size_combo.findData(font_size)
            if idx >= 0:
                w.size_combo.setCurrentIndex(idx)
        w.load_current()
    w.show()
    sys.exit(app.exec())
