---
version: '1'
system_folder: ⚙️ System
inbox_folder: 📥 Inbox
desk_folder: 🛠️ Workbench
root_folders:
- 📥 Inbox
- 🛠️ Workbench
- 🔍 Focus
- 📁 Projects
- 🧩 Areas
- 💡 Knowledge
- 🗂️ Reference
- 🗄️ Archive
- ⚙️ System
include_folders: []
ignore_glob: []
---

# Vault Layout Contract
This note defines the vault layout contract for agents and ingest defaults.

## Description
- Edit the YAML frontmatter to change folder names or ingest defaults.
- Folders listed here are created if missing; nothing is deleted.
- Unknown folders are allowed to remain.

## Guidance for agents
- System notes live under the system folder.
- Inbox is the capture surface for new notes.
- Desk is the active workspace.
- Root folders define human navigation anchors.
