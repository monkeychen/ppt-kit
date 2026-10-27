import re
from dataclasses import dataclass, field
from typing import BinaryIO


@dataclass
class UploadedFile:
    filename: str
    content_type: str
    content: bytes


@dataclass
class MultipartFormData:
    files: dict[str, UploadedFile] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


def _extract_boundary(content_type: str) -> bytes:
    if not content_type or "boundary=" not in content_type:
        raise ValueError("Missing or invalid multipart boundary in Content-Type")

    parts = content_type.split("boundary=", 1)
    boundary_str = parts[1].split(";")[0].strip().strip('"').strip("'")
    if not boundary_str:
        raise ValueError("Empty boundary in Content-Type")
    return boundary_str.encode("utf-8")


def parse_multipart(
    stream: BinaryIO | bytes, content_type: str, content_length: int | None = None
) -> MultipartFormData:
    boundary = _extract_boundary(content_type)
    delimiter = b"--" + boundary

    if isinstance(stream, bytes):
        raw_body = stream[:content_length] if content_length is not None else stream
    else:
        raw_body = stream.read(content_length) if content_length is not None else stream.read()

    if not raw_body:
        return MultipartFormData()

    chunks = raw_body.split(delimiter)
    files: dict[str, UploadedFile] = {}
    fields: dict[str, str] = {}

    for chunk in chunks:
        # Strip leading CRLF
        if chunk.startswith(b"\r\n"):
            chunk = chunk[2:]
        elif chunk.startswith(b"\n"):
            chunk = chunk[1:]

        # Terminal chunk or empty
        if not chunk or chunk == b"--" or chunk.startswith(b"--\r\n") or chunk.startswith(b"--\n"):
            continue

        # Split headers and body
        if b"\r\n\r\n" in chunk:
            header_bytes, part_body = chunk.split(b"\r\n\r\n", 1)
        elif b"\n\n" in chunk:
            header_bytes, part_body = chunk.split(b"\n\n", 1)
        else:
            continue

        # Strip trailing CRLF from part_body before next boundary
        if part_body.endswith(b"\r\n"):
            part_body = part_body[:-2]
        elif part_body.endswith(b"\n"):
            part_body = part_body[:-1]

        headers_str = header_bytes.decode("utf-8", errors="replace")
        content_disposition = ""
        part_content_type = "application/octet-stream"

        for line in headers_str.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" in line:
                name, val = line.split(":", 1)
                name_lower = name.strip().lower()
                val_clean = val.strip()
                if name_lower == "content-disposition":
                    content_disposition = val_clean
                elif name_lower == "content-type":
                    part_content_type = val_clean

        if not content_disposition:
            continue

        # Extract field name
        name_match = re.search(r'name="([^"]+)"', content_disposition)
        if not name_match:
            name_match = re.search(r"name=([^\s;]+)", content_disposition)
        if not name_match:
            continue
        field_name = name_match.group(1)

        # Extract filename if file upload
        filename_match = re.search(r'filename="([^"]+)"', content_disposition)
        if not filename_match:
            filename_match = re.search(r"filename=([^\s;]+)", content_disposition)

        if filename_match:
            filename = filename_match.group(1)
            files[field_name] = UploadedFile(
                filename=filename,
                content_type=part_content_type,
                content=part_body,
            )
        else:
            fields[field_name] = part_body.decode("utf-8", errors="replace")

    return MultipartFormData(files=files, fields=fields)
