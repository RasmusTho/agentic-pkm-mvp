from pathlib import Path
import sys
import yaml
from app.index.build import build_index_from_settings, query

def main():
    settings = yaml.safe_load(Path("vault/_system/settings/system-settings.yaml").read_text(encoding="utf-8"))
    idx = build_index_from_settings(settings)
    term = " ".join(sys.argv[1:]) if len(sys.argv) > 0 else ""
    for p, s in query(idx, term):
        print(f"{s:.2f}\t{p}")

if __name__ == "__main__":
    main()
