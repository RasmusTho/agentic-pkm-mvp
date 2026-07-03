import os, re, datetime, unicodedata
from datetime import timezone

def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii","ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-").lower()
    return text or "note"

def archive_path(title: str, base_dir: str | os.PathLike[str]) -> str:
    yyyymm = datetime.datetime.now(timezone.utc).strftime("%Y-%m")
    slug = _slugify(title)[:80]
    return os.path.join(os.fspath(base_dir), "Archive", "Trash", yyyymm, f"{slug}.md")
