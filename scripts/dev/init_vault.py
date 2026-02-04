from pathlib import Path
import os
import textwrap
import uuid

import yaml

ROOT = Path(__file__).resolve().parents[2]
VAULT = ROOT / "vault"

INBOX_DIR = (os.getenv("VAULT_INBOX_DIR_REL") or "").strip()
if not INBOX_DIR:
    raise SystemExit("Set VAULT_INBOX_DIR_REL to initialize a dev vault without hardcoded inbox defaults.")

WORKBENCH_DIR = (os.getenv("VAULT_WORKBENCH_DIR_REL") or "").strip()
if not WORKBENCH_DIR:
    raise SystemExit("Set VAULT_WORKBENCH_DIR_REL to initialize a dev vault without hardcoded defaults.")
STRUCTURE = [
    "vault/0_Atlas",
    "vault/1_Calendar/Daily",
    "vault/1_Calendar/Monthly",
    f"vault/{WORKBENCH_DIR}",
    f"vault/{INBOX_DIR}",
    "vault/2_Cards/Concepts",
    "vault/2_Cards/People",
    "vault/2_Cards/Evergreen",
    "vault/3_Sources/Literature",
    "vault/3_Sources/Video",
    "vault/3_Sources/Audio",
    "vault/3_Sources/Series",
    "vault/4_Spaces/Work/Projects",
    "vault/4_Spaces/Work/Areas",
    "vault/4_Spaces/Work/Resources",
    "vault/4_Spaces/Work/Archive",
    "vault/4_Spaces/Family",
    "vault/4_Spaces/Hobbies",
    "vault/9_Extras/Attachments",
    "vault/9_Extras/Templates",
    "vault/9_Extras/textgenerator",
    "vault/9_Extras/Archive",
    "vault/_system/settings",
    "vault/_system/schemas",
    "vault/_system/events",
    "vault/_system/logs",
    "vault/settings",
]


def ensure_dirs():
    for d in STRUCTURE:
        p = ROOT / d
        p.mkdir(parents=True, exist_ok=True)
        (p / ".gitkeep").write_text("", encoding="utf-8")


def write_system_settings_yaml():
    settings_uuid = uuid.uuid4().hex.upper()
    data = {
        "uuid": settings_uuid,
        "title": "System Settings (Canonical)",
        "version": "0.3.0",
        "origin": "local",
        "review_state": "processed",
        "trust": "own",
        "source_ref": "vault://_system/settings/system-settings.yaml",
        "runtime": {
            "environment": "dev",
            "database_url": "postgresql://app:app@localhost:15432/app",
            "enable_outbox": True,
            "enable_tracing": True,
        },
        "paths": {
            "inbox_dir_rel": INBOX_DIR,
            "runtime_dir_rel": "System/Runtime",
            "system_dir_rel": "System",
        },
        "ingest": {
            "active_vault_path": str((VAULT).resolve()),
            "file_glob": ["**/*.md", "**/*.yaml"],
            "ignore_glob": ["_system/**"],
            "write_policy": "write_on_diff",
        },
        "index": {
            "bm25_enabled": True,
            "vector_enabled": True,
            "embedding_model": "deterministic-1536",
            "min_confidence": 0.15,
            "rules": [
                {"when": {"review_state": "inbox"}, "action": "soft_exclude", "weight": 0.05},
                {"when": {"review_state": "archived"}, "action": "include", "weight": 0.25},
                {"when": {"review_state": "promoted"}, "action": "include", "weight": 1.0},
                {"when": {"review_state": "evergreen"}, "action": "include", "weight": 1.2},
            ],
        },
        "observability": {
            "otlp_endpoint": "http://localhost:4317",
            "jaeger_ui": "http://localhost:16686",
            "trace_level": "info",
        },
        "events": {
            "catalog_path": "vault/_system/events/catalog.yaml",
            "sla_outbox_to_index_ms": 2000,
        },
        "sync": {
            "debounce_ms": 1200,
            "inactive_grace_s": 5,
        },
        "agents": {
            "reembed_on_body_diff": True,
        },
    }
    path = ROOT / "vault/_system/settings/system-settings.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")


def write_readable_overview_md():
    md = textwrap.dedent(
        f"""\
    ---
    uuid: "SET-BY-SYSTEM"
    title: "System Settings — Overview"
    origin: "local"
    review_state: "processed"
    trust: "own"
    source_ref: "vault://settings/Overview.md"
    ---

    # System Settings — Overview

    Detta är en **läsbar** översikt för människor. Den **kanoniska** konfigurationen ligger i:

    ```
    vault/_system/settings/system-settings.yaml
    ```

    Rekommendation: öppna YAML-filen ovan när du faktiskt vill ändra värden. Den här sidan länkar vidare, ger förklaringar och kan visa dashboards (Dataview).

    ## Snabbnavigering

    - Kanon: [[../_system/settings/system-settings.yaml]]
    - Eventkatalog: [[../_system/events/]]
    - Scheman: [[../_system/schemas/]]
    - Arbetsyta: [[../{WORKBENCH_DIR}/]]
    - Inbox: [[../{INBOX_DIR}/]]
    """
    )
    (ROOT / "vault/settings/Overview.md").write_text(md, encoding="utf-8")


def write_atlas_home():
    home = textwrap.dedent(
        f"""\
    # Home

    - [[../{WORKBENCH_DIR}/|Workbench]] – skapa nya anteckningar här.
    - [[../{INBOX_DIR}/|Inbox]] – systemets inflöde.
    - [[../settings/Overview|System Settings Overview]]
    - [[../2_Cards/|Cards]] · [[../3_Sources/|Sources]] · [[../4_Spaces/|Spaces]] · [[../9_Extras/|Extras]]
    """
    )
    (ROOT / "vault/0_Atlas/Home.md").write_text(home, encoding="utf-8")


def main():
    ensure_dirs()
    write_system_settings_yaml()
    write_readable_overview_md()
    write_atlas_home()


if __name__ == "__main__":
    main()
