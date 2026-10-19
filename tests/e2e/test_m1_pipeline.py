import json
import subprocess
from pathlib import Path

from benchmark.run import run_benchmark


def test_synthetic_end_to_end_benchmark_pipeline(tmp_path: Path) -> None:
    # 1. Run 5-slide synthetic benchmark with real PowerPoint rendering
    bench_out = tmp_path / "bench_results"
    summary = run_benchmark(out_dir=bench_out, count=5, seed=42, render=True)
    assert summary["count"] == 5
    slides_list = summary["slides"]
    assert isinstance(slides_list, list) and len(slides_list) == 5
    for slide_entry in slides_list:
        assert isinstance(slide_entry, dict)
        metrics = slide_entry["metrics"]
        assert isinstance(metrics, dict)
        assert float(metrics["ssim"]) > 0.999
        assert float(metrics["char_accuracy"]) == 1.0

    # 2. Run CLI end-to-end on one of the generated PDFs
    syn_pdf = bench_out / "synthetic" / "syn_000.rendered.pdf"
    cli_out = tmp_path / "cli_out"
    proc = subprocess.run(
        [
            "uv",
            "run",
            "pptkit",
            "convert",
            str(syn_pdf),
            "-o",
            str(cli_out),
            "--json",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    cli_summary = json.loads(proc.stdout)
    assert cli_summary["succeeded_pages"] == 1
    assert (cli_out / "syn_000.rendered.pptx").exists()
    assert (cli_out / "syn_000.rendered.report.json").exists()
