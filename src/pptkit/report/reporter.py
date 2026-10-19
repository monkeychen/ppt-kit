from typing import Literal

from pydantic import BaseModel, Field


class PageQualityReport(BaseModel):
    page_index: int
    route: Literal["vector", "raster"]
    status: Literal["ok", "failed"]
    ssim: float | None = None
    text_region_mae: float | None = None
    heatmap_path: str | None = None
    editable_elements: int = 0
    degraded_elements: int = 0
    low_confidence_elements: list[str] = Field(default_factory=list)
    missing_fonts: list[str] = Field(default_factory=list)
    elapsed_sec: float = 0.0
    model_calls: int = 0
    error: str | None = None


class DocumentQualityReport(BaseModel):
    source: str
    output_pptx: str | None = None
    total_pages: int = 0
    succeeded_pages: int = 0
    failed_pages: int = 0
    pages: list[PageQualityReport] = Field(default_factory=list)


def filter_needs_review(
    report: DocumentQualityReport, ssim_threshold: float = 0.90
) -> list[PageQualityReport]:
    flagged: list[PageQualityReport] = []
    for p in report.pages:
        if p.status != "ok":
            flagged.append(p)
        elif p.degraded_elements > 0:
            flagged.append(p)
        elif p.ssim is not None and p.ssim < ssim_threshold:
            flagged.append(p)
        elif len(p.low_confidence_elements) > 0:
            flagged.append(p)
    return flagged
