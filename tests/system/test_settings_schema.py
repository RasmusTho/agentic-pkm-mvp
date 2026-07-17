import json
from pathlib import Path

from jsonschema import validate, Draft7Validator
from app.settings.locations import read_settings_mapping

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_DOCUMENT = ROOT / "vault/settings/system-settings.md"
SCHEMA = ROOT / "schemas/system-settings.schema.json"

def test_system_settings_yaml_conforms_to_schema():
    data = read_settings_mapping(SETTINGS_DOCUMENT)
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft7Validator.check_schema(schema)
    validate(instance=data, schema=schema)
