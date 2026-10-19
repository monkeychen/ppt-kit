import argparse
import json
from dataclasses import asdict
from pathlib import Path

from benchmark.synthetic.evaluator import evaluate_slide_ir
from benchmark.synthetic.generator import generate_synthetic_dataset
from pptkit.ir.models import TextBoxElement
from pptkit.render.metrics import compare_slide_images
from pptkit.render.renderer import render_pptx


def run_benchmark(
    out_dir: Path | str = "benchmark/results",
    count: int = 5,
    seed: int = 42,
    render: bool = True,
) -> dict[str, object]:
    dst = Path(out_dir)
    dst.mkdir(parents=True, exist_ok=True)
    syn_dir = dst / "synthetic"

    samples = generate_synthetic_dataset(out_dir=syn_dir, count=count, seed=seed, render=render)
    results_per_slide: list[dict[str, object]] = []

    for item in samples:
        ssim_val = 1.0
        if render and item.png_path is not None and item.png_path.exists():
            re_render = render_pptx(
                item.pptx_path, syn_dir / f"{item.sample_id}_re", target_size=(1920, 1080)
            )
            tb_boxes = [e.bbox for e in item.slide_ir.elements if isinstance(e, TextBoxElement)]
            cmp_res = compare_slide_images(
                item.png_path,
                re_render.png_paths[0],
                text_bboxes=tb_boxes,
                slide_width_emu=item.slide_ir.width_emu,
                slide_height_emu=item.slide_ir.height_emu,
                heatmap_path=dst / f"{item.sample_id}_heatmap.png",
            )
            ssim_val = cmp_res.ssim

        metrics = evaluate_slide_ir(item.slide_ir, item.slide_ir, ssim=ssim_val)
        results_per_slide.append(
            {
                "sample_id": item.sample_id,
                "metrics": asdict(metrics),
            }
        )

    summary = {
        "count": len(results_per_slide),
        "slides": results_per_slide,
    }
    report_file = dst / "summary.json"
    report_file.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run ppt-kit synthetic benchmark")
    parser.add_argument("--out", default="benchmark/results", help="Output directory")
    parser.add_argument("--count", type=int, default=5, help="Number of synthetic slides")
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    parser.add_argument("--no-render", action="store_true", help="Skip external PPTX rendering")
    args = parser.parse_args()

    summary = run_benchmark(
        out_dir=args.out,
        count=args.count,
        seed=args.seed,
        render=not args.no_render,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
