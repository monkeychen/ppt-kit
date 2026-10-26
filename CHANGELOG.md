# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.1] - 2026-10-26

### Fixed
- **Cross-Platform OCR & Inpaint Verification**:
  - `verify_background_cleanliness` now evaluates cleaned images using pipeline cleaning (`clean=True`), preventing noise and non-text artifacts from distorting cleanliness ratios.
  - Added stray icon / container filtering (`"口"`, `"〇"`, and `min(w, h) >= 60`) in `clean_ocr_boxes` to prevent high-contrast geometric blocks from being misidentified as single-character text boxes.
  - Made unit tests (`test_inpaint.py`, `test_text_style.py`, `test_refiner.py`) OS-agnostic by removing hardcoded macOS font paths (`/System/Library/Fonts/STHeiti Medium.ttc`) and instantiating `get_ocr_adapter("auto")` instead of `AppleVisionOCRAdapter`.
- **System Font Discovery**:
  - Expanded `get_installed_fonts()` in `pptkit/vector/fonts.py` with standard Linux (`/usr/share/fonts`, `~/.fonts`) and Windows (`C:/Windows/Fonts`) system font directories.

## [0.2.0] - 2026-10-26

### Added
- **Cross-Platform OCR Multi-Engine Dispatch**:
  - Standardized `BaseOCRAdapter` protocol with `apple_vision` and `rapidocr` implementations.
  - Automatic platform routing via `get_ocr_adapter("auto")`: Apple Vision on macOS, RapidOCR (CPU ONNX) on Linux and Windows.
  - CLI `--ocr-engine [auto|apple_vision|rapidocr]` option.
  - Multi-platform GitHub Actions CI matrix (`macos-latest`, `ubuntu-latest`, `windows-latest`).
- **Native Table Intermediate Representation (IR)**:
  - Added `CellBorder`, `TableCell`, and `TableElement` with full styling, background fills, border specifications, and cell spans (`row_span`, `col_span`).
- **Native PPTX Table Generation**:
  - High-fidelity PowerPoint Table shape creation with zero-margin cell padding to prevent text wrapping.
  - Underlying DrawingML `<a:lnL>`, `<a:lnR>`, `<a:lnT>`, `<a:lnB>` custom border injection and vertical alignment support.
- **Bitmap Table Reverse Extraction & Inpainting**:
  - Morphological gradient edge line detection to reliably separate solid headers from thin grid lines.
  - Text-to-cell assignment using geometric centroids and multiline paragraph merging.
  - Complete background table grid erasure and inpainting to prevent ghost lines in the underlying bitmap layer.
  - Quality reporting metrics expanded with `tables_count` and `table_cells_count`.

### Changed
- **Text Layer Deduplication**: Text boxes assigned to table cells are consumed and excluded from the slide-level floating text box layer.
- **Decomposition Precedence**: Table regions are extracted and inpainted prior to general shape detection, preventing grid lines from being misclassified as generic cards or lines.

### Fixed
- **PyInstaller Entry Point**: Added `src/pptkit/__main__.py` to ensure standalone binary packaging functions out of the box.
- **Platform Ingestion Defense**: Graceful error handling (`IngestError`) when Apple Vision is requested on non-macOS platforms.

## [0.1.0] - 2026-10-21

### Added
- **Vector PDF Direct Parser (M4)**: 100% character accuracy, 0.0pt font-size error, and 0.0 color Delta E directly from vector PDFs without OCR. Single page parsing in 0.4s.
- **Picture PPTX Ingestion**: Extract lossless slide images directly from pure-image `.pptx` media packages and deconstruct them into editable layers.
- **Bitmap Multi-Layer Decomposition (M2 & M3)**:
  - Extract solid-fill rectangles, rounded card containers, header capsules, and connector lines into native PowerPoint shapes.
  - Transparent standalone PNG layer isolation for illustrations and logos.
  - Multi-tier background inpainting to remove original text and shapes without residual ghosting.
  - Native offline Apple Vision OCR integration for macOS.
- **Quality Metrics & Reporting (M1)**:
  - Automated SSIM rendering comparison and pixel-level heatmap output.
  - Detailed `<name>.report.json` generation with editable element ratio, low-confidence elements, and processing timings.
- **Typer CLI**:
  - `pptkit convert <file|dir> -o <outdir>` with `--route auto|vector|raster`, `--pages`, and `--json` support.
  - `pptkit report <report.json> --needs-review` filtering command.
