import json
import os
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Annotated, Literal

import typer

from pptkit.adapters.ocr import OCREngineType
from pptkit.ingest.loader import SUPPORTED_EXTS, IngestError, load_input
from pptkit.ir.models import PresentationIR, SlideIR
from pptkit.raster.master import induct_slide_masters
from pptkit.raster.pipeline import reconstruct_raster_slide
from pptkit.raster.quantize import quantize_presentation
from pptkit.report.reporter import (
    DocumentQualityReport,
    PageQualityReport,
    filter_needs_review,
)
from pptkit.vector.parser import parse_vector_pdf_page
from pptkit.writer.pptx_writer import write_pptx

app = typer.Typer(
    name="pptkit",
    help="Convert slide images, PDFs, and picture presentations into editable PPTX.",
    no_args_is_help=True,
)


def version_callback(value: bool) -> None:
    if value:
        from pptkit import __version__

        typer.echo(f"pptkit v{__version__}")
        raise typer.Exit()


@app.callback()
def _main_callback(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            "-V",
            callback=version_callback,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = None,
) -> None:
    """ppt-kit: Convert slide images, PDFs, and picture presentations into editable PPTX."""


def _parse_pages_spec(pages_spec: str | None, total_pages: int) -> set[int]:
    if not pages_spec or not pages_spec.strip():
        return set(range(total_pages))
    selected: set[int] = set()
    for part in pages_spec.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_s, end_s = token.split("-", 1)
            start_idx = max(1, int(start_s))
            end_idx = min(total_pages, int(end_s))
            for one_based in range(start_idx, end_idx + 1):
                selected.add(one_based - 1)
        else:
            idx = int(token) - 1
            if 0 <= idx < total_pages:
                selected.add(idx)
    return selected


def _resolve_api_key(provider: Literal["gemini", "openai"]) -> str | None:
    if provider == "gemini":
        env_vars = ("PPTKIT_GEMINI_API_KEY", "GEMINI_API_KEY")
    else:
        env_vars = ("PPTKIT_OPENAI_API_KEY", "OPENAI_API_KEY")

    for var in env_vars:
        val = os.environ.get(var, "").strip()
        if val:
            return val

    cfg_path = Path(
        os.environ.get("PPTKIT_CONFIG_PATH", str(Path.home() / ".config/pptkit/config.toml"))
    )
    if cfg_path.exists():
        try:
            cfg = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
            key_val = str(cfg.get(provider, {}).get("api_key", "")).strip()
            if key_val:
                return key_val
        except Exception:
            pass
    return None


