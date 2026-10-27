#!/usr/bin/env python3
"""Cross-platform build script for ppt-kit.

Supports building:
1. binary: Standalone single-file executable via PyInstaller (bundles Web GUI assets)
2. wheel: Standard Python wheel and source distribution via uv build
3. all: Both wheel and standalone binary
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


def get_repo_root() -> Path:
    """Resolve repository root directory."""
    return Path(__file__).resolve().parent.parent


def format_size(num_bytes: int) -> str:
    """Format byte count into human-readable size."""
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024.0:
            return f"{num_bytes:.2f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.2f} TB"


def clean_artifacts(repo_root: Path) -> None:
    """Clean up build and dist directories and PyInstaller spec files."""
    print("🧹 Cleaning previous build artifacts...")
    for dir_name in ("dist", "build"):
        target_dir = repo_root / dir_name
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
            print(f"   Removed: {dir_name}/")

    for spec_file in repo_root.glob("*.spec"):
        try:
            spec_file.unlink()
            print(f"   Removed: {spec_file.name}")
        except OSError:
            pass


def build_wheel(repo_root: Path) -> int:
    """Build Python wheel and sdist using uv build."""
    print("\n📦 [1/2] Building Python wheel & source distribution (uv build)...")
    cmd = ["uv", "build"]
    print(f"   Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        print("❌ Error: Wheel build failed.", file=sys.stderr)
        return result.returncode

    print("✅ Wheel & sdist build completed successfully.")
    return 0


def build_binary(repo_root: Path) -> int:
    """Build standalone binary executable using PyInstaller via uv."""
    print("\n🚀 [2/2] Building standalone executable binary (PyInstaller)...")

    # Static assets directory
    static_dir = repo_root / "src" / "pptkit" / "gui" / "static"
    if not static_dir.exists():
        print(f"❌ Error: Web GUI static directory not found: {static_dir}", file=sys.stderr)
        return 1

    entry_point = repo_root / "src" / "pptkit" / "__main__.py"
    if not entry_point.exists():
        print(f"❌ Error: Entry point not found: {entry_point}", file=sys.stderr)
        return 1

    # PyInstaller --add-data format: <source><pathsep><target_in_bundle>
    # Unix uses ':', Windows uses ';' (handled by os.pathsep)
    add_data_arg = f"src/pptkit/gui/static{os.pathsep}pptkit/gui/static"

    cmd = [
        "uv",
        "run",
        "--with",
        "pyinstaller",
        "pyinstaller",
        "--noconfirm",
        "--onefile",
        "--add-data",
        add_data_arg,
        "--name",
        "pptkit",
        str(entry_point),
    ]

    print(f"   Platform separator: {repr(os.pathsep)}")
    print(f"   Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=repo_root)
    if result.returncode != 0:
        print("❌ Error: Binary build failed.", file=sys.stderr)
        return result.returncode

    print("✅ Standalone binary build completed successfully.")
    return 0


def list_outputs(repo_root: Path) -> None:
    """Display generated files in dist/."""
    dist_dir = repo_root / "dist"
    if not dist_dir.exists():
        return

    files = sorted(dist_dir.iterdir(), key=lambda p: p.name)
    if not files:
        return

    print("\n🎉 Generated Artifacts in dist/:")
    for file_path in files:
        if file_path.is_file() and not file_path.name.startswith("."):
            size = format_size(file_path.stat().st_size)
            print(f"   • {file_path.name:<32} ({size})")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="ppt-kit convenient packaging tool (supports binary and wheel).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "target",
        nargs="?",
        default="binary",
        choices=["binary", "wheel", "all"],
        help="Build target: 'binary' (executable), 'wheel' (.whl + sdist), or 'all'",
    )
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean dist/, build/, and *.spec before building",
    )

    args = parser.parse_args()
    repo_root = get_repo_root()

    print("=" * 60)
    print(f"🔨 ppt-kit Build Tool (Target: {args.target})")
    print(f"📂 Workspace: {repo_root}")
    print("=" * 60)

    if args.clean:
        clean_artifacts(repo_root)

    ret = 0
    if args.target in ("wheel", "all"):
        ret = build_wheel(repo_root)
        if ret != 0:
            return ret

    if args.target in ("binary", "all"):
        ret = build_binary(repo_root)
        if ret != 0:
            return ret

    list_outputs(repo_root)
    print("\n✨ All tasks finished successfully!\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
