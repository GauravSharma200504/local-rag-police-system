"""Upload validation and content-addressed file storage (no user-controlled paths → no path traversal)."""
from __future__ import annotations

import hashlib
import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.ingestion.extractors import SUPPORTED_EXTENSIONS

MIME = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


class UploadRejected(Exception):
    pass


@dataclass
class StoredFile:
    path: Path
    sha256: str
    size: int
    ext: str
    mime: str


def safe_filename(name: str) -> str:
    name = Path(name.replace("\\", "/")).name  # strip any directory components
    return "".join(ch for ch in name if ch.isalnum() or ch in " ._-()").strip()[:200] or "document"


def validate_content(ext: str, data: bytes) -> None:
    """Check magic bytes so a renamed executable cannot pass as a document."""
    if ext == ".pdf" and not data.startswith(b"%PDF"):
        raise UploadRejected("File is not a valid PDF")
    if ext == ".docx":
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as z:
                if "word/document.xml" not in z.namelist():
                    raise UploadRejected("File is not a valid DOCX")
        except zipfile.BadZipFile as e:
            raise UploadRejected("File is not a valid DOCX") from e
    if ext == ".png" and not data.startswith(b"\x89PNG"):
        raise UploadRejected("File is not a valid PNG")
    if ext in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8"):
        raise UploadRejected("File is not a valid JPEG")
    if ext == ".txt":
        if b"\x00" in data[:4096] and not data.startswith((b"\xff\xfe", b"\xfe\xff")):
            raise UploadRejected("Text file appears to be binary")


def store_upload(filename: str, data: bytes) -> StoredFile:
    settings = get_settings()
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UploadRejected(f"Unsupported file type '{ext}'. Allowed: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
    if len(data) == 0:
        raise UploadRejected("File is empty")
    if len(data) > settings.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File exceeds {settings.max_upload_mb} MB limit")
    validate_content(ext, data)
    sha = hashlib.sha256(data).hexdigest()
    directory = settings.upload_dir / sha[:2]
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sha}{ext}"
    if not path.exists():
        path.write_bytes(data)
    return StoredFile(path=path, sha256=sha, size=len(data), ext=ext, mime=MIME[ext])
