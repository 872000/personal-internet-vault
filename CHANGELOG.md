# Changelog

## 2026-10-01 — Personal Internet Vault

Evolved from MyTube Sync into a Personal Internet Vault spanning YouTube,
Reddit, GitHub, Spotify and browser history.

### Added
- `vault/schema.py` — unified `SavedItem` schema
  (`service`, `kind`, `title`, `url`, `saved_at`, `tags`, `metadata` JSON)
  with URL normalization for cross-service dedupe (tracking params stripped).
- `vault/store.py` — `VaultStore`: local SQLite vault with FTS5 full-text
  search over title/URL/tags, dedupe by normalized URL, JSON export/import,
  per-service stats.
- `vault/importers.py` — normalizers for each service's native export format:
  YouTube Takeout subscriptions CSV + watch history JSON, Reddit GDPR
  saved-posts JSON, GitHub starred-repos JSON, Spotify "My Data" library JSON,
  Chromium History SQLite and Bookmarks JSON. Defensive per-row parsing —
  bad rows are skipped, never fatal.
- `vault/cli.py` — tiny CLI: `init`, `import`, `search`, `list`, `stats`,
  `export`. Example: `python3 -m vault.cli search "lofi mix"`.
- README: new "Personal Internet Vault" section documenting the vault
  package and quick-start commands.

### Preserved
- Original MyTube Sync FastAPI backend, Firefox extension, frontend and
  `mytube-import.py` are unchanged.
