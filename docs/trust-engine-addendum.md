# Trust Engine+ — addendum to EV-Platform-PRD-Tech-Spec.docx

The PRD's wedge (§7) is a per-connector reliability score and guaranteed-charge
insurance, buildable from data the platform already collects (MeterValues,
StatusNotification history). This addendum specifies exactly how that was
implemented for the Phase 1 driver-app build, plus one addition beyond the
original PRD scope: crowdsourced fault verification ("Plug Watch").

## 1. Reliability score

`backend/app/services/reliability.py`

A connector's score is a time-decayed weighted average of its last 20
sessions that ended in `completed` (100) or `failed` (0) — `stopped_remotely`
(user-initiated stop) is excluded entirely, since the connector worked fine
and the driver just chose to end early. Weight decays by half every 5
sessions, so a connector's most recent behavior dominates its score without
one old failure permanently capping it.

```
weight(i) = 0.5 ^ (i / 5)          # i = 0 is the most recent session
score = Σ(outcome_i * weight_i) / Σ(weight_i)
```

Any unresolved Plug Watch report (§3) in the last 2 hours subtracts 15 points
per report, floored at 0. A connector with no session history yet defaults
to 100 (optimistic until proven otherwise).

## 2. The Guaranteed badge

`guaranteed = (score >= 90) AND (no unresolved Plug Watch reports)`

This is the flag shown to drivers before they start a session, and it is
**snapshotted onto the session row at creation time** (`sessions.guaranteed_at_start`).
The badge can drift after a session starts (another driver's report, a
concurrent failure elsewhere) without retroactively changing what was
promised at the moment this driver committed to charging here.

## 3. Guaranteed-charge insurance

`backend/app/services/insurance.py`

If a session with `guaranteed_at_start = true` ends in a station-caused
`failed` status, a claim and a matching wallet credit are inserted
**synchronously, in the same transaction that closes the session** — no
manual claim form, no support ticket. The driver sees the credit the moment
the failure is reported back over the session WebSocket.

A user-initiated stop (`stopped_remotely`) never triggers a claim — the
guarantee is about the station not failing you, not about a full refund on
demand.

## 4. Plug Watch — crowdsourced fault verification (new, beyond the PRD)

`backend/app/routers/trust.py` + `reliability.handle_new_report`

OCPP's StatusNotification is the platform's only signal of connector health
in the base spec — if a charger's firmware silently misreports its own state
(a real, common failure mode with field hardware), the app just believes it.
Plug Watch adds a second, independent signal: drivers can flag a connector
(`wont_charge`, `damaged`, `blocked`, `wrong_status`, `other`) from the app.

If **2 or more** reports land within a **2-hour window** while the connector's
OCPP-reported status still says `available` or `occupied` (i.e., hardware
telemetry disagrees with multiple independent drivers), the backend:

1. force-overrides the connector to `faulted`,
2. opens a `maintenance_tickets` row referencing the report count as the reason,
3. recomputes the reliability score (which drops it below the Guaranteed
   threshold immediately, per §1-2).

This is the platform's actual differentiation claim: trust isn't purely
hardware-attested, it's cross-checked against the people standing at the
charger.

## 5. New API surface beyond docs/api-spec.yaml

These endpoints extend the OpenAPI contract; a production build should fold
them into api-spec.yaml proper.

| Endpoint | Purpose |
|---|---|
| `GET /v1/connectors/{id}/reliability` | Score, guaranteed flag, status, open reports |
| `POST /v1/connectors/{id}/reports` | Submit a Plug Watch report |
| `GET /v1/users/me/credits` | Wallet balance + credit history |
| `GET /v1/sessions/{id}/claim` | Insurance claim for a session (404 if none) |
| `GET /v1/users/me/vehicles` | Driver's vehicles (needed to start a session) |
| `POST /v1/auth/register`, `POST /v1/auth/login`, `GET /v1/users/me` | Minimal auth — the PRD's OAuth2/OIDC (Auth0/Keycloak) is the production target; this is a stdlib PBKDF2 + HMAC-token stand-in for the driver-only scope of this build |

## 6. What's simulated vs. real in this build

There is no physical charger or OCPP Central System available in this
environment. `backend/app/services/ocpp_sim.py` plays that role: it emits
StatusNotification/MeterValues-equivalent events over the session WebSocket,
and one seeded connector is deliberately unreliable so the score/insurance/
Plug Watch behavior is observable rather than theoretical. Swapping this for
a real Central System (SteVe or custom, per PRD §3.1) changes nothing about
the reliability/insurance/Plug Watch logic above — they consume session and
report rows, not the simulator directly.
