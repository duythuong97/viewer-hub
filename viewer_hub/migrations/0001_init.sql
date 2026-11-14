-- hub.db v1: registry of packs, CSV datasets, docs sites, settings.
CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE packs (
  id          TEXT NOT NULL,
  version     TEXT NOT NULL,
  title       TEXT NOT NULL,
  format      INTEGER NOT NULL,
  components  TEXT NOT NULL,          -- JSON copy of pack.json "components"
  imported_at TEXT NOT NULL,
  active      INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (id, version)
);

CREATE TABLE datasets (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  origin        TEXT NOT NULL,        -- 'workspace' | 'pack:<pack_id>'
  schema        INTEGER NOT NULL,
  rows          INTEGER NOT NULL DEFAULT 0,
  needs_rebuild INTEGER NOT NULL DEFAULT 0,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE sites (
  id            TEXT PRIMARY KEY,
  title         TEXT NOT NULL,
  origin        TEXT NOT NULL,
  schema        INTEGER NOT NULL,
  pages         INTEGER NOT NULL DEFAULT 0,
  needs_rebuild INTEGER NOT NULL DEFAULT 1,
  build_error   TEXT,
  built_at      TEXT,
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
