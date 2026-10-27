import io

import pytest

from pptkit.gui.multipart import MultipartFormData, UploadedFile, parse_multipart


def test_parse_multipart_form_extracts_file_and_fields() -> None:
    boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
    content_type = f"multipart/form-data; boundary={boundary}"

    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="mode"\r\n\r\n'
        "auto\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="presentation.pdf"\r\n'
        "Content-Type: application/pdf\r\n\r\n"
        "%PDF-1.4 mock binary content\r\n"
        f"--{boundary}--\r\n"
    ).encode()

    result = parse_multipart(io.BytesIO(body), content_type=content_type, content_length=len(body))

    assert isinstance(result, MultipartFormData)
    assert result.fields.get("mode") == "auto"
    assert "file" in result.files
    uploaded = result.files["file"]
    assert isinstance(uploaded, UploadedFile)
    assert uploaded.filename == "presentation.pdf"
    assert uploaded.content_type == "application/pdf"
    assert uploaded.content == b"%PDF-1.4 mock binary content"


def test_parse_multipart_invalid_payload_raises_error() -> None:
    # 1. Missing boundary
    with pytest.raises(ValueError, match="boundary"):
        parse_multipart(io.BytesIO(b"random content"), content_type="application/json")

    # 2. Malformed boundary format
    with pytest.raises(ValueError, match="boundary"):
        parse_multipart(io.BytesIO(b"random content"), content_type="multipart/form-data")

    # 3. Empty body
    boundary = "Boundary123"
    content_type = f"multipart/form-data; boundary={boundary}"
    res = parse_multipart(io.BytesIO(b""), content_type=content_type, content_length=0)
    assert len(res.files) == 0
    assert len(res.fields) == 0


def test_parse_multipart_raw_binary_with_null_bytes() -> None:
    boundary = "WebKitBoundaryXYZ"
    content_type = f'multipart/form-data; boundary="{boundary}"'

    raw_binary = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x01\x00"
    body = (
        (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="image"; filename="test.png"\r\n'
            "Content-Type: image/png\r\n\r\n"
        ).encode()
        + raw_binary
        + f"\r\n--{boundary}--\r\n".encode()
    )

    result = parse_multipart(io.BytesIO(body), content_type=content_type, content_length=len(body))
    assert "image" in result.files
    assert result.files["image"].content == raw_binary
    assert result.files["image"].filename == "test.png"
