"""Session management and input validation for local GUI."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import fitz
from PIL import Image
from pptx import Presentation

SUPPORTED_EXTENSIONS = {".pdf", ".pptx", ".png", ".jpg", ".jpeg", ".webp"}


@dataclass
class SessionInfo:
    """Metadata describing an uploaded presentation or slide."""

    session_id: str
    filename: str
    file_size: int
    file_type: str
    page_count: int
    input_path: Path
    session_dir: Path

    def to_dict(self) -> dict[str, object]:
        """Convert session info to JSON-serializable dictionary."""
        data = asdict(self)
        data["input_path"] = str(self.input_path)
        data["session_dir"] = str(self.session_dir)
        data["preview_url"] = f"/api/preview/{self.session_id}/page_0"
        return data

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SessionInfo:
        """Reconstruct session info from serialized dictionary."""
        return cls(
            session_id=str(data["session_id"]),
            filename=str(data["filename"]),
            file_size=int(str(data["file_size"])),
            file_type=str(data["file_type"]),
            page_count=int(str(data["page_count"])),
            input_path=Path(str(data["input_path"])),
            session_dir=Path(str(data["session_dir"])),
        )


class SessionManager:
    """Manages active conversion sessions and isolates filesystem storage."""

    DEFAULT_BASE_DIR: ClassVar[Path] = Path.home() / ".cache" / "pptkit" / "sessions"

    def __init__(self, base_dir: Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir is not None else self.DEFAULT_BASE_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, SessionInfo] = {}

    def create_session(self, filename: str, content: bytes) -> SessionInfo:
        """Create a new session, persist uploaded content, and extract metadata."""
        ext = Path(filename).suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Unsupported file format: {ext or 'none'}. "
                f"Only {', '.join(sorted(SUPPORTED_EXTENSIONS))} supported."
            )

        now_str = datetime.now().strftime("%Y%m%d")
        rand_suffix = uuid.uuid4().hex[:8]
        session_id = f"sess_{now_str}_{rand_suffix}"

        session_dir = self.base_dir / session_id
        session_dir.mkdir(parents=True, exist_ok=True)

        input_path = session_dir / filename
        input_path.write_bytes(content)

        file_type = ext.lstrip(".")
        page_count = self._detect_page_count(input_path, file_type, content)

        info = SessionInfo(
            session_id=session_id,
            filename=filename,
            file_size=len(content),
            file_type=file_type,
            page_count=page_count,
            input_path=input_path,
            session_dir=session_dir,
        )

        meta_file = session_dir / "session.json"
        meta_file.write_text(
            json.dumps(info.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

        self._sessions[session_id] = info
        return info

    def get_session(self, session_id: str) -> SessionInfo | None:
        """Retrieve an existing session by ID from memory or cache directory."""
        if session_id in self._sessions:
            return self._sessions[session_id]

        meta_file = self.base_dir / session_id / "session.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                info = SessionInfo.from_dict(data)
                self._sessions[session_id] = info
                return info
            except Exception:
                return None
        return None

    def _detect_page_count(self, file_path: Path, file_type: str, content: bytes) -> int:
        if file_type == "pdf":
            try:
                with fitz.open(stream=content, filetype="pdf") as doc:
                    return max(1, int(doc.page_count))
            except Exception:
                return 1
        elif file_type == "pptx":
            try:
                prs = Presentation(str(file_path))
                return max(1, len(prs.slides))
            except Exception:
                return 1
        elif file_type in {"png", "jpg", "jpeg", "webp"}:
            try:
                with Image.open(file_path) as img:
                    return getattr(img, "n_frames", 1)
            except Exception:
                return 1
        return 1
