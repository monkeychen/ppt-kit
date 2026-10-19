import json
import os
import sys
import tempfile
import time
import tomllib
from pathlib import Path
from typing import Annotated, Literal

import typer

from pptkit.ingest.loader import SUPPORTED_EXTS, IngestError, load_input
from pptkit.ir.models import Background, BBox, ImageElement, PresentationIR, SlideIR
from pptkit.writer.pptx_writer import write_pptx

app = typer.Typer(
    name="pptkit",
    help="Convert slide images and PDFs into editable PPTX presentations.",
    no_args_is_help=True,
)


@app.callback()
def _main_callback() -> None:
    """ppt-kit CLI root."""


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
) -> tuple[int, int, dict[str, object]]:
    ingested = load_input(src_file, route_override=route_opt)
    out_dir.mkdir(parents=True, exist_ok=True)

    api_key = _resolve_api_key(provider)
    env_hint = (
        "PPTKIT_GEMINI_API_KEY 或 GEMINI_API_KEY"
        if provider == "gemini"
        else "PPTKIT_OPENAI_API_KEY 或 OPENAI_API_KEY"
    )

    slides_ir: list[SlideIR] = []
    page_reports: list[dict[str, object]] = []
    succeeded = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        for page in ingested.pages:
            t0 = time.perf_counter()
            if page.route == "raster" and not api_key:
                failed += 1
                msg = (
                    f"第 {page.page_index + 1} 页走 raster 路径需要 API Key。"
                    f"请设置环境变量 {env_hint}，或在 ~/.config/pptkit/config.toml 中配置。"
                )
                typer.echo(msg, err=True)
                page_reports.append(
                    {
                        "page_index": page.page_index,
                        "route": page.route,
                        "status": "failed",
                        "error": msg,
                        "elapsed_sec": round(time.perf_counter() - t0, 4),
                    }
                )
                continue

            img_tmp = tmp_dir / f"page_{page.page_index:03d}.png"
            img_tmp.write_bytes(page.raster_png_bytes)

            slide_ir = SlideIR(
                page_index=page.page_index,
                route=page.route,
                width_emu=page.width_emu,
                height_emu=page.height_emu,
                background=Background(fill_type="solid", color_hex="#FFFFFF"),
                elements=[
                    ImageElement(
                        id=f"p{page.page_index}-fallback-bg",
                        bbox=BBox(
                            x=0,
                            y=0,
                            width=page.width_emu,
                            height=page.height_emu,
                        ),
                        z_order=0,
                        image_path=str(img_tmp),
                        source="fallback",
                        degraded=True,
                    )
                ],
            )
            slides_ir.append(slide_ir)
            succeeded += 1
            page_reports.append(
                {
                    "page_index": page.page_index,
                    "route": page.route,
                    "status": "ok",
                    "degraded_elements": 1,
                    "editable_elements": 0,
                    "elapsed_sec": round(time.perf_counter() - t0, 4),
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

    report_data: dict[str, object] = {
        "source": str(src_file),
        "output_pptx": str(out_dir / f"{src_file.stem}.pptx") if succeeded > 0 else None,
        "total_pages": len(ingested.pages),
        "succeeded_pages": succeeded,
        "failed_pages": failed,
        "pages": page_reports,
    }
    report_path = out_dir / f"{src_file.stem}.report.json"
    report_path.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return succeeded, failed, report_data


@app.command("convert")
def convert_cmd(
    input_path: Annotated[Path, typer.Argument(help="Input slide file or directory")],
    output_dir: Annotated[Path, typer.Option("-o", "--output", help="Output directory")] = Path(
        "out"
    ),
    route: Annotated[
        Literal["auto", "vector", "raster"],
        typer.Option("--route", help="Route selection: auto, vector, or raster"),
    ] = "auto",
    provider: Annotated[
        Literal["gemini", "openai"],
        typer.Option("--provider", help="Model provider for raster path"),
    ] = "gemini",
    json_out: Annotated[bool, typer.Option("--json", help="Emit pure JSON to stdout")] = False,
) -> None:
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
            succ, fail, rep = _convert_single_file(fpath, output_dir, route, provider)
            total_succeeded += succ
            total_failed += fail
            reports.append(rep)
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
