# Overlay Grammar

## Why grammar
Overlay behavior needs a shared contract so interaction remains predictable across modes.

## Overlay classes
- Margin rail: conversation context and composer.
- Session drawer: session switching and history.
- Bottom sheet: portrait/mobile rail equivalent.
- Source peek: anchored provenance/context card.
- Proposal card/block pair: same staged object shown in thread + document.

## Structural rules
- Overlays augment the current document context; they do not replace it.
- Overlays should be dismissible without data loss or navigation reset.
- Trigger and dismiss actions should be explicit and reversible.
- If an overlay is unavailable (viewport/runtime limits), fallback must keep the same cognitive semantics.

## Consistency rule
Any proposal object shown in chat must map to the same object in document context with identical status and actions.
