"""Fast protection floors for the debrief's byte patch and retrieval admission."""
from uuid import uuid4

import pytest

from app.episode_debrief.synthesis import DebriefSynthesisError, append_debrief_ref_text
from app.episode_debrief.trigger import debrief_id_for_episode
from app.expansion.create import CreateRequest, InvalidOutputKindError, OutputKind, run_create_pass
from app.retrieval import hybrid
from app.retrieval.capability import RetrievalRequest, retrieve
from scripts.yaml_roundtrip import load_frontmatter


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("existing", ["", "debrief_ref: []\n", "debrief_ref:\n  - debrief-" + "a" * 64 + "\n"])
def test_ref_patch_preserves_all_other_bytes(newline, existing):
    ep = "ep-" + str(uuid4())
    raw = f"---\nepisode_id: {ep}\nscope: work\n# human comment\ntitle: 'Human title'\ntime: {{start: '2026-10-13T08:00:00Z', closed: true}}\n{existing}segmentation: re-cut\n---\nHuman body.  \n"
    raw = raw.replace("\n", newline)
    result = append_debrief_ref_text(raw, episode_id=ep, scope="work", debrief_id=debrief_id_for_episode(ep))
    before_fm, before_body = load_frontmatter(raw)
    after_fm, after_body = load_frontmatter(result)
    after_fm.pop("debrief_ref")
    before_fm.pop("debrief_ref", None)
    assert after_fm == before_fm and before_body == after_body
    assert f"# human comment{newline}title: 'Human title'" in result
    assert result.endswith(f"Human body.  {newline}")
    assert append_debrief_ref_text(result, episode_id=ep, scope="work", debrief_id=debrief_id_for_episode(ep)) == result


def test_bound_retrieval_prefilters_scope_and_binding_without_ranking(monkeypatch):
    monkeypatch.setattr(hybrid, "_STORE", hybrid.MemoryHybridStore())
    monkeypatch.setattr(hybrid, "_revalidate_cache_generation", lambda: None)
    monkeypatch.setattr(hybrid, "_rank_eligible", lambda *_args, **_kwargs: pytest.fail("membership lookup must not rank"))
    docs = [
        {"doc_id": "admitted", "text": "Source", "payload": {"domain": "work", "vault_binding_id": "A", "evidence_role": "background"}},
        {"doc_id": "foreign-scope", "text": "Secret", "payload": {"domain": "private", "vault_binding_id": "A"}},
        {"doc_id": "foreign-binding", "text": "Other vault", "payload": {"domain": "work", "vault_binding_id": "B"}},
        {"doc_id": "unattributed", "text": "Unproven vault", "payload": {"domain": "work"}},
    ]
    hybrid._STORE.set_documents(docs)
    response = retrieve(RetrievalRequest(query="ignored", scope="work", artifact_ids=tuple(d['doc_id'] for d in docs), artifact_binding_ids=("A",)))
    assert [hit.object_id for hit in response.hits] == ["admitted"]
    assert response.hits[0].evidence_role_in_context == "background"


def test_debrief_kind_cannot_be_run_as_unbound_explicit_ask(tmp_path):
    with pytest.raises(InvalidOutputKindError):
        run_create_pass(CreateRequest(kind=OutputKind.EPISODE_DEBRIEF, title="Not triggered", sources=()), vault_root=tmp_path, outbox_path=tmp_path / "outbox.jsonl")
    assert not list(tmp_path.iterdir())


def test_duplicate_yaml_fields_are_refused():
    ep = "ep-" + str(uuid4())
    raw = f"---\nepisode_id: {ep}\nscope: work\nscope: work\ntitle: Human\ntime: {{start: '2026-10-13T08:00:00Z', closed: true}}\nsegmentation: accepted\n---\nHuman body.\n"
    with pytest.raises((DebriefSynthesisError, ValueError)):
        append_debrief_ref_text(raw, episode_id=ep, scope="work", debrief_id=debrief_id_for_episode(ep))


def test_alias_cannot_redirect_debrief_ref_patch_into_human_goal():
    ep = 'ep-' + str(uuid4())
    raw = f"---\nepisode_id: {ep}\nscope: work\ntitle: Human\ntime: {{start: '2026-10-13T08:00:00Z', closed: true}}\ngoal: &items []\ndebrief_ref: *items\nsegmentation: accepted\n---\nHuman body.\n"
    with pytest.raises((DebriefSynthesisError, ValueError)):
        append_debrief_ref_text(raw, episode_id=ep, scope='work', debrief_id=debrief_id_for_episode(ep))


@pytest.mark.parametrize('state', ['evergreen', 'promoted', 'processed', 'inbox', 'logged'])
def test_content_fingerprint_preserves_legacy_state_equivalence(state):
    from app.episode_debrief.evidence import commitment_content_fingerprint
    from app.domain.state_axes import normalize_artifact_state_axes
    fields = {'review_state':state, 'summary':'Send report', 'target_ref':'report-A',
              'commitment_id':'c-1', 'commitment_state':'next'}
    emitted = normalize_artifact_state_axes(fields, default_review_state='provisional')
    assert commitment_content_fingerprint(fields, 'Send report') == commitment_content_fingerprint(emitted, 'Send report')
    emitted['target_ref'] = 'contract-B'
    assert commitment_content_fingerprint(fields, 'Send report') != commitment_content_fingerprint(emitted, 'Send report')
