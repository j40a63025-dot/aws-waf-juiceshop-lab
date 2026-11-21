CREATE TABLE waf_events (
    event_id UUID PRIMARY KEY,
    occurred_at TIMESTAMPTZ NOT NULL,
    action TEXT NOT NULL CHECK (action IN ('ALLOW', 'BLOCK')),
    rule VARCHAR(64) NOT NULL CHECK (rule ~ '^[A-Za-z][A-Za-z0-9_-]*$')
);
