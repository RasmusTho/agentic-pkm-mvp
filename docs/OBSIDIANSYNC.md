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
