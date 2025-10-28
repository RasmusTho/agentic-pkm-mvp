import json

from app.cli.settings import main as settings_main


def test_cli_policy_outputs_expected_fields(capsys):
    exit_code = settings_main(["--policy", "--json"])
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["debounce_ms"] >= 0
    assert "inactive_grace_s" in payload
    assert "reembed_on_body_diff" in payload


def test_cli_section_rules_returns_list(capsys):
    exit_code = settings_main(["--section", "index.rules", "--json"])
    assert exit_code == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert isinstance(payload, list)
    assert any(rule.get("action") == "soft_exclude" for rule in payload)
