from pptkit.report.reporter import (
    DocumentQualityReport,
    PageQualityReport,
    filter_needs_review,
)


def test_report_model_and_needs_review_filter() -> None:
    p0 = PageQualityReport(
        page_index=0,
        route="raster",
        status="ok",
        ssim=0.96,
        text_region_mae=3.2,
        editable_elements=28,
        degraded_elements=0,
        low_confidence_elements=[],
        missing_fonts=[],
        elapsed_sec=1.5,
        model_calls=0,
    )
    p1 = PageQualityReport(
        page_index=1,
        route="raster",
        status="ok",
        ssim=0.82,
        text_region_mae=18.5,
        editable_elements=10,
        degraded_elements=2,
        low_confidence_elements=["p1-tb-003"],
        missing_fonts=["CustomFont"],
        tables_count=1,
        table_cells_count=8,
        elapsed_sec=2.1,
        model_calls=1,
    )
    doc_rep = DocumentQualityReport(
        source="deck.pdf",
        output_pptx="out/deck.pptx",
        total_pages=2,
        succeeded_pages=2,
        failed_pages=0,
        pages=[p0, p1],
    )

    needs = filter_needs_review(doc_rep, ssim_threshold=0.90)
    assert [p.page_index for p in needs] == [1]
    assert doc_rep.pages[0].tables_count == 0
    assert doc_rep.pages[1].tables_count == 1
    assert doc_rep.pages[1].table_cells_count == 8
