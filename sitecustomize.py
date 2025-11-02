import importlib
try:
    mod = importlib.import_module('app.agents.classifier')
    if hasattr(mod, 'classify_run') and not getattr(mod, '_persist_hooked', False):
        _orig = mod.classify_run
        def _wrap(object_id, trace_id=None):
            res = _orig(object_id, trace_id=trace_id)
            try:
                value = res.get('classification') if isinstance(res, dict) else res
            except Exception:
                value = res
            try:
                from app.stores.decisions import put_decision
                put_decision(
                    object_id=object_id,
                    agent='classifier',
                    kind='classify',
                    key='classification',
                    value=value
                )
            except Exception:
                pass
            return {'classification': value}
        mod.classify_run = _wrap
        mod._persist_hooked = True
except Exception:
    pass
