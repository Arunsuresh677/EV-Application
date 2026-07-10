-- EV Charging Platform — SQLite dev/demo schema.
-- Translated from docs/schema.sql (PostgreSQL, production reference — keep that as the
-- source of truth for column intent). Differences here are purely dialect:
--   UUID -> TEXT (app generates uuid4 hex), ENUM -> TEXT + CHECK, BOOLEAN -> INTEGER (0/1),
--   TIMESTAMPTZ -> TEXT (ISO-8601 UTC), JSONB -> TEXT (json-encoded), BIGSERIAL -> INTEGER PK.
-- Three tables at the end (plugwatch_reports, insurance_claims, user_credits) are new,
-- added for the Trust Engine+ feature and have no PostgreSQL counterpart yet.

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS operators (
    id              TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS fleets (
    id              TEXT PRIMARY KEY,
    company_name    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS users (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    password_salt   TEXT NOT NULL,
    phone           TEXT,
    role            TEXT NOT NULL DEFAULT 'driver'
                    CHECK (role IN ('driver','fleet_driver','fleet_manager','station_admin','support','super_admin')),
    rfid_card_id    TEXT UNIQUE,
    fleet_id        TEXT REFERENCES fleets(id),
    operator_id     TEXT REFERENCES operators(id),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_users_fleet ON users(fleet_id);
CREATE INDEX IF NOT EXISTS idx_users_operator ON users(operator_id);

CREATE TABLE IF NOT EXISTS payment_methods (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    psp_token       TEXT NOT NULL,
    brand           TEXT,
    last4           TEXT,
    is_default      INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS vehicles (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT REFERENCES users(id),
    fleet_id            TEXT REFERENCES fleets(id),
    make                TEXT NOT NULL,
    model               TEXT NOT NULL,
    connector_type      TEXT NOT NULL CHECK (connector_type IN ('CCS2','CHAdeMO','TYPE2','NACS')),
    battery_capacity_kwh REAL NOT NULL,
    created_at          TEXT NOT NULL,
    CHECK (user_id IS NOT NULL OR fleet_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS stations (
    id              TEXT PRIMARY KEY,
    operator_id     TEXT NOT NULL REFERENCES operators(id),
    name            TEXT NOT NULL,
    address         TEXT NOT NULL,
    lat             REAL NOT NULL,
    lng             REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'offline' CHECK (status IN ('online','offline','maintenance')),
    ocpp_charge_point_id TEXT UNIQUE NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_stations_operator ON stations(operator_id);
CREATE INDEX IF NOT EXISTS idx_stations_geo ON stations(lat, lng);

CREATE TABLE IF NOT EXISTS connectors (
    id              TEXT PRIMARY KEY,
    station_id      TEXT NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    ocpp_connector_id INTEGER NOT NULL,
    type            TEXT NOT NULL CHECK (type IN ('CCS2','CHAdeMO','TYPE2','NACS')),
    power_kw        REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'available'
                    CHECK (status IN ('available','occupied','faulted','reserved','maintenance')),
    -- 'faulted' = system/Plug-Watch auto-detected problem; 'maintenance' =
    -- operator manually took it offline. Driver-facing UI shows both under
    -- one label ("Under maintenance"); the operator dashboard keeps the
    -- distinction since it's operationally meaningful to them.
    reliability_score REAL NOT NULL DEFAULT 100,
    guaranteed      INTEGER NOT NULL DEFAULT 0,
    updated_at      TEXT NOT NULL,
    UNIQUE(station_id, ocpp_connector_id)
);
CREATE INDEX IF NOT EXISTS idx_connectors_station ON connectors(station_id);
CREATE INDEX IF NOT EXISTS idx_connectors_status ON connectors(status);

CREATE TABLE IF NOT EXISTS tariffs (
    id                  TEXT PRIMARY KEY,
    operator_id         TEXT NOT NULL REFERENCES operators(id),
    pricing_model       TEXT NOT NULL CHECK (pricing_model IN ('per_kwh','per_minute','flat')),
    rate                REAL NOT NULL,
    time_of_day_rules   TEXT,
    created_at          TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reservations (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    connector_id    TEXT NOT NULL REFERENCES connectors(id),
    start_time      TEXT NOT NULL,
    expiry_time     TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','active','expired','cancelled','fulfilled')),
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reservations_connector ON reservations(connector_id, status);

CREATE TABLE IF NOT EXISTS sessions (
    id                  TEXT PRIMARY KEY,
    user_id             TEXT NOT NULL REFERENCES users(id),
    connector_id        TEXT NOT NULL REFERENCES connectors(id),
    vehicle_id          TEXT REFERENCES vehicles(id),
    reservation_id      TEXT REFERENCES reservations(id),
    idempotency_key     TEXT UNIQUE NOT NULL,
    ocpp_transaction_id INTEGER,
    guaranteed_at_start INTEGER NOT NULL DEFAULT 0,
    start_time          TEXT,
    end_time            TEXT,
    energy_kwh          REAL,
    cost                REAL,
    status              TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','active','completed','failed','stopped_remotely')),
    fail_reason         TEXT,
    created_at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_connector ON sessions(connector_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status);

CREATE TABLE IF NOT EXISTS meter_values (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    reading_kwh     REAL NOT NULL,
    power_kw        REAL,
    recorded_at     TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_meter_values_session ON meter_values(session_id, recorded_at);

CREATE TABLE IF NOT EXISTS payments (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    payment_method_id TEXT REFERENCES payment_methods(id),
    amount          REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','captured','failed','refunded')),
    psp_reference   TEXT,
    invoice_id      TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_payments_session ON payments(session_id);

CREATE TABLE IF NOT EXISTS fleet_vehicles (
    fleet_id        TEXT NOT NULL REFERENCES fleets(id),
    vehicle_id      TEXT NOT NULL REFERENCES vehicles(id),
    charge_cap_pct  INTEGER DEFAULT 100,
    PRIMARY KEY (fleet_id, vehicle_id)
);

CREATE TABLE IF NOT EXISTS fleet_drivers (
    fleet_id        TEXT NOT NULL REFERENCES fleets(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    vehicle_id      TEXT REFERENCES vehicles(id),
    PRIMARY KEY (fleet_id, user_id)
);

CREATE TABLE IF NOT EXISTS maintenance_tickets (
    id              TEXT PRIMARY KEY,
    station_id      TEXT NOT NULL REFERENCES stations(id),
    connector_id    TEXT REFERENCES connectors(id),
    issue           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','in_progress','resolved','closed')),
    assigned_to     TEXT REFERENCES users(id),
    created_at      TEXT NOT NULL,
    resolved_at     TEXT
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON maintenance_tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_station ON maintenance_tickets(station_id);

-- ---------------------------------------------------------------------------
-- Trust Engine+ additions (no PostgreSQL counterpart in docs/schema.sql yet)
-- ---------------------------------------------------------------------------

-- Crowdsourced fault reports ("Plug Watch"). Two independent reports on a
-- connector the OCPP feed still calls available/occupied, within the report
-- window used by services/reliability.py, force-flip the connector to
-- faulted and open a maintenance ticket — catching failures pure hardware
-- telemetry missed.
CREATE TABLE IF NOT EXISTS plugwatch_reports (
    id              TEXT PRIMARY KEY,
    connector_id    TEXT NOT NULL REFERENCES connectors(id) ON DELETE CASCADE,
    reporter_id     TEXT NOT NULL REFERENCES users(id),
    issue_type      TEXT NOT NULL CHECK (issue_type IN ('wont_charge','damaged','blocked','wrong_status','other')),
    note            TEXT,
    resolved        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plugwatch_connector ON plugwatch_reports(connector_id, created_at);

-- Automatic guaranteed-charge insurance payouts. A session's guaranteed_at_start
-- flag is snapshotted when the session is created; if that session later fails
-- for a station-caused reason, services/insurance.py inserts a claim + a
-- matching user_credits row in the same transaction that closes the session —
-- no manual claim filing.
CREATE TABLE IF NOT EXISTS insurance_claims (
    id              TEXT PRIMARY KEY,
    session_id      TEXT NOT NULL REFERENCES sessions(id),
    connector_id    TEXT NOT NULL REFERENCES connectors(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    reason          TEXT NOT NULL,
    credit_amount   REAL NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_claims_user ON insurance_claims(user_id);

-- Driver wallet ledger. Positive amounts are credits (insurance payouts,
-- goodwill); a real production system would also record debits when credit
-- is applied to a payment, which is out of scope for this pass.
CREATE TABLE IF NOT EXISTS user_credits (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL REFERENCES users(id),
    amount          REAL NOT NULL,
    reason          TEXT NOT NULL,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_credits_user ON user_credits(user_id);

-- ---------------------------------------------------------------------------
-- Operator billing — the SaaS fee VoltPath charges the charging networks
-- that use the platform. Distinct from `payments` (a driver paying for a
-- charging session) and `tariffs` (an operator pricing their own sessions).
-- No PostgreSQL counterpart in docs/schema.sql yet.
-- ---------------------------------------------------------------------------

-- Static plan catalog, seeded here (not in seed.py) since it's platform
-- config rather than demo data — every environment, including tests, should
-- have the same three plans available.
CREATE TABLE IF NOT EXISTS subscription_plans (
    id                      TEXT PRIMARY KEY,
    name                    TEXT NOT NULL,
    monthly_fee             REAL NOT NULL,
    max_stations            INTEGER,     -- NULL = unlimited
    platform_fee_percent    REAL NOT NULL,
    sort_order              INTEGER NOT NULL
);
INSERT OR IGNORE INTO subscription_plans (id, name, monthly_fee, max_stations, platform_fee_percent, sort_order) VALUES
    ('starter', 'Starter', 0, 2, 0.03, 1),
    ('growth', 'Growth', 4999, 10, 0.015, 2),
    ('enterprise', 'Enterprise', 19999, NULL, 0.005, 3);

CREATE TABLE IF NOT EXISTS operator_subscriptions (
    operator_id     TEXT PRIMARY KEY REFERENCES operators(id),
    plan_id         TEXT NOT NULL REFERENCES subscription_plans(id),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','past_due','cancelled')),
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- One row per operator per calendar-month billing period. Created lazily
-- (services/billing.py) the first time that period's billing data is read,
-- not on a schedule — same reasoning as reservation expiry.
CREATE TABLE IF NOT EXISTS invoices (
    id              TEXT PRIMARY KEY,
    operator_id     TEXT NOT NULL REFERENCES operators(id),
    period_start    TEXT NOT NULL,
    period_end      TEXT NOT NULL,
    base_fee        REAL NOT NULL,
    usage_fee       REAL NOT NULL,
    total           REAL NOT NULL,
    status          TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','paid','overdue')),
    created_at      TEXT NOT NULL,
    paid_at         TEXT,
    UNIQUE(operator_id, period_start)
);
CREATE INDEX IF NOT EXISTS idx_invoices_operator ON invoices(operator_id, period_start DESC);
