import json
import zipfile
from pathlib import Path

import pymupdf
from pptx import Presentation
from typer.testing import CliRunner

from pptkit.cli.app import app

runner = CliRunner()


def _create_multi_page_raster_pdf(path: Path) -> None:
    doc = pymupdf.open()

    # Page 0 (Title slide): Dark blue cover
    p0 = doc.new_page(width=960, height=540)
    p0.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(0.05, 0.1, 0.25))
    p0.insert_text((150, 240), "数字孪生系统技术汇报", fontsize=32, color=(1, 1, 1))
    p0.insert_text((150, 300), "中国移动通信集团", fontsize=18, color=(0.8, 0.8, 0.8))

    # Page 1 (Content slide 1): Shared light background + blue header bar
    p1 = doc.new_page(width=960, height=540)
    p1.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(0.97, 0.97, 0.97))
    p1.draw_rect(pymupdf.Rect(0, 0, 960, 45), fill=(0.0, 0.32, 0.85))
    p1.insert_text((40, 30), "一、项目概述与总体架构", fontsize=18, color=(1, 1, 1))
    p1.insert_text((60, 150), "核心指标达成：论文60+篇、专利250+项", fontsize=16)

    # Page 2 (Content slide 2): Same shared light background + blue header bar
    p2 = doc.new_page(width=960, height=540)
    p2.draw_rect(pymupdf.Rect(0, 0, 960, 540), fill=(0.97, 0.97, 0.97))
    p2.draw_rect(pymupdf.Rect(0, 0, 960, 45), fill=(0.0, 0.32, 0.85))
    p2.insert_text((40, 30), "二、攻关难点与技术突破", fontsize=18, color=(1, 1, 1))
    p2.insert_text((60, 150), "面对网络告警风暴，实现自主决策协同", fontsize=16)

    doc.save(path)
    doc.close()


def test_cli_convert_inducts_master_and_deduplicates(tmp_path: Path) -> None:
    pdf_path = tmp_path / "deck.pdf"
    _create_multi_page_raster_pdf(pdf_path)

    out_dir = tmp_path / "out"
    res = runner.invoke(app, ["convert", str(pdf_path), "-o", str(out_dir), "--json"])
    assert res.exit_code == 0, res.output

    pptx_out = out_dir / "deck.pptx"
    report_out = out_dir / "deck.report.json"
    assert pptx_out.exists()
    assert report_out.exists()

    report = json.loads(report_out.read_text(encoding="utf-8"))
    assert report["total_pages"] == 3
    assert report["succeeded_pages"] == 3

    # Open generated PPTX and verify slide master structure
    prs = Presentation(str(pptx_out))
    assert len(prs.slides) == 3

    # Verify deduplication in zip
    with zipfile.ZipFile(pptx_out) as z:
        media_files = [f for f in z.namelist() if f.startswith("ppt/media/")]
        # Content pages 1 and 2 share the content master background,
        # so total media files are significantly less than number of pages * 2
        assert len(media_files) <= 3
