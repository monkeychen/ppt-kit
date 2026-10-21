import json
from pathlib import Path

import pymupdf
from typer.testing import CliRunner

from pptkit.cli.app import app

runner = CliRunner()


def _create_test_vector_pdf(path: Path) -> None:
    doc = pymupdf.open()

    # Page 1: Slide with title, rect, round_rect, line, and bullet text
    p0 = doc.new_page(width=960, height=540)
    p0.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(0.98, 0.98, 0.98))
    p0.draw_rect(
        pymupdf.Rect(80, 80, 440, 260),
        fill=(0.1, 0.3, 0.7),
        color=(0.05, 0.15, 0.4),
        width=2,
    )
    p0.draw_rect(
        pymupdf.Rect(500, 80, 880, 260),
        radius=0.1,
        fill=(0.95, 0.6, 0.1),
        color=(0.8, 0.4, 0.0),
        width=1.5,
    )
    p0.draw_line(pymupdf.Point(80, 300), pymupdf.Point(880, 300), color=(0.7, 0.7, 0.7), width=1)
    p0.insert_text((80, 350), "Overview of Architecture", fontsize=26, color=(0.1, 0.1, 0.1))
    p0.insert_text(
        (80, 400),
        "High performance vector extraction bypassing VLM/OCR.",
        fontsize=16,
        color=(0.2, 0.2, 0.2),
    )

    # Page 2: Multi-line and multiple text boxes
    p1 = doc.new_page(width=960, height=540)
    p1.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(1.0, 1.0, 1.0))
    p1.insert_text((100, 100), "Detailed Technical Specifications", fontsize=24)
    p1.insert_text((100, 150), "Paragraph line 1 with system font.", fontsize=15)
    p1.insert_text((100, 180), "Paragraph line 2 with continuous flow.", fontsize=15)
    p1.draw_oval(pymupdf.Rect(600, 300, 800, 450), fill=(0.3, 0.8, 0.4))

    doc.save(path)
    doc.close()


def test_cli_convert_vector_pdf_end_to_end(tmp_path: Path) -> None:
    pdf_path = tmp_path / "spec_test.pdf"
    _create_test_vector_pdf(pdf_path)

    out_dir = tmp_path / "out_vector"
    res = runner.invoke(app, ["convert", str(pdf_path), "-o", str(out_dir), "--json"])
    assert res.exit_code == 0, res.output

    pptx_out = out_dir / "spec_test.pptx"
    report_out = out_dir / "spec_test.report.json"
    assert pptx_out.exists()
    assert report_out.exists()

    report = json.loads(report_out.read_text(encoding="utf-8"))
    assert report["total_pages"] == 2
    assert report["succeeded_pages"] == 2
    assert report["failed_pages"] == 0

    p0_rep = report["pages"][0]
    assert p0_rep["route"] == "vector"
    assert p0_rep["status"] == "ok"
    assert p0_rep["editable_elements"] >= 4
    assert p0_rep["degraded_elements"] == 0
    assert p0_rep["model_calls"] == 0
    assert p0_rep["elapsed_sec"] < 2.0  # Vector parsing is sub-second

    p1_rep = report["pages"][1]
    assert p1_rep["route"] == "vector"
    assert p1_rep["status"] == "ok"
    assert p1_rep["editable_elements"] >= 2
    assert p1_rep["degraded_elements"] == 0
