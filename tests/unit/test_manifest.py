import json
from pathlib import Path


def test_real_benchmark_manifest_has_at_least_20_pages() -> None:
    manifest_path = Path(__file__).resolve().parents[2] / "benchmark" / "real" / "manifest.json"
    assert manifest_path.exists(), "benchmark/real/manifest.json must exist"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "samples" in data
    samples = data["samples"]

    by_source: dict[str, int] = {"gpt": 0, "notebooklm": 0, "gemini": 0, "pptpdf": 0}
    total_pages = 0
    for entry in samples:
        assert "filename" in entry
        assert "source" in entry
        assert "pages" in entry
        assert "sha256" in entry
        assert "expected_route" in entry
        src = entry["source"]
        pages = int(entry["pages"])
        assert pages >= 1
        total_pages += pages
        if src in by_source:
            by_source[src] += pages

    assert total_pages >= 20
    for src, count in by_source.items():
        assert count >= 5, f"Source '{src}' must have >= 5 pages in manifest, got {count}"
