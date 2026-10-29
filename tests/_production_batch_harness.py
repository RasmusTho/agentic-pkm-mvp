"""Synthetic native sources with all client versions obtained through HTTP."""
from uuid import uuid4

from tests._production_operation_harness import production_operation_host


def production_batch_host(tmp_path, monkeypatch, *, count=2, extra_roots=()):
    host = production_operation_host(tmp_path, monkeypatch, extra_roots=extra_roots)
    sources = [(host.artifact_id, host.note)]
    for index in range(1, count):
        identity = str(uuid4())
        note = host.root / "Notes" / f"human-{index}.md"
        note.write_text(f"---\nuuid: {identity}\nartifact_class: human_knowledge\ntrust: human\n---\nOriginal {index}.\n")
        sources.append((identity, note))
    return host, sources


def batch_command(host, sources, *, batch_id="batch-1", kind="artifact.update"):
    items = []
    for index, (identity, _) in enumerate(sources):
        arguments = ({"body": f"HTTP batch body {index}.\n"} if kind == "artifact.update"
                     else {"name": f"renamed-{index}.md"} if kind == "artifact.rename"
                     else {"destination": f"Notes/moved-{index}.md"})
        command = dict(operation_id=kind, request_id=f"{batch_id}:{index}",
            active_context_ref=host.selection["context"]["context_id"],
            vault_generation=str(host.selection["context"]["generation"]),
            target_binding_id=host.binding_id, targets=[{"artifact_id": identity}], arguments=arguments)
        observed = host.client.post("/api/operations/preconditions", headers=host.headers, json=command)
        assert observed.status_code == 200, observed.text
        proof = observed.json()
        assert proof["status"] == "observed", proof
        items.append(dict(request_id=command["request_id"], artifact_id=identity,
            expected_version=proof["expected_version"], arguments=proof["arguments"]))
    return dict(batch_id=batch_id, operation_id=kind,
        active_context_ref=host.selection["context"]["context_id"],
        vault_generation=str(host.selection["context"]["generation"]),
        target_binding_id=host.binding_id, items=items)


def preview_batch(host, command):
    result = host.client.post("/api/operations/batches/preview", headers=host.headers, json=command)
    assert result.status_code == 200, result.text
    proof = result.json()
    assert proof["status"] == "pending", proof
    return proof


def batch_action(host, preview, action="execute"):
    return host.client.post(f"/api/operations/batches/{preview['batch_id']}/{action}",
        headers=host.headers, json={"expected_digest": preview["digest"]})


def batch_inspect(host, preview):
    return host.client.get(f"/api/operations/batches/{preview['batch_id']}",
        headers=host.headers, params={"expected_digest": preview["digest"]})
