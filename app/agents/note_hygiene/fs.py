import os, re, datetime, pathlib, unicodedata
from typing import Tuple

def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-").lower()
    return text or "note"

def archive_path(title: str, base_dir: str = ".") -> str:
    yyyymm = datetime.datetime.now(datetime.UTC).strftime("%Y-%m")
    slug = _slugify(title)[:80]
    folder = os.path.join(base_dir, "Archive", "Trash", yyyymm)
    pathlib.Path(folder).mkdir(parents=True, exist_ok=True)
    return os.path.join(folder, f"{slug}.md")
