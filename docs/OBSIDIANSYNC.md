# Obsidian-first sync
## Principer
- Människa först: maskinen ändrar aldrig body, endast frontmatter-nycklar
- UUID = identitet, filnamn = kosmetik
- Git som primär förändringskälla, iCloud som transport
## Plugins
- Required: Obsidian Git, Dataview
- Recommended: Templater/QuickAdd, MetaEdit/Properties++, Advanced URI, Linter
## Flöden
- Obsidian→DB: commit→watcher→/ingest|/update→outbox→indexer
- DB→Obsidian: event→frontmatter write (om inaktiv) annars förslag i /Inbox
## Skrivpolicy
- Aldrig body, inga auto-rename, debounce + hash, rename/move uppdaterar bara path


## Rename-policy
- Fil-rename eller flytt uppdaterar endast `objects.path` samt `file_state.path` via watcher-stödet.
- Ingen re-embedding triggas vid rename/move; indexering körs endast om filens body ändras.

## Settings hot-reload
- Backend laddar `System/Settings/system.md` när mtime ändras och applicerar policies utan omstart.
- Felaktig frontmatter (validerad mot `docs/schema/system-settings.schema.json`) loggas och stoppar inte befintliga policies.

## Filesystem fallback
- `scripts/fs_watcher.py` speglar samma policy som git-watchern och ger offline-idempotens.
- Aktiv fil (detekterad via `settings.policy()`) skrivs inte tillbaka utan triagemeddelande i Inbox med Advanced-URI-länk.

## Advanced-URI UX
- Alla Inbox-poster får `obsidian://advanced-uri`-länkar för snabb navigering till berörd fil.
- Dashboarden `System/Dashboards/*.md` visar senaste händelser via Dataview-tabeller.
