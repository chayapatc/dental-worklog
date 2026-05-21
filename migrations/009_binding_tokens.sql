-- LINE binding tokens: temporary tokens for LIFF → system browser OAuth flow
-- Token-based binding avoids Google's disallowed_useragent restriction in LINE in-app browser
-- Tokens expire after 10 minutes

CREATE TABLE IF NOT EXISTS line_binding_tokens (
    token TEXT PRIMARY KEY,
    line_user_id TEXT NOT NULL,
    line_display_name TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now','localtime')),
    expires_at TEXT NOT NULL
);
