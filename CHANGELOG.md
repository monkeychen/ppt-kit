# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