def _convert_single_file(
    src_file: Path,
    out_dir: Path,
    route_opt: Literal["auto", "vector", "raster"],
    provider: Literal["gemini", "openai"],
    pages_spec: str | None = None,
    max_iter: int = 1,
    use_vlm: bool = False,
    ocr_engine: OCREngineType = "auto",
) -> tuple[int, int, DocumentQualityReport]:
    ingested = load_input(src_file, route_override=route_opt)
    out_dir.mkdir(parents=True, exist_ok=True)
    assets_dir = out_dir / f".{src_file.stem}_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    selected_indices = _parse_pages_spec(pages_spec, len(ingested.pages))
    target_pages = [p for p in ingested.pages if p.page_index in selected_indices]

    api_key = _resolve_api_key(provider)
    env_hint = (
        "PPTKIT_GEMINI_API_KEY 或 GEMINI_API_KEY"
        if provider == "gemini"
        else "PPTKIT_OPENAI_API_KEY 或 OPENAI_API_KEY"
    )

    slides_ir: list[SlideIR] = []
    page_reports: list[PageQualityReport] = []
    succeeded = 0
    failed = 0
    start_all = time.perf_counter()

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        for idx_in_batch, page in enumerate(target_pages):
            t0 = time.perf_counter()
            if page.route == "raster" and use_vlm and not api_key:
                failed += 1
                msg = (
                    f"第 {page.page_index + 1} 页启用了 --vlm 需要 API Key。"
                    f"请设置环境变量 {env_hint}，或在 ~/.config/pptkit/config.toml 中配置。"
                )
                typer.echo(msg, err=True)
                page_reports.append(
                    PageQualityReport(
                        page_index=page.page_index,
                        route=page.route,
                        status="failed",
                        error=msg,
                        elapsed_sec=round(time.perf_counter() - t0, 4),
                    )
                )
                continue

            img_tmp = tmp_dir / f"page_{page.page_index:03d}.png"
            img_tmp.write_bytes(page.raster_png_bytes)

            if page.route == "raster":
                rec = reconstruct_raster_slide(
                    image_path=img_tmp,
                    page_index=page.page_index,
                    work_dir=assets_dir / f"p{page.page_index:03d}",
                    max_iter=max_iter,
                    enable_render_refine=(max_iter > 0),
                    ocr_engine=ocr_engine,
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
                        missing_fonts=[],
                        tables_count=rec.tables_count,
                        table_cells_count=rec.table_cells_count,
                        elapsed_sec=elapsed,
                        model_calls=1 if use_vlm else 0,
                    )
                )
            else:
                # Vector PDF direct parser (M4)
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
                    1 for e in vec_res.slide_ir.elements if not getattr(e, "degraded", False)
                )
                degraded_count = sum(
                    1 for e in vec_res.slide_ir.elements if getattr(e, "degraded", False)
                )

                page_reports.append(
                    PageQualityReport(
                        page_index=page.page_index,
                        route=page.route,
                        status="ok",
                        editable_elements=editable_count,
                        degraded_elements=degraded_count,
                        low_confidence_elements=vec_res.low_confidence_ids,
                        missing_fonts=vec_res.missing_fonts,
                        elapsed_sec=elapsed,
                        model_calls=0,
                    )
                )

            done_cnt = idx_in_batch + 1
            avg_sec = (time.perf_counter() - start_all) / done_cnt
            eta_sec = max(0.0, avg_sec * (len(target_pages) - done_cnt))
            ocr_tag = f", ocr={ocr_engine}" if page.route == "raster" else ""
            typer.echo(
                f"[{src_file.name}] 进度 {done_cnt}/{len(target_pages)} 页 "
                f"(route={page.route}{ocr_tag}, ETA={eta_sec:.1f}s)",
                err=True,
            )

        pptx_out = out_dir / f"{src_file.stem}.pptx"
        if src_file.resolve() == pptx_out.resolve():
            pptx_out = out_dir / f"{src_file.stem}.converted.pptx"
        if slides_ir:
            masters, slides_ir = induct_slide_masters(slides_ir)
            pres_ir = PresentationIR(
                source_path=str(src_file),
                width_emu=slides_ir[0].width_emu,
                height_emu=slides_ir[0].height_emu,
                masters=masters,
                slides=slides_ir,
            )
            pres_ir = quantize_presentation(pres_ir)
            write_pptx(pres_ir, pptx_out)

    doc_report = DocumentQualityReport(
        source=str(src_file),
        output_pptx=str(pptx_out) if succeeded > 0 else None,
        total_pages=len(target_pages),
        succeeded_pages=succeeded,
        failed_pages=failed,
        pages=page_reports,
    )
    report_path = out_dir / f"{src_file.stem}.report.json"
    report_path.write_text(doc_report.model_dump_json(indent=2), encoding="utf-8")
    return succeeded, failed, doc_report


