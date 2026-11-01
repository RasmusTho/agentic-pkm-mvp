"""Canonical passive channel binding/restore probe; no initialization or repair."""

from typing import Any
from urllib.parse import urlparse

from app.ops.operations_acceptance import OperationsAcceptanceRefusal

BINDING_PROBE = r'''
import hashlib,json,os,pathlib,sys,stat
from uuid import UUID
p=json.load(sys.stdin)
assert os.environ.get('PKM_ENVIRONMENT')==p['channel']
root=pathlib.Path(os.environ['VAULT_ROOT']).resolve(strict=True)
assert str(root)==p['vault_path']
# API context/orientation reads can restore last-active and heal identities.
# Inspect the actual restore inputs passively before any such HTTP request.
from app.instance.vault_registry import AppLocalSettingsStore,VaultRegistryStore,default_app_local_settings_path,_app_local_from_registry,REGISTRY_AUTHORITY_ACTIVE
registry=os.environ.get('INSTANCE_VAULT_REGISTRY_PATH','').strip()
ownership=os.environ.get('INSTANCE_OWNERSHIP_ROOT','').strip()
settings=None
snapshot=None
if registry:
 assert ownership and pathlib.Path(registry).is_file(),'fixture_restore_registry_missing'
 registry_store=VaultRegistryStore(pathlib.Path(registry))
 assert stat.S_IMODE(registry_store.path.parent.stat().st_mode)==0o700,'fixture_restore_registry_permissions'
 lock=registry_store.lock_path
 assert lock.is_file() and not lock.is_symlink() and stat.S_IMODE(lock.stat().st_mode)==0o600 and lock.stat().st_uid==os.geteuid(),'fixture_restore_lock_missing'
 assert not registry_store.transaction_path.exists() and not registry_store.scalar_rollback_session_path.exists(),'fixture_restore_transaction_unsupported'
 snapshot=registry_store._read_current_locked(recover=False)
 export=registry_store.rollback_export_path
 assert export.is_file() and not export.is_symlink() and export.read_bytes()==registry_store._rollback_export_payload(snapshot),'fixture_restore_export_missing_or_stale'
 if snapshot.authority==REGISTRY_AUTHORITY_ACTIVE:
  settings=_app_local_from_registry(snapshot)
if settings is None:
 app_path=default_app_local_settings_path()
 assert app_path.is_file() and not app_path.is_symlink(),'fixture_restore_registry_missing'
 settings=AppLocalSettingsStore(path=app_path).load()
known=settings.known_vaults.get(settings.last_active_vault_ref)
assert known is not None and pathlib.Path(known.path).resolve(strict=True)==root,'fixture_restore_target_mismatch'
if snapshot is not None and snapshot.settings_rebind is not None:
 from app.instance.settings_rebind import SettingsRebindRecord
 record=SettingsRebindRecord.from_payload(snapshot.settings_rebind)
 registration=snapshot.registrations.get(record.candidate_binding_id)
 assert record.phase in ('no_lifecycle','committed') and record.applied_revision==record.desired_revision and record.reload_revision==record.desired_revision,'fixture_restore_rebind_unsettled'
 if record.phase=='committed':
  from app.watcher.settings_rebind import settings_rebind_watcher_receipt_path,load_settings_rebind_watcher_receipt
  state_dir=os.environ.get('WATCHER_STATE_DIR','').strip()
  assert state_dir,'fixture_restore_rebind_receipt_missing'
  receipt_path=settings_rebind_watcher_receipt_path(pathlib.Path(state_dir),record.desired_revision)
  assert receipt_path.is_file() and not receipt_path.is_symlink() and stat.S_IMODE(receipt_path.stat().st_mode)==0o600 and receipt_path.stat().st_uid==os.geteuid(),'fixture_restore_rebind_receipt_missing'
  receipt=load_settings_rebind_watcher_receipt(receipt_path)
  assert receipt.stage=='completed' and receipt.desired_revision==record.desired_revision and receipt.prior_binding_id==record.prior_binding_id and receipt.candidate_binding_id==record.candidate_binding_id,'fixture_restore_rebind_receipt_mismatch'
 assert registration is not None and pathlib.Path(registration.path).resolve(strict=True)==root and registration.vault_id in (None,p['vault_id']),'fixture_restore_rebind_target_mismatch'
 assert snapshot.last_active_vault_ref==registration.ref==known.ref,'fixture_restore_rebind_selection_uncommitted'
 ingress=registry_store.path.parent/'settings-rebind-ingress.lock'
 assert ingress.is_file() and not ingress.is_symlink() and stat.S_IMODE(ingress.stat().st_mode)==0o600 and ingress.stat().st_uid==os.geteuid(),'fixture_restore_rebind_lock_missing'
from app.vault.manager import REQUIRED_SETTINGS_FILES,SETTINGS_DIR_NAME
from app.vault.markdown_settings import MarkdownSettingsStore
for name in REQUIRED_SETTINGS_FILES:
 target=root/SETTINGS_DIR_NAME/name
 assert target.is_file() and not target.is_symlink() and target.resolve(strict=True).is_relative_to(root),'fixture_restore_settings_missing'
vault_doc=MarkdownSettingsStore().read(root/SETTINGS_DIR_NAME/'vault.md').frontmatter
local_doc=MarkdownSettingsStore().read(root/SETTINGS_DIR_NAME/'local.md').frontmatter
assert vault_doc.get('schema')=='design-handoff.vault.v1' and isinstance(vault_doc.get('vaultId'),str) and vault_doc['vaultId'].strip() and vault_doc['vaultId'].strip()==p['vault_id'],'fixture_restore_identity_missing'
assert local_doc.get('schema')=='design-handoff.local.v1' and str(local_doc.get('localInstanceId') or '').strip(),'fixture_restore_identity_missing'
'''


