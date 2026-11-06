import hashlib
import json
from pathlib import Path
from uuid import uuid4


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def save(root: Path, source_id: str, content: bytes, metadata: dict) -> str:
    directory = root / source_id / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "original.html"
    with path.open("xb") as stream:
        stream.write(content)
    with (directory / "metadata.json").open("x", encoding="utf-8") as stream:
        json.dump(metadata, stream, ensure_ascii=False, indent=2)
    return str(path.relative_to(root))
