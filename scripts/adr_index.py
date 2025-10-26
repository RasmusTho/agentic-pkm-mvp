import pathlib

adr_dir = pathlib.Path("docs/adr")
items = []
for path in sorted(adr_dir.glob("*.md")):
    if path.name.lower() in {"readme.md", "index.md"}:
        continue
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    title = next((line.lstrip("# ").strip() for line in lines if line.startswith("# ")), path.stem)
    items.append((path.name, title))

lines = ["# ADR Index", ""]
for name, title in items:
    lines.append(f"- [{title}](./{name})")

index_path = adr_dir / "INDEX.md"
index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("Wrote", index_path)
