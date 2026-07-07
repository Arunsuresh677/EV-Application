# VoltPath — EV Charging Platform

A charging platform for drivers, built around one wedge: **trust**. Most
networks show you a pin and a status dot that might be lying to you. VoltPath
adds a live, crowd-verified reliability score per connector and automatically
credits you if a "Guaranteed" connector fails you — no claim form, no support
ticket.

This repo is the actual build, not just the spec: a working backend, a
real driver web app, and extended iOS/Android source. See
[docs/EV-Platform-PRD-Tech-Spec.docx](docs/EV-Platform-PRD-Tech-Spec.docx)
for the full product/technical spec this was built against, and
[docs/trust-engine-addendum.md](docs/trust-engine-addendum.md) for exactly
how the trust wedge is implemented.

## Run it

This machine has Python but not Node/Docker/PostgreSQL, so the backend runs
on FastAPI + SQLite instead of the PRD's target NestJS/Postgres stack — same
REST/WebSocket contract, so swapping the production stack in later doesn't
touch the API surface. No extra packages need installing (fastapi, uvicorn,
pydantic, websockets are already present; everything else — auth, DB access —
uses the Python standard library on purpose, to keep this runnable with zero
setup).

```
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

Open `http://localhost:8000` — that's the driver web app, served by the same
FastAPI process as the API. First run seeds demo data automatically:

- **Driver login:** `driver@demo.dev` / `chargeme123`
- Three demo stations, including one connector deliberately seeded with a low
  score so its sessions fail somewhat often — that's what makes the
  reliability/insurance/Plug Watch behavior demonstrable instead of
  theoretical. See [docs/trust-engine-addendum.md](docs/trust-engine-addendum.md) §6.

Station operators log in separately at `http://localhost:8000/operator`:

- **Voltway Networks admin:** `operator@demo.dev` / `operate123` (owns the
  three driver-app demo stations above)
- **Beacon EV Networks admin:** `beacon-admin@demo.dev` / `operate123` — a
  second, unrelated operator seeded specifically to prove neither admin can
  see the other's stations, pricing, or tickets.

Fleet managers log in at `http://localhost:8000/fleet`:

- **Zenith Logistics manager:** `fleet-manager@demo.dev` / `fleet12345`,
  managing one driver (`fleet-driver@demo.dev` / `fleet12345`) with a
  company-owned vehicle already assigned — that driver has no personal
  payment method on file, since fleet billing routes to the company's cost
  report instead of a personal card.

VoltPath's own platform team logs in at `http://localhost:8000/admin`:

- **Platform super admin:** `admin@voltpath.dev` / `platform123` — sees
  every operator on the platform (not just one), and can suspend/reactivate
  one, which takes effect immediately on every request that operator's
  admins make, not just their next login.

New operators, fleets, and drivers can also just register themselves —
"New charging network? Register your company" on the operator login screen,
"Own a fleet of EVs? Register your company" on the fleet one, or "New here?
Create an account" on the driver one. No seeding required for any of them.

For anything beyond one local instance, set `EVPLATFORM_SECRET_KEY`
(urlsafe-base64, 32+ random bytes) in the environment before starting the
server — every instance behind a load balancer needs to validate auth
tokens with the same key. Without it, a key is generated once into
`backend/data/secret.key` for zero-setup local dev, which only works for a
single instance. See [docs/trust-engine-addendum.md](docs/trust-engine-addendum.md) §6
for this plus rate limiting and request logging.

## Run the tests

```
cd backend
python -m pytest
```

30 tests, no extra setup, runs in a few seconds against an isolated temp
database (never touches `backend/data/evplatform.db`). Covers the trust
engine (reliability scoring math, insurance auto-claims, Plug Watch
auto-fault-flip), RBAC/multi-tenant isolation (operators can't see each
other's data, suspension takes effect immediately), and session correctness
(idempotency, vehicle ownership, the fleet-vehicle regression covered below).

## What's here

```
backend/          FastAPI + SQLite. Real OCPP hardware/Central System is
                   simulated (backend/app/services/ocpp_sim.py) since none
                   exists in this environment — see addendum §6.
                   tests/ — pytest suite, see "Run the tests" above.
web/               index.html: the driver app — one HTML/CSS/JS codebase, two
                   real layouts (resize the window — <900px is mobile,
                   >=900px is desktop). operator.html / fleet.html / admin.html:
                   the station operator, fleet manager, and platform admin
                   dashboards. No build step for any of them.
ios-starter/       SwiftUI screens + APIClient, extended with Trust Engine+
                   (TrustBadge, Plug Watch report sheet, wallet/claim models).
android-starter/   The same screens/features in Kotlin/Jetpack Compose.
docs/              PRD, Postgres schema (production reference), OpenAPI spec,
                   and the Trust Engine+ addendum.
```

The operator dashboard (`backend/app/routers/operator.py`) is RBAC-gated
server-side (`station_admin`/`super_admin` only, see `auth.require_role`) and
every route is scoped to the caller's own `operator_id` — one charging
network's admin can never see or touch another's data. This is the actual
multi-tenant boundary a product sold to multiple, unrelated stations depends
on.

`ios-starter/` and `android-starter/` are real, extended source trees but
**cannot be compiled or run in this environment** — there's no Xcode or
Android SDK/JDK here. Building and running them needs Xcode on a Mac (iOS)
and Android Studio/JDK locally (Android). The backend and web app were
verified end-to-end in-browser; the native code was reviewed by reading it
back, not compiled.

## Next real steps (production stack)

1. Swap SQLite → PostgreSQL + Redis, FastAPI's dev auth → OAuth2/OIDC
   (Auth0/Keycloak), and the OCPP simulator → a real Central System
   (evaluate SteVe vs. building one) — see PRD §3.1 and §8 for the risk list
   around hardware-vendor variability.
2. Wire the iOS/Android Xcode/Gradle projects and real maps SDK (Google Maps
   Platform / Mapbox) — the starters intentionally don't include build
   tooling or maps wiring yet.

Every role from the PRD's permission matrix (§2) now has a working
surface — driver, station operator, fleet manager, and platform super
admin — so the remaining gaps are the real-world integrations above, not
missing product surface.
