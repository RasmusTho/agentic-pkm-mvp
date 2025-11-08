import sys, pathlib, re
roots = [pathlib.Path("."), pathlib.Path("docs")]
bad = []
for root in roots:
    if not root.exists():
        continue
    for p in root.rglob("*.md"):
        t = p.read_text(encoding="utf-8", errors="ignore")
        if t.count("```") % 2 != 0:
            bad.append(str(p))
        # snabba sanity-checks för blandade staket
        if re.search(r"```[a-zA-Z]+\s*$", t, flags=re.M) and "```" not in t.rstrip().splitlines()[-1]:
            pass
if bad:
    print("Unclosed code fences in:")
    for f in bad:
        print(f" - {f}")
    sys.exit(1)
print("Docs code fences OK")
