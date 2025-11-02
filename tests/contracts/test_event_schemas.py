import json
import glob
from pathlib import Path
from jsonschema import validate

SCHEMA_DIR = Path("app/events/schemas")
FIXTURE_DIR = Path("tests/fixtures/events")

def test_event_examples_validate_against_schemas():
    for schema_path in SCHEMA_DIR.glob("*.schema.json"):
        name = schema_path.name.replace(".schema.json", "")
        example_path = FIXTURE_DIR / f"{name}.example.json"
        assert example_path.exists(), f"Missing example for {name}"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        example = json.loads(example_path.read_text(encoding="utf-8"))
        validate(instance=example, schema=schema)

def test_aliases_map_is_well_formed():
    aliases_path = Path("app/events/aliases.json")
    data = json.loads(aliases_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    for legacy, canonical in data.items():
        assert isinstance(legacy, str) and isinstance(canonical, str)
        assert legacy != "" and canonical != ""