def validate_native_gateway(
    d: dict[str, Any], api: dict[str, Any], ui: dict[str, Any], resolved: list[str],
    *, refusal_type: Any = OperationsAcceptanceRefusal,
) -> None:
    """Bind the guest's loopback gateway to this exact Compose API without HTTP reads."""
    for row, service in ((api, "api"), (ui, "companion-ui")):
        labels = row["Config"]["Labels"]
        if (
            not row["State"]["Running"]
            or labels.get("com.docker.compose.project") != "pkm-" + d["channel"]
            or labels.get("com.docker.compose.service") != service
            or labels.get("org.opencontainers.image.revision") != d["expected_sha"]
        ):
            raise refusal_type("native_gateway_container_identity_mismatch")
    env = dict(x.split("=", 1) for x in ui["Config"]["Env"] if "=" in x)
    if (
        env.get("COMPANION_API_BASE_URL") != "http://api:8000"
        or env.get("COMPANION_UI_SERVE_MODULE", "companion_ui.workspace.serve_dev_page")
        != "companion_ui.workspace.serve_dev_page"
        or ui["Config"].get("Entrypoint") is not None
        or ui["Config"]["Cmd"]
        != [
            "/bin/bash",
            "-c",
            'python -m "${COMPANION_UI_SERVE_MODULE:-companion_ui.workspace.serve_dev_page}"',
        ]
    ):
        raise refusal_type("native_gateway_startup_configuration_mismatch")
    ui_port = str(urlparse(d["ui_url"]).port)
    api_port = str(urlparse(d["api_url"]).port)
    if env.get("PORT", "8111") != ui_port:
        raise refusal_type("native_gateway_port_mismatch")
    for row, inner, outer in ((ui, ui_port, ui_port), (api, "8000", api_port)):
        bindings = row["NetworkSettings"]["Ports"].get(inner + "/tcp") or []
        if not any(
            x.get("HostPort") == outer and x.get("HostIp") in {"127.0.0.1", "0.0.0.0"}
            for x in bindings
        ):
            raise refusal_type("native_gateway_published_port_mismatch")
    api_networks = api["NetworkSettings"]["Networks"]
    ui_networks = ui["NetworkSettings"]["Networks"]
    addresses = {
        api_networks[name].get("IPAddress")
        for name in api_networks.keys() & ui_networks.keys()
        if "api" in (api_networks[name].get("Aliases") or [])
    } - {None, ""}
    if not resolved or set(resolved) != addresses:
        raise refusal_type("native_gateway_resolves_another_backend")
