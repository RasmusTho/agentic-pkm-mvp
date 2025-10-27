import json
from pathlib import Path

import yaml
from jsonschema import validate, Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SETTINGS_YAML = ROOT / "vault/_system/settings/system-settings.yaml"
SCHEMA = ROOT / "schemas/system-settings.schema.json"

def test_system_settings_yaml_conforms_to_schema():
    data = yaml.safe_load(SETTINGS_YAML.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validate(instance=data, schema=schema)
