"""Raw documents are stored on disk by their SHA-256 hash (content-addressed).
The same content is only ever stored once, and a stored file never changes."""

import hashlib
from pathlib import Path

RAW_DIR = Path(__file__).resolve().parents[3] / "data" / "raw"

EXTENSIONS = {"text/html": ".html", "application/pdf": ".pdf"}


def content_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def save_raw(body: bytes, content_type: str | None, root: Path = RAW_DIR) -> tuple[str, Path]:
    digest = content_hash(body)
    extension = EXTENSIONS.get(content_type or "", ".bin")
    path = root / digest[:2] / f"{digest}{extension}"  # 256 subfolders, not one huge folder
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(body)
        tmp.replace(path)  # atomic: a crash never leaves a half-written file
    return digest, path
