import shutil
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf
from PIL import Image

POWERPOINT_APP = Path("/Applications/Microsoft PowerPoint.app")
LIBREOFFICE_BIN = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
POWERPOINT_SANDBOX_DOCS = (
    Path.home() / "Library/Containers/com.microsoft.Powerpoint/Data/Documents/pptkit"
)


@dataclass
class RenderOutput:
    renderer: Literal["powerpoint", "libreoffice"]
    pdf_path: Path
    png_paths: list[Path]


def _pdf_to_pngs(
    pdf_path: Path,
    out_dir: Path,
    stem: str,
    target_size: tuple[int, int] | None = None,
) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open(pdf_path)
    png_paths: list[Path] = []
    try:
        for idx in range(len(doc)):
            page = doc[idx]
            if target_size is not None:
                tw, th = target_size
                mat = pymupdf.Matrix(tw / page.rect.width, th / page.rect.height)
                pix = page.get_pixmap(matrix=mat, alpha=False)
            else:
                pix = page.get_pixmap(dpi=150, alpha=False)
            p_out = out_dir / f"{stem}_page_{idx:03d}.png"
            pix.save(p_out)
            if target_size is not None and (pix.width, pix.height) != target_size:
                with Image.open(p_out) as im:
                    im.resize(target_size, Image.Resampling.LANCZOS).save(p_out)
            png_paths.append(p_out)
    finally:
        doc.close()
    return png_paths


def render_with_powerpoint(
    pptx_path: Path | str,
    out_dir: Path | str,
    target_size: tuple[int, int] | None = None,
) -> RenderOutput:
    src = Path(pptx_path).resolve()
    dst_dir = Path(out_dir).resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)

    run_id = uuid.uuid4().hex[:10]
    sandbox_dir = POWERPOINT_SANDBOX_DOCS / run_id
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    sandbox_pptx = sandbox_dir / src.name
    sandbox_pdf = sandbox_dir / f"{src.stem}.pdf"
    shutil.copy2(src, sandbox_pptx)

    script = f"""
    with timeout of 60 seconds
    tell application "Microsoft PowerPoint"
        open POSIX file "{sandbox_pptx}"
        delay 0.8
        set pres to active presentation
        save pres in ("{sandbox_pdf}" as POSIX file) as save as PDF
        close pres saving no
    end tell
    end timeout
    """
    try:
        subprocess.run(
            ["osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
        final_pdf = dst_dir / f"{src.stem}.rendered.pdf"
        shutil.copy2(sandbox_pdf, final_pdf)
    finally:
        shutil.rmtree(sandbox_dir, ignore_errors=True)

    pngs = _pdf_to_pngs(final_pdf, dst_dir, src.stem, target_size=target_size)
    return RenderOutput(renderer="powerpoint", pdf_path=final_pdf, png_paths=pngs)


def render_with_libreoffice(
    pptx_path: Path | str,
    out_dir: Path | str,
    target_size: tuple[int, int] | None = None,
) -> RenderOutput:
    src = Path(pptx_path).resolve()
    dst_dir = Path(out_dir).resolve()
    dst_dir.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        [
            str(LIBREOFFICE_BIN),
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(dst_dir),
            str(src),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    lo_pdf = dst_dir / f"{src.stem}.pdf"
    final_pdf = dst_dir / f"{src.stem}.rendered.pdf"
    if lo_pdf != final_pdf and lo_pdf.exists():
        lo_pdf.replace(final_pdf)

    pngs = _pdf_to_pngs(final_pdf, dst_dir, src.stem, target_size=target_size)
    return RenderOutput(renderer="libreoffice", pdf_path=final_pdf, png_paths=pngs)


def render_pptx(
    pptx_path: Path | str,
    out_dir: Path | str,
    preferred: Literal["auto", "powerpoint", "libreoffice"] = "auto",
    target_size: tuple[int, int] | None = None,
) -> RenderOutput:
    if preferred == "powerpoint" or (preferred == "auto" and POWERPOINT_APP.exists()):
        return render_with_powerpoint(pptx_path, out_dir, target_size=target_size)
    return render_with_libreoffice(pptx_path, out_dir, target_size=target_size)
