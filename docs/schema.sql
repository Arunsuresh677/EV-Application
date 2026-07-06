-- EV Charging Platform — Core Data Model
-- PostgreSQL 15+. Redis is used alongside this for live station/connector
-- status and session telemetry caching (not modeled here — ephemeral by design).

CREATE TYPE user_role AS ENUM ('driver', 'fleet_driver', 'fleet_manager', 'station_admin', 'support', 'super_admin');
CREATE TYPE station_status AS ENUM ('online', 'offline', 'maintenance');
CREATE TYPE connector_type AS ENUM ('CCS2', 'CHAdeMO', 'TYPE2', 'NACS');
CREATE TYPE connector_status AS ENUM ('available', 'occupied', 'faulted', 'reserved');
CREATE TYPE session_status AS ENUM ('pending', 'active', 'completed', 'failed', 'stopped_remotely');
CREATE TYPE pricing_model AS ENUM ('per_kwh', 'per_minute', 'flat');
CREATE TYPE reservation_status AS ENUM ('pending', 'active', 'expired', 'cancelled', 'fulfilled');
CREATE TYPE payment_status AS ENUM ('pending', 'captured', 'failed', 'refunded');
CREATE TYPE ticket_status AS ENUM ('open', 'in_progress', 'resolved', 'closed');

CREATE TABLE operators (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name    TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE fleets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    company_name    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            TEXT NOT NULL,
    email           TEXT UNIQUE NOT NULL,
    phone           TEXT,
    role            user_role NOT NULL DEFAULT 'driver',
    rfid_card_id    TEXT UNIQUE,
    fleet_id        UUID REFERENCES fleets(id),
    operator_id     UUID REFERENCES operators(id),  -- set for station_admin/support roles
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_users_fleet ON users(fleet_id);
CREATE INDEX idx_users_operator ON users(operator_id);

CREATE TABLE payment_methods (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    psp_token       TEXT NOT NULL,        -- PSP-hosted token; no raw card data ever stored here
    brand           TEXT,
    last4           TEXT,
    is_default      BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE vehicles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID REFERENCES users(id),        -- nullable if fleet-owned
    fleet_id            UUID REFERENCES fleets(id),
    make                TEXT NOT NULL,
    model               TEXT NOT NULL,
    connector_type      connector_type NOT NULL,
    battery_capacity_kwh NUMERIC(6,2) NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (user_id IS NOT NULL OR fleet_id IS NOT NULL)
);

CREATE TABLE stations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id     UUID NOT NULL REFERENCES operators(id),
    name            TEXT NOT NULL,
    address         TEXT NOT NULL,
    lat             DOUBLE PRECISION NOT NULL,
    lng             DOUBLE PRECISION NOT NULL,
    status          station_status NOT NULL DEFAULT 'offline',
    ocpp_charge_point_id TEXT UNIQUE NOT NULL,   -- the identity a physical charger authenticates as
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_stations_operator ON stations(operator_id);
CREATE INDEX idx_stations_geo ON stations(lat, lng);

CREATE TABLE connectors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id      UUID NOT NULL REFERENCES stations(id) ON DELETE CASCADE,
    ocpp_connector_id INT NOT NULL,     -- the numeric connectorId OCPP messages reference
    type            connector_type NOT NULL,
    power_kw        NUMERIC(6,2) NOT NULL,
    status          connector_status NOT NULL DEFAULT 'available',
    reliability_score NUMERIC(4,1),     -- 0-100, derived from session success history — the "wedge" feature
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(station_id, ocpp_connector_id)
);
CREATE INDEX idx_connectors_station ON connectors(station_id);
CREATE INDEX idx_connectors_status ON connectors(status);

CREATE TABLE tariffs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    operator_id         UUID NOT NULL REFERENCES operators(id),
    pricing_model       pricing_model NOT NULL,
    rate                NUMERIC(8,4) NOT NULL,
    time_of_day_rules   JSONB,          -- e.g. [{"start":"22:00","end":"06:00","multiplier":0.7}]
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE reservations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id),
    connector_id    UUID NOT NULL REFERENCES connectors(id),
    start_time      TIMESTAMPTZ NOT NULL,
    expiry_time     TIMESTAMPTZ NOT NULL,
    status          reservation_status NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_reservations_connector ON reservations(connector_id, status);

CREATE TABLE sessions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES users(id),
    connector_id        UUID NOT NULL REFERENCES connectors(id),
    vehicle_id          UUID REFERENCES vehicles(id),
    reservation_id      UUID REFERENCES reservations(id),
    idempotency_key     TEXT UNIQUE NOT NULL,   -- prevents double-start on retried taps
    ocpp_transaction_id BIGINT,                 -- id returned by the charger's StartTransaction.conf
    start_time          TIMESTAMPTZ,
    end_time            TIMESTAMPTZ,
    energy_kwh          NUMERIC(8,3),
    cost                NUMERIC(10,2),
    status              session_status NOT NULL DEFAULT 'pending',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_sessions_user ON sessions(user_id, created_at DESC);
CREATE INDEX idx_sessions_connector ON sessions(connector_id);
CREATE INDEX idx_sessions_status ON sessions(status);

-- Raw MeterValues stream — source of truth for billing reconciliation if the
-- WebSocket drops mid-session. Never derive final cost from live state alone.
CREATE TABLE meter_values (
    id              BIGSERIAL PRIMARY KEY,
    session_id      UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    reading_kwh     NUMERIC(10,3) NOT NULL,
    power_kw        NUMERIC(6,2),
    recorded_at     TIMESTAMPTZ NOT NULL
);
CREATE INDEX idx_meter_values_session ON meter_values(session_id, recorded_at);

CREATE TABLE payments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES sessions(id),
    payment_method_id UUID REFERENCES payment_methods(id),
    amount          NUMERIC(10,2) NOT NULL,
    status          payment_status NOT NULL DEFAULT 'pending',
    psp_reference   TEXT,               -- PSP's own charge/invoice id, for reconciliation
    invoice_id      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_payments_session ON payments(session_id);

CREATE TABLE fleet_vehicles (
    fleet_id        UUID NOT NULL REFERENCES fleets(id),
    vehicle_id      UUID NOT NULL REFERENCES vehicles(id),
    charge_cap_pct  SMALLINT DEFAULT 100,
    PRIMARY KEY (fleet_id, vehicle_id)
);

CREATE TABLE fleet_drivers (
    fleet_id        UUID NOT NULL REFERENCES fleets(id),
    user_id         UUID NOT NULL REFERENCES users(id),
    vehicle_id      UUID REFERENCES vehicles(id),   -- assigned vehicle, if any
    PRIMARY KEY (fleet_id, user_id)
);

CREATE TABLE maintenance_tickets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    station_id      UUID NOT NULL REFERENCES stations(id),
    connector_id    UUID REFERENCES connectors(id),
    issue           TEXT NOT NULL,
    status          ticket_status NOT NULL DEFAULT 'open',
    assigned_to     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at     TIMESTAMPTZ
);
CREATE INDEX idx_tickets_status ON maintenance_tickets(status);
CREATE INDEX idx_tickets_station ON maintenance_tickets(station_id);
