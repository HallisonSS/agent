-- Schema permanente do AGENT. Idempotente: roda no 1º start do Postgres
-- (docker-entrypoint-initdb.d) e também é reaplicado pelo agent-api no boot.

-- ===== Memória permanente (longo prazo) =====
CREATE TABLE IF NOT EXISTS memories (
    id          BIGSERIAL PRIMARY KEY,
    kind        TEXT        NOT NULL DEFAULT 'note'
                CHECK (kind IN ('note','fact','incident','decision','preference','chat_summary')),
    title       TEXT,
    content     TEXT        NOT NULL,
    tags        TEXT[]      NOT NULL DEFAULT '{}',
    source      TEXT        NOT NULL DEFAULT 'api',
    importance  SMALLINT    NOT NULL DEFAULT 3 CHECK (importance BETWEEN 1 AND 5),
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    tsv         tsvector GENERATED ALWAYS AS (
                    to_tsvector('portuguese', coalesce(title,'') || ' ' || content)
                ) STORED
);
CREATE INDEX IF NOT EXISTS idx_memories_tsv  ON memories USING GIN (tsv);
CREATE INDEX IF NOT EXISTS idx_memories_tags ON memories USING GIN (tags);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories (kind, created_at DESC);

-- ===== Decisões do worker (regra ou LLM) =====
CREATE TABLE IF NOT EXISTS decisions (
    id                BIGSERIAL PRIMARY KEY,
    fingerprint       TEXT,
    alertname         TEXT,
    severity          TEXT,
    summary           TEXT,
    action            TEXT        NOT NULL,
    params            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    requires_approval BOOLEAN     NOT NULL DEFAULT FALSE,
    source            TEXT        NOT NULL DEFAULT 'policy',   -- policy | llm | fallback
    llm_provider      TEXT,
    llm_model         TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_decisions_alertname ON decisions (alertname, created_at DESC);

-- ===== Aprovações humanas (RBAC) =====
CREATE TABLE IF NOT EXISTS approvals (
    id           BIGSERIAL PRIMARY KEY,
    requested_by TEXT        NOT NULL DEFAULT 'api',
    action       TEXT        NOT NULL,
    params       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    reason       TEXT,
    decision_id  BIGINT REFERENCES decisions(id) ON DELETE SET NULL,
    status       TEXT        NOT NULL DEFAULT 'pending'
                 CHECK (status IN ('pending','approved','rejected','executed','failed')),
    decided_by   TEXT,
    decided_at   TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals (status, created_at DESC);

-- ===== Auditoria: entrada, decisão, comando, saída =====
CREATE TABLE IF NOT EXISTS audit_log (
    id         BIGSERIAL PRIMARY KEY,
    ts         TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor      TEXT        NOT NULL,
    event_type TEXT        NOT NULL,
    ref        TEXT,
    payload    JSONB       NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_audit_ts   ON audit_log (ts DESC);
CREATE INDEX IF NOT EXISTS idx_audit_type ON audit_log (event_type, ts DESC);
