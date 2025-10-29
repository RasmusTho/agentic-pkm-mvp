from pathlib import Path
import sys, json
from app.agents.merge_resolver.agent import merge_note_from_blobs

def main():
    base, current, other = sys.argv[1], sys.argv[2], sys.argv[3]
    base_txt = Path(base).read_text(encoding="utf-8") if Path(base).exists() else ""
    cur_txt = Path(current).read_text(encoding="utf-8") if Path(current).exists() else ""
    oth_txt = Path(other).read_text(encoding="utf-8") if Path(other).exists() else ""
    merged, info = merge_note_from_blobs(base_txt, cur_txt, oth_txt)
    Path(current).write_text(merged, encoding="utf-8")
    print(json.dumps(info))
    sys.exit(0 if info.get("status") in ("resolved","prompted") else 1)

if __name__ == "__main__":
    main()
