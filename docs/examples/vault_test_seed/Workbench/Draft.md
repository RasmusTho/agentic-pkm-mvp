---
uuid: 10000000-0000-0000-0000-000000000004
title: Draft Note for Promotion
review_state: inbox
---

This is a draft note in the Workbench, ready for promotion.

It tests the promotion pipeline and panel agent behavior.

## Content

Some test content that will be embedded and indexed.

## Test Characteristics

- Located in Workbench (inbox-like location)
- Has review_state: inbox
- Target for promotion tests
- Should move to 2_Cards/ when promoted
- Tests panel.intent.* → promote.* event chain

## Panel Configuration

Note can be promoted via panel UI or CLI:
- Desired state: promoted
- Target directory: 2_Cards/
- Triggers promote.intent events
