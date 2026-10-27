"""Asynchronous task runner and real-time event broadcaster for slide conversion."""

from __future__ import annotations

import queue
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pptkit.adapters.ocr import OCREngineType
from pptkit.gui.session import SessionInfo
from pptkit.ingest.loader import load_input
from pptkit.ir.models import PresentationIR, SlideIR
from pptkit.raster.pipeline import reconstruct_raster_slide
from pptkit.report.reporter import DocumentQualityReport, PageQualityReport
from pptkit.vector.parser import parse_vector_pdf_page
from pptkit.writer.pptx_writer import write_pptx


@dataclass
class ConversionOptions:
    """Configurable options for session conversion execution."""

    route: Literal["auto", "vector", "raster"] = "auto"
    provider: Literal["gemini", "openai"] = "gemini"
    use_vlm: bool = False
    ocr_engine: OCREngineType = "auto"
    max_iter: int = 1
    api_key: str | None = None
    pages_spec: str | None = None


class ConversionTask:
    """Manages lifecycle, background worker thread, and SSE event streaming for a session."""

    def __init__(
        self,
        session_info: SessionInfo,
        options: ConversionOptions | None = None,
    ) -> None:
        self.session_info = session_info
        self.options = options or ConversionOptions()
        self.status: Literal["idle", "running", "completed", "failed"] = "idle"
        self.error_message: str | None = None
        self.output_pptx_path: Path | None = None
        self.report_path: Path | None = None
        self.document_report: DocumentQualityReport | None = None

        self._history: list[dict[str, Any]] = []
        self._subscribers: list[queue.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None

    def emit_event(self, event: dict[str, Any]) -> None:
        """Broadcast an event to all active subscriber queues and persist to history."""
        with self._lock:
            self._history.append(event)
            dead_subscribers = []
            for q in self._subscribers:
                try:
                    q.put_nowait(event)
                except Exception:
                    dead_subscribers.append(q)
            for dead in dead_subscribers:
                self._subscribers.remove(dead)

    def subscribe(
        self,
    ) -> tuple[list[dict[str, Any]], queue.Queue[dict[str, Any]]]:
        """Subscribe to event stream.

        Returns historical events and an active queue for future events.
        """
        with self._lock:
            q: queue.Queue[dict[str, Any]] = queue.Queue()
            history = list(self._history)
            self._subscribers.append(q)
            return history, q

    def unsubscribe(self, q: queue.Queue[dict[str, Any]]) -> None:
        """Unregister a subscriber queue."""
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    def start(self) -> None:
        """Launch background worker thread if not already running."""
        with self._lock:
            if self.status == "running":
                return
            self.status = "running"
            self._thread = threading.Thread(target=self._run_conversion, daemon=True)
            self._thread.start()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the background worker terminates."""
        if self._thread:
            self._thread.join(timeout=timeout)

    def _run_conversion(self) -> None:
        try:
            src_file = self.session_info.input_path
            if not src_file.exists():
                raise FileNotFoundError(f"Input file not found: {src_file}")

            ingested = load_input(src_file, route_override=self.options.route)
            total_pages = len(ingested.pages)

            self.emit_event(
                {
                    "type": "start",
                    "session_id": self.session_info.session_id,
                    "total_pages": total_pages,
                }
            )

            out_dir = self.session_info.session_dir / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            assets_dir = self.session_info.session_dir / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)

            slides_ir: list[SlideIR] = []
            page_reports: list[PageQualityReport] = []
            succeeded = 0
            failed = 0

            with tempfile.TemporaryDirectory() as tmp_dir_str:
                tmp_dir = Path(tmp_dir_str)
                for page in ingested.pages:
                    t0 = time.perf_counter()
                    img_tmp = tmp_dir / f"page_{page.page_index:03d}.png"
                    img_tmp.write_bytes(page.raster_png_bytes)

                    # Also cache original image slice in session for preview serving
                    orig_preview = assets_dir / f"orig_p{page.page_index:03d}.png"
                    if not orig_preview.exists():
                        orig_preview.write_bytes(page.raster_png_bytes)

                    try:
                        if page.route == "raster":
                            rec = reconstruct_raster_slide(
                                image_path=img_tmp,
                                page_index=page.page_index,
                                work_dir=assets_dir / f"p{page.page_index:03d}",
                                max_iter=self.options.max_iter,
                                enable_render_refine=(self.options.max_iter > 0),
                                ocr_engine=self.options.ocr_engine,
                            )
                            slides_ir.append(rec.slide_ir)
                            succeeded += 1
                            elapsed = round(time.perf_counter() - t0, 4)
                            page_reports.append(
                                PageQualityReport(
                                    page_index=page.page_index,
                                    route=page.route,
                                    status="ok",
                                    ssim=rec.ssim,
                                    text_region_mae=rec.text_region_mae,
                                    heatmap_path=rec.heatmap_path,
                                    editable_elements=len(rec.slide_ir.elements),
                                    degraded_elements=rec.degraded_count,
                                    low_confidence_elements=rec.low_confidence_ids or [],
                                    elapsed_sec=elapsed,
                                )
                            )
                            self.emit_event(
                                {
                                    "type": "page",
                                    "page_index": page.page_index,
                                    "status": "ok",
                                    "route": "raster",
                                    "ssim": rec.ssim,
                                    "editable_elements": len(rec.slide_ir.elements),
                                    "elapsed_sec": elapsed,
                                }
                            )
                        else:
                            vec_work_dir = assets_dir / f"p{page.page_index:03d}"
                            vec_res = parse_vector_pdf_page(
                                pdf_path=src_file,
                                page_index=page.page_index,
                                work_dir=vec_work_dir,
                            )
                            slides_ir.append(vec_res.slide_ir)
                            succeeded += 1
                            elapsed = round(time.perf_counter() - t0, 4)
                            editable_count = sum(
                                1
                                for e in vec_res.slide_ir.elements
                                if not getattr(e, "degraded", False)
                            )
                            degraded_count = sum(
                                1
                                for e in vec_res.slide_ir.elements
                                if getattr(e, "degraded", False)
                            )
                            page_reports.append(
                                PageQualityReport(
                                    page_index=page.page_index,
                                    route="vector",
                                    status="ok",
                                    ssim=1.0,
                                    text_region_mae=0.0,
                                    heatmap_path=None,
                                    editable_elements=editable_count,
                                    degraded_elements=degraded_count,
                                    low_confidence_elements=[],
                                    elapsed_sec=elapsed,
                                )
                            )
                            self.emit_event(
                                {
                                    "type": "page",
                                    "page_index": page.page_index,
                                    "status": "ok",
                                    "route": "vector",
                                    "ssim": 1.0,
                                    "editable_elements": editable_count,
                                    "elapsed_sec": elapsed,
                                }
                            )
                    except Exception as page_exc:
                        failed += 1
                        err_msg = str(page_exc)
                        elapsed = round(time.perf_counter() - t0, 4)
                        page_reports.append(
                            PageQualityReport(
                                page_index=page.page_index,
                                route=page.route,
                                status="failed",
                                error=err_msg,
                                elapsed_sec=elapsed,
                            )
                        )
                        self.emit_event(
                            {
                                "type": "page",
                                "page_index": page.page_index,
                                "status": "failed",
                                "route": page.route,
                                "error": err_msg,
                                "elapsed_sec": elapsed,
                            }
                        )

            pptx_out = out_dir / f"{src_file.stem}.pptx"
            if slides_ir:
                pres_ir = PresentationIR(
                    source_path=str(src_file),
                    width_emu=slides_ir[0].width_emu,
                    height_emu=slides_ir[0].height_emu,
                    slides=slides_ir,
                )
                write_pptx(pres_ir, pptx_out)
                self.output_pptx_path = pptx_out

            doc_report = DocumentQualityReport(
                source=str(src_file),
                output_pptx=str(pptx_out) if succeeded > 0 else None,
                total_pages=total_pages,
                succeeded_pages=succeeded,
                failed_pages=failed,
                pages=page_reports,
            )
            report_path = out_dir / f"{src_file.stem}.report.json"
            report_path.write_text(doc_report.model_dump_json(indent=2), encoding="utf-8")
            self.report_path = report_path
            self.document_report = doc_report

            valid_ssims = [p.ssim for p in doc_report.pages if p.ssim is not None]
            avg_ssim = sum(valid_ssims) / len(valid_ssims) if valid_ssims else 0.0

            self.status = "completed"
            self.emit_event(
                {
                    "type": "complete",
                    "session_id": self.session_info.session_id,
                    "succeeded_pages": succeeded,
                    "failed_pages": failed,
                    "avg_ssim": round(avg_ssim, 4),
                    "output_pptx": str(pptx_out) if pptx_out.exists() else None,
                    "download_url": f"/api/download/{self.session_info.session_id}",
                }
            )

        except Exception as exc:
            self.status = "failed"
            self.error_message = str(exc)
            self.emit_event(
                {
                    "type": "error",
                    "session_id": self.session_info.session_id,
                    "error_code": "CONVERSION_ERROR",
                    "message": str(exc),
                }
            )
