"""Fixed disposable native web API composition in the interaction layer.

The real API process supplies its own queue and normal capture formatter to
lower-layer fixture/observation code before serving the unchanged Product app.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from app.ops.native_web_acceptance import EFFECT_LIMITS, NativeWebRefusal, verify_resources
from app.ops.native_web_daily import DailyBriefingState
from app.ops.native_web_fixture import bootstrap_fixture, fixture_readback, prepare_daily_sources
from app.ops.native_web_runtime import AcknowledgedFixtureState, DailySourceFault, _asset_readback


def create_native_web_app(manifest: dict[str, Any]) -> Any:
    # Source initialization and queue production occur here, in the process
    # which will actually serve app.main:app, before its normal lifespan.
    verify_resources(manifest)
    _asset_readback(manifest)
    vault = Path('/scratch/vault')
    from app.api.routes import companion
    fixture = bootstrap_fixture(vault, manifest['resource_generation'],
                                review_queue=companion._MEMORY_CANDIDATE_REVIEW_QUEUE)
    fixture['daily'] = prepare_daily_sources(fixture, manifest['resource_tree'])
    from app.main import app
    baseline = fixture_readback(vault, fixture)
    baseline.pop('mutable_readback')
    effects = {pilot: dict.fromkeys(limits, 0) for pilot, limits in EFFECT_LIMITS.items()}
    from app.api.routes.capture import _compose_entry
    acknowledged = AcknowledgedFixtureState(vault, fixture, effects, capture_entry=_compose_entry)
    daily_briefing = DailyBriefingState(vault, effects)
    daily_fault = DailySourceFault(vault, fixture['daily'], effects, acknowledged, daily_briefing)

    @app.middleware('http')
    async def observe_guarded_acknowledgement(request: Any, call_next: Any) -> Any:
        admitted = None
        daily_admitted = None
        if request.method == 'POST' and request.url.path == '/api/companion/briefing/first-contact':
            daily_fault.require_current()
            daily_admitted = daily_briefing.begin_contact(await request.json())
        if request.method == 'POST' and request.url.path in {'/api/panel/confirm', '/api/companion/capture'}:
            admitted = acknowledged.begin_request(request.url.path, await request.json())
        response = await call_next(request)
        if admitted is None and daily_admitted is None or response.status_code != 200:
            return response
        from starlette.responses import Response
        chunks = [chunk async for chunk in response.body_iterator]
        raw = b''.join(chunks)
        if len(raw) > 1024 * 1024:
            raise NativeWebRefusal('normal_acknowledgement_over_budget')
        if daily_admitted is not None:
            daily_fault.require_sources()
            daily_briefing.observe_contact(json.loads(raw), daily_admitted)
        else:
            acknowledged.observe(request.url.path, json.loads(raw), admitted)
        # Forward the exact Product bytes/status/headers/background unchanged;
        # this observer neither creates a receipt nor fabricates an ack.
        return Response(raw, status_code=response.status_code, headers=dict(response.headers), background=response.background)

    def readback() -> dict[str, Any]:
        from app.tts.config import load_tts_config
        from app.tts.providers import resolve_voice
        tts = load_tts_config()
        voices = [resolve_voice(tts, language) for language in ('sv-SE', 'en-US')]
        if (not tts.enabled or not tts.local_only or tts.allow_browser_fallback or tts.allow_cloud_fallback
            or any(not voice.available for voice in voices)
            or [(voice.provider, voice.voice_id) for voice in voices] != [('piper', 'sv_SE-lisa-medium'), ('kokoro', 'bf_isabella')]):
            raise NativeWebRefusal('selected_real_local_tts_unavailable')
        verify_resources(manifest)
        current = fixture_readback(vault, fixture)
        mutable = current.pop('mutable_readback')
        acknowledged.require_current(mutable)
        daily_fault.require_current()
        module_path = sys.modules['app.main'].__file__
        if not isinstance(module_path, str):
            raise NativeWebRefusal('actual_api_module_unknown')
        return {
            'source_sha': manifest['source_sha'], 'image_digest': manifest['image_digest'],
            'app_image_id': manifest['app_image_id'], 'resource_tree': manifest['resource_tree'],
            'resource_generation': manifest['resource_generation'], 'api_pid': os.getpid(),
            'api_module': str(Path(module_path).resolve()),
            'fixture': current, **_asset_readback(manifest),
            'selected_tts': [(voice.provider, voice.language, voice.voice_id) for voice in voices],
        }

    @app.get('/__native_web_identity', include_in_schema=False)
    def native_identity(pilot: str | None = None, effect: str | None = None) -> dict[str, Any]:
        from fastapi import HTTPException
        observed = readback()
        if observed['fixture'] != baseline:
            raise HTTPException(409, 'synthetic fixture identity drift')
        if pilot is not None or effect is not None:
            if pilot not in effects or effect not in effects[pilot]:
                raise HTTPException(409, 'unknown fixed effect')
            if effects[pilot][effect] >= EFFECT_LIMITS[pilot][effect]:
                raise HTTPException(409, 'fixed browser effect budget exhausted')
            effects[pilot][effect] += 1
            if pilot == 'deep-review':
                acknowledged.grant(effect)
            else:
                daily_briefing.grant(effect)
                daily_fault.grant(effect)
        return {'identity': observed, 'effects': effects, 'acknowledgements': acknowledged.acknowledgements,
                'mutable_versions': acknowledged.versions, 'daily_source_versions': daily_fault.expected_versions(),
                'daily_source_acknowledgements': daily_fault.acknowledgements,
                'daily_source_transition': daily_fault.transition(), 'daily_briefing_state': daily_briefing.snapshot()}

    @app.post('/__native_web_fixture/scheduled-replay', include_in_schema=False)
    def fixed_scheduled_replay() -> dict[str, Any]:
        daily_fault.require_current()
        return daily_briefing.scheduled_replay()

    @app.post('/__native_web_fixture/degrade-source', include_in_schema=False)
    def degrade_source() -> dict[str, Any]:
        return daily_fault.write(False)

    @app.post('/__native_web_fixture/restore-source', include_in_schema=False)
    def restore_source() -> dict[str, Any]:
        return daily_fault.write(True)

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--api-process', action='store_true', required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args(argv)
    import uvicorn
    uvicorn.run(create_native_web_app(json.loads(args.manifest.read_text())), host='127.0.0.1', port=8000, log_level='warning')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
