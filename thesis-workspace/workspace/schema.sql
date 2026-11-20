CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY,
    space TEXT NOT NULL,
    email TEXT NOT NULL,
    name TEXT NOT NULL,
    UNIQUE(space, email)
);
CREATE TABLE IF NOT EXISTS theses (
    id INTEGER PRIMARY KEY,
    space TEXT NOT NULL,
    owner_id INTEGER NOT NULL REFERENCES people(id),
    title TEXT NOT NULL,
    argument TEXT NOT NULL,
    questions TEXT NOT NULL,
    competing TEXT NOT NULL,
    topics TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('Exploring', 'Developing', 'Active', 'Archived')),
    visibility TEXT NOT NULL CHECK(visibility IN ('draft', 'team')),
    reviewed TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS theses_by_space ON theses(space, visibility, owner_id);
CREATE TABLE IF NOT EXISTS versions (
    thesis_id INTEGER NOT NULL REFERENCES theses(id),
    revision INTEGER NOT NULL,
    changed TEXT NOT NULL,
    visibility TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    token TEXT NOT NULL,
    PRIMARY KEY(thesis_id, revision)
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY,
    thesis_id INTEGER REFERENCES theses(id),
    added_by INTEGER NOT NULL REFERENCES people(id),
    added TEXT NOT NULL,
    title TEXT NOT NULL,
    author TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility = 'draft' OR (visibility = 'team' AND thesis_id IS NOT NULL)),
    kind TEXT NOT NULL CHECK(kind IN ('text', 'link', 'file')),
    url TEXT NOT NULL,
    filename TEXT NOT NULL,
    file_bytes BLOB,
    passage_data TEXT NOT NULL,
    deleted INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS sources_by_thesis ON sources(thesis_id, visibility, added_by);
CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY,
    thesis_id INTEGER NOT NULL REFERENCES theses(id),
    person_id INTEGER NOT NULL REFERENCES people(id),
    body TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS comments_by_thesis ON comments(thesis_id);
CREATE TABLE IF NOT EXISTS login_tokens (
    token_hash TEXT PRIMARY KEY,
    email TEXT NOT NULL,
    created INTEGER NOT NULL,
    expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS login_by_email ON login_tokens(email, created);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    person_id INTEGER NOT NULL REFERENCES people(id),
    expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_by_expiry ON sessions(expires);
CREATE TABLE IF NOT EXISTS ask_results (
    id TEXT PRIMARY KEY,
    session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
    expires INTEGER NOT NULL,
    question TEXT NOT NULL,
    result TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ask_results_by_expiry ON ask_results(expires);
