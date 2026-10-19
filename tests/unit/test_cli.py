import io
import json
from pathlib import Path

import pymupdf
import pytest
from PIL import Image
from typer.testing import CliRunner

from pptkit.cli.app import app

runner = CliRunner()


def _create_vector_pdf(path: Path) -> None:
    doc = pymupdf.open()
    p = doc.new_page(width=960, height=540)
    p.insert_text((100, 120), "Editable Vector Slide Content Here")
    doc.save(path)
    doc.close()


def _create_raster_png(path: Path) -> None:
    img = Image.new("RGB", (640, 360), color=(240, 240, 250))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    path.write_bytes(buf.getvalue())


def test_cli_convert_file_and_dir_outputs_pptx_and_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PPTKIT_GEMINI_API_KEY", "dummy-key-for-unit-test")

    in_dir = tmp_path / "inputs"
    in_dir.mkdir()
    pdf_file = in_dir / "deck.pdf"
    png_file = in_dir / "slide.png"
    _create_vector_pdf(pdf_file)
    _create_raster_png(png_file)

    out_single = tmp_path / "out_single"
    res_single = runner.invoke(app, ["convert", str(pdf_file), "-o", str(out_single)])
    assert res_single.exit_code == 0
    assert (out_single / "deck.pptx").exists()
    report_path = out_single / "deck.report.json"
    assert report_path.exists()
    rep = json.loads(report_path.read_text(encoding="utf-8"))
    assert rep["pages"][0]["route"] == "vector"

    out_batch = tmp_path / "out_batch"
    res_batch = runner.invoke(app, ["convert", str(in_dir), "-o", str(out_batch)])
    assert res_batch.exit_code == 0
    assert (out_batch / "deck.pptx").exists()
    assert (out_batch / "deck.report.json").exists()
    assert (out_batch / "slide.pptx").exists()
    assert (out_batch / "slide.report.json").exists()


def test_cli_missing_api_key_allows_vector_blocks_raster(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for var in (
        "PPTKIT_GEMINI_API_KEY",
        "GEMINI_API_KEY",
        "PPTKIT_OPENAI_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PPTKIT_CONFIG_PATH", str(tmp_path / "nonexistent_config.toml"))

    pdf_file = tmp_path / "vec.pdf"
    png_file = tmp_path / "ras.png"
    _create_vector_pdf(pdf_file)
    _create_raster_png(png_file)

    out_dir = tmp_path / "out"
    res_vec = runner.invoke(app, ["convert", str(pdf_file), "-o", str(out_dir)])
    assert res_vec.exit_code == 0

    res_ras = runner.invoke(app, ["convert", str(png_file), "-o", str(out_dir)])
    assert res_ras.exit_code == 1
    combined_out = res_ras.stdout + (res_ras.stderr or "")
    assert "PPTKIT_GEMINI_API_KEY" in combined_out or "GEMINI_API_KEY" in combined_out


def test_cli_partial_failure_isolation_and_exit_codes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 1. Mixed PDF (1 vector + 1 raster page) without API Key -> exit code 2
    for var in ("PPTKIT_GEMINI_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PPTKIT_CONFIG_PATH", str(tmp_path / "nonexistent_config.toml"))

    mixed_pdf = tmp_path / "mixed.pdf"
    doc = pymupdf.open()
    p0 = doc.new_page(width=960, height=540)
    p0.insert_text((100, 120), "Page 0 Vector Text Content")
    p1 = doc.new_page(width=960, height=540)
    img = Image.new("RGB", (320, 180), color=(200, 210, 220))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    p1.insert_image(pymupdf.Rect(0, 0, 960, 540), stream=buf.getvalue())
    doc.save(mixed_pdf)
    doc.close()

    out_dir = tmp_path / "out_partial"
    res_partial = runner.invoke(app, ["convert", str(mixed_pdf), "-o", str(out_dir)])
    assert res_partial.exit_code == 2
    assert (out_dir / "mixed.pptx").exists()
    rep = json.loads((out_dir / "mixed.report.json").read_text(encoding="utf-8"))
    assert rep["succeeded_pages"] == 1
    assert rep["failed_pages"] == 1

    # 2. Corrupted file -> exit code 1 with guidance
    bad_pdf = tmp_path / "corrupted.pdf"
    bad_pdf.write_bytes(b"invalid pdf bytes")
    res_bad = runner.invoke(app, ["convert", str(bad_pdf), "-o", str(out_dir)])
    assert res_bad.exit_code == 1
