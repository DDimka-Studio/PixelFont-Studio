# PixelFont Studio

A pixel font editor for 8×8 / 16×16 / 32×32 fonts, built with PyQt6.
Glyphs are drawn by hand (or imported from an existing font — see
below), stored as individual `.svg` files, and exported to
`.otf` / `.ttf` / `.ttc` / `.bdf` / `.h`.

## Installation

Requires Python 3.9+.

```bash
pip install -r requirements.txt
```

This installs everything the app needs:

| Package    | Used for                                      |
|------------|------------------------------------------------|
| PyQt6      | the desktop UI                                  |
| fonttools  | reading font files and building .otf/.ttf/.ttc  |
| Pillow     | rasterizing glyphs when importing a font        |

## Running

```bash
python pixelfont_studio.py
```

## Basic workflow

1. **Create a new project** (or open an existing one) from the start screen.
2. Pick a glyph in the left panel, draw it in the grid.
3. `Ctrl+S` / **💾 Save .svg** saves the current glyph; the project's glyph
   list is saved automatically whenever it changes.
4. **🔨 Build Font** exports the whole project to your chosen formats.

Each project folder contains:

```
MyProject/
  config.json        # glyph registry (codepoint -> file name) + settings
  size_8/*.svg        # 8x8 glyphs
  size_16/*.svg        # 16x16 glyphs
  size_32/*.svg        # 32x32 glyphs
  out/                # exported fonts land here by default
```

## Importing an existing font (e.g. Monocraft)

Use this to bring in a font you already have as a starting point, then
touch it up by hand instead of drawing every glyph from scratch.

1. Click **⬇ Import Font…** in the toolbar (this also creates/opens a
   project if none is open yet).
2. Pick the font file — for example `Monocraft.ttf`
   ([github.com/IdreesInc/Monocraft](https://github.com/IdreesInc/Monocraft)).
3. Choose the grid size to import at (8×8, 16×16, or 32×32).
4. Edit the character list if you want — it's pre-filled with A–Z, a–z,
   digits, and common punctuation. Any characters not present in the
   font are skipped automatically, as are duplicates.
5. Click **OK**. Each imported character:
   - is added to the project's glyph list if it isn't already there,
   - is rasterized into the grid at the size you chose,
   - is written to `size_<N>/<name>.svg`, exactly like a hand-drawn glyph.
6. Select any imported glyph in the list and edit it normally — pixel by
   pixel, invert, shift, etc. — then save.

**Note on quality:** the importer renders each character with the source
font at a high resolution and downsamples it into the pixel grid. For
fonts that are *already* pixel-art (like Monocraft), this reproduces the
design closely; for smooth/vector fonts it's a rough approximation.
Either way, treat the import as a first draft to clean up by hand rather
than a pixel-perfect conversion — that's also why "Import Font" doesn't
overwrite glyphs you've already edited unless you uncheck "Skip
characters already in the project".

Supported input formats: `.ttf` and `.otf` (anything Pillow's
`ImageFont.truetype` can load).
