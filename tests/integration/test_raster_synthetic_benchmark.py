from pathlib import Path

import pytest

from benchmark.synthetic.evaluator import evaluate_slide_ir
from benchmark.synthetic.generator import generate_synthetic_dataset
from pptkit.adapters.ocr import AppleVisionOCRAdapter
from pptkit.ir.models import TextBoxElement
from pptkit.raster.inpaint import verify_background_cleanliness
from pptkit.raster.pipeline import reconstruct_raster_slide


@pytest.mark.integration
def test_synthetic_raster_benchmark_meets_f7_and_f8_thresholds(tmp_path: Path) -> None:
    samples = generate_synthetic_dataset(tmp_path / "synth", count=2, seed=42, render=True)
    ocr = AppleVisionOCRAdapter()

    ssims: list[float] = []
    for sample in samples:
        assert sample.png_path is not None and sample.png_path.exists()
        gt_texts = [
            run.text
            for elem in sample.slide_ir.elements
            if isinstance(elem, TextBoxElement)
            for para in elem.paragraphs
            for run in para.runs
        ]
        orig_chars = sum(len(t) for t in gt_texts)

        work_dir = tmp_path / f"work_{sample.sample_id}"
        res = reconstruct_raster_slide(
            image_path=sample.png_path,
            page_index=0,
            work_dir=work_dir,
            max_iter=1,
            enable_render_refine=True,
        )

        # AC7.3: Background cleanliness <= 2% remaining chars
        rem_ratio = verify_background_cleanliness(res.cleaned_bg_path, orig_chars, ocr)
        assert rem_ratio <= 0.02

        # AC7.1: Text detection recall >= 95%
        pred_texts = [
            run.text
            for elem in res.slide_ir.elements
            if isinstance(elem, TextBoxElement)
            for para in elem.paragraphs
            for run in para.runs
        ]
        pred_chars = sum(len(t) for t in pred_texts)
        assert pred_chars / max(orig_chars, 1) >= 0.95

        # AC8.1: Shape reconstruction recall >= 85% and precision >= 90%
        eval_metrics = evaluate_slide_ir(sample.slide_ir, res.slide_ir)
        assert eval_metrics.shape_recall >= 0.85
        assert eval_metrics.shape_precision >= 0.90

        assert res.ssim is not None
        ssims.append(res.ssim)

    # AC7.4: Mean SSIM >= 0.90 on synthetic raster benchmark
    mean_ssim = sum(ssims) / len(ssims)
    assert mean_ssim >= 0.90
