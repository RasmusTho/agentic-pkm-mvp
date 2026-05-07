# Overlay Grammar

## Why grammar
Overlay behavior needs a shared contract so interaction remains predictable across cognitive postures.

## Overlay classes
- Margin rail: conversation context and composer.
- Session drawer: session switching and history.
- Bottom sheet: portrait/mobile rail equivalent.
- Source peek: anchored provenance/context card.
- Proposal card/block pair: same staged object shown in thread and document.
- Recovery strip: lightweight re-entry cues after interruption.

## Structural rules
- Overlays augment the current document context; they do not replace it.
- Overlays should be dismissible without data loss or navigation reset.
- Trigger and dismiss actions should be explicit and reversible.
- If an overlay is unavailable (viewport/runtime limits), fallback must keep the same cognitive semantics.
- Overlay content must never become hidden semantic state.

## Continuity rules
- Any proposal object shown in chat must map to the same object in document context with identical status and actions.
- Resurfaced objects must carry enough provenance for rapid trust evaluation.
- Overlay dismissal must not erase unresolved cognitive tension.

## Related docs
- `COGNITIVE_OBJECTS.md`
- `TEMPORAL_PROVENANCE.md`
- `ATTENTION_MODEL.md`
- `SALIENCE_AND_TENSION.md`