@app.command("convert")
def convert_cmd(
    input_path: Annotated[
        Path,
        typer.Argument(
            metavar="<input_path>",
            help="Input slide file (.png, .jpg, .webp, .pdf, .pptx) or directory of slide files",
        ),
    ],
    output_dir: Annotated[
        Path,
        typer.Option(
            "-o",
            "--output",
            help="Output directory for generated PPTX and quality report",
        ),
    ] = Path("out"),
    route: Annotated[
        Literal["auto", "vector", "raster"],
        typer.Option(
            "--route",
            help="Route: auto (detect), vector (direct PDF parse), or raster (OCR + layers)",
        ),
    ] = "auto",
    ocr_engine: Annotated[
        OCREngineType,
        typer.Option(
            "--ocr-engine",
            help="OCR engine: auto (Apple Vision/RapidOCR), apple_vision, or rapidocr",
        ),
    ] = "auto",
    pages: Annotated[
        str | None,
        typer.Option(
            "--pages",
            help="1-based page range or list to convert, e.g. '1-3,5' (default: all pages)",
        ),
    ] = None,
    max_iter: Annotated[
        int,
        typer.Option(
            "--max-iter",
            help="Max render-compare refinement iterations (0 = skip refinement)",
        ),
    ] = 1,
    provider: Annotated[
        Literal["gemini", "openai"],
        typer.Option(
            "--provider",
            help="Cloud model provider when --vlm is enabled (gemini or openai)",
        ),
    ] = "gemini",
    vlm: Annotated[
        bool,
        typer.Option(
            "--vlm",
            help="Require cloud VLM enhancement for difficult elements (requires API key)",
        ),
    ] = False,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit pure JSON summary to stdout (progress logs redirect to stderr)",
        ),
    ] = False,
) -> None:
    """Convert slide images, PDFs, or picture presentations into editable PPTX."""
    if not input_path.exists():
        typer.echo(f"错误：输入路径不存在：{input_path}", err=True)
        raise typer.Exit(code=1)

    target_files: list[Path] = []
    if input_path.is_dir():
        for child in sorted(input_path.iterdir()):
            if child.is_file() and child.suffix.lower() in SUPPORTED_EXTS:
                target_files.append(child)
        if not target_files:
            typer.echo(f"错误：目录中未找到受支持的输入文件：{input_path}", err=True)
            raise typer.Exit(code=1)
    else:
        target_files = [input_path]

    total_succeeded = 0
    total_failed = 0
    reports: list[dict[str, object]] = []

    for fpath in target_files:
        try:
            succ, fail, rep = _convert_single_file(
                fpath,
                output_dir,
                route,
                provider,
                pages_spec=pages,
                max_iter=max_iter,
                use_vlm=vlm,
                ocr_engine=ocr_engine,
            )
            total_succeeded += succ
            total_failed += fail
            reports.append(rep.model_dump())
        except IngestError as exc:
            total_failed += 1
            typer.echo(f"错误 [{exc.code}]：{exc.message}。建议：{exc.hint}", err=True)
            reports.append(
                {
                    "source": str(fpath),
                    "error_code": exc.code,
                    "message": exc.message,
                    "hint": exc.hint,
                }
            )

    summary = {
        "files": len(target_files),
        "succeeded_pages": total_succeeded,
        "failed_pages": total_failed,
        "reports": reports,
    }
    if json_out:
        sys.stdout.write(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    else:
        typer.echo(
            f"转换完成：成功 {total_succeeded} 页，失败 {total_failed} 页，输出目录：{output_dir}"
        )

    if total_succeeded == 0:
        raise typer.Exit(code=1)
    if total_failed > 0:
        raise typer.Exit(code=2)
    raise typer.Exit(code=0)


@app.command("report")
def report_cmd(
    report_file: Annotated[
        Path,
        typer.Argument(
            metavar="<report_file>",
            help="Path to conversion quality report (<name>.report.json)",
        ),
    ],
    needs_review: Annotated[
        bool,
        typer.Option(
            "--needs-review",
            help="Filter and list only pages with low SSIM or degraded layers requiring review",
        ),
    ] = False,
    ssim_threshold: Annotated[
        float,
        typer.Option(
            "--ssim-threshold",
            help="SSIM similarity threshold below which a page requires review",
        ),
    ] = 0.90,
    json_out: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit filtered report as pure JSON to stdout",
        ),
    ] = False,
) -> None:
    """Inspect quality metrics and filter pages requiring human review."""
    if not report_file.exists():
        typer.echo(f"错误：报告文件不存在：{report_file}", err=True)
        raise typer.Exit(code=1)

    doc_rep = DocumentQualityReport.model_validate_json(report_file.read_text(encoding="utf-8"))
    pages = (
        filter_needs_review(doc_rep, ssim_threshold=ssim_threshold)
        if needs_review
        else doc_rep.pages
    )
    payload = {
        "source": doc_rep.source,
        "needs_review_count": len(pages),
        "pages": [p.model_dump() for p in pages],
    }
    if json_out:
        sys.stdout.write(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    else:
        typer.echo(f"共筛出 {len(pages)} 页：{[p.page_index + 1 for p in pages]}")


@app.command("gui")
def gui_cmd(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            "-p",
            help="Port to bind local Web GUI server to (auto-increments if occupied)",
        ),
    ] = 8765,
    host: Annotated[
        str,
        typer.Option(
            "--host",
            "-h",
            help="Host interface to bind to (e.g. 127.0.0.1 or 0.0.0.0)",
        ),
    ] = "127.0.0.1",
    no_browser: Annotated[
        bool,
        typer.Option(
            "--no-browser",
            help="Start server without automatically opening the default browser",
        ),
    ] = False,
) -> None:
    """Start local Web GUI conversion workstation in browser."""
    import webbrowser

    from pptkit.gui.server import PPTKitServer, find_available_port

    try:
        actual_port = find_available_port(host=host, start_port=port, max_tries=10)
    except Exception as e:
        typer.echo(f"错误：端口分配失败：{e}", err=True)
        raise typer.Exit(code=1) from e

    if actual_port != port:
        typer.echo(f"提示：端口 {port} 已被占用，自动切换至端口 {actual_port}")

    url = f"http://{host}:{actual_port}"
    server = PPTKitServer(host=host, port=actual_port)

    typer.echo("✦ ppt-kit GUI 正在运行")
    typer.echo(f"  地址: {url}")
    typer.echo("  按 Ctrl+C 停止服务\n")

    if not no_browser:
        webbrowser.open(url)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        typer.echo("\n服务已停止。")
    finally:
        server.shutdown()
        server.server_close()
