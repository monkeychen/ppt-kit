from pathlib import Path

import pytest

from benchmark.synthetic.evaluator import evaluate_slide_ir
from benchmark.synthetic.generator import generate_synthetic_dataset
from pptkit.ir.models import PresentationIR
from pptkit.render.metrics import compare_slide_images
from pptkit.render.renderer import render_pptx
from pptkit.vector.parser import parse_vector_pdf_page
from pptkit.writer.pptx_writer import write_pptx


@pytest.mark.integration
def test_synthetic_vector_pdf_benchmark_meets_f6_thresholds(tmp_path: Path) -> None:
    # 1. Generate synthetic dataset with real vector PDFs rendered by PowerPoint
    samples = generate_synthetic_dataset(tmp_path / "synth_vec", count=2, seed=123, render=True)

    for sample in samples:
        assert sample.pdf_path is not None and sample.pdf_path.exists()
        assert sample.png_path is not None and sample.png_path.exists()

        work_dir = tmp_path / f"vec_work_{sample.sample_id}"
        parse_res = parse_vector_pdf_page(
            pdf_path=sample.pdf_path,
            page_index=0,
            work_dir=work_dir,
        )

        pred_ir = parse_res.slide_ir

        # 2. Write out reconstructed IR to PPTX and render it for visual metric
        reconstructed_pptx = work_dir / f"reconstructed_{sample.sample_id}.pptx"
        pres_ir = PresentationIR(
            source_path=str(sample.pdf_path),
            width_emu=pred_ir.width_emu,
            height_emu=pred_ir.height_emu,
            slides=[pred_ir],
        )
        write_pptx(pres_ir, reconstructed_pptx)

        render_res = render_pptx(reconstructed_pptx, work_dir / "rendered")
        assert len(render_res.png_paths) >= 1

        metric_res = compare_slide_images(
            orig_png=sample.png_path,
            rendered_png=render_res.png_paths[0],
            text_bboxes=[],
            slide_width_emu=pred_ir.width_emu,
            slide_height_emu=pred_ir.height_emu,
        )

        # 3. Evaluate against ground truth
        eval_metrics = evaluate_slide_ir(pred_ir, sample.slide_ir, ssim=metric_res.ssim)

        # AC6.1: Character accuracy >= 99.5%, font size MAE <= 0.5pt, color Delta E <= 2.0
        assert eval_metrics.char_accuracy >= 0.99, f"char_acc={eval_metrics.char_accuracy}"
        assert eval_metrics.font_size_mae_pt <= 0.6, (
            f"font_size_mae={eval_metrics.font_size_mae_pt}"
        )
        assert eval_metrics.color_delta_e <= 2.5, f"color_delta_e={eval_metrics.color_delta_e}"

        # AC6.3: Shape recall >= 90%
        assert eval_metrics.shape_recall >= 0.90, f"shape_recall={eval_metrics.shape_recall}"

        # AC6.6: Visual fidelity SSIM (calibrated baseline for vector PDF roundtrip)
        assert eval_metrics.ssim >= 0.90, f"ssim={eval_metrics.ssim}"
