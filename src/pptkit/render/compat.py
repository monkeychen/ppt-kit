import subprocess
from dataclasses import dataclass
from pathlib import Path

from pptkit.render.renderer import render_with_powerpoint


@dataclass
class AppCompatStatus:
    app_name: str
    opened_ok: bool
    has_repair_or_error_dialog: bool
    screenshot_path: str | None
    detail: str = ""


def check_powerpoint_compat(pptx_path: Path | str, out_dir: Path | str) -> AppCompatStatus:
    out = Path(out_dir) / "powerpoint"
    out.mkdir(parents=True, exist_ok=True)
    res = render_with_powerpoint(pptx_path, out)
    first_png = str(res.png_paths[0]) if res.png_paths else None
    return AppCompatStatus(
        app_name="PowerPoint",
        opened_ok=len(res.png_paths) > 0,
        has_repair_or_error_dialog=False,
        screenshot_path=first_png,
        detail=f"Exported {len(res.png_paths)} page(s) via AppleScript",
    )


def check_keynote_compat(pptx_path: Path | str, out_dir: Path | str) -> AppCompatStatus:
    src = Path(pptx_path).resolve()
    out = Path(out_dir).resolve() / "keynote"
    out.mkdir(parents=True, exist_ok=True)
    shot_path = out / f"{src.stem}_keynote.png"

    script = f"""
    with timeout of 45 seconds
    tell application "Keynote"
        open POSIX file "{src}"
        delay 1.5
        set docCount to count of documents
    end tell
    end timeout
    return docCount
    """
    proc = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    opened_ok = proc.returncode == 0 and int((proc.stdout or "0").strip() or "0") >= 1

    # Capture screen or Keynote window for audit evidence
    subprocess.run(["screencapture", "-x", str(shot_path)], check=False)

    close_script = 'tell application "Keynote" to close every document saving no'
    subprocess.run(["osascript", "-e", close_script], capture_output=True, text=True)

    return AppCompatStatus(
        app_name="Keynote",
        opened_ok=opened_ok,
        has_repair_or_error_dialog=not opened_ok,
        screenshot_path=str(shot_path) if shot_path.exists() else None,
        detail=proc.stderr.strip() if not opened_ok else "Opened cleanly in Keynote",
    )


def check_wps_compat(pptx_path: Path | str, out_dir: Path | str) -> AppCompatStatus:
    src = Path(pptx_path).resolve()
    out = Path(out_dir).resolve() / "wps"
    out.mkdir(parents=True, exist_ok=True)
    shot_path = out / f"{src.stem}_wps.png"

    proc = subprocess.run(
        ["open", "-a", "/Applications/wpsoffice.app", str(src)],
        capture_output=True,
        text=True,
    )
    subprocess.run(["sleep", "2.0"], check=False)
    subprocess.run(["screencapture", "-x", str(shot_path)], check=False)

    return AppCompatStatus(
        app_name="WPS Office",
        opened_ok=proc.returncode == 0,
        has_repair_or_error_dialog=proc.returncode != 0,
        screenshot_path=str(shot_path) if shot_path.exists() else None,
        detail=proc.stderr.strip()
        if proc.returncode != 0
        else "Launched cleanly via open -a wpsoffice.app",
    )
