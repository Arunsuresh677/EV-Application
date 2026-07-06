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

- **Login:** `driver@demo.dev` / `chargeme123`
- Three demo stations, including one connector deliberately seeded with a low
  score so its sessions fail somewhat often — that's what makes the
  reliability/insurance/Plug Watch behavior demonstrable instead of
  theoretical. See [docs/trust-engine-addendum.md](docs/trust-engine-addendum.md) §6.

## What's here

```
backend/          FastAPI + SQLite. Real OCPP hardware/Central System is
                   simulated (backend/app/services/ocpp_sim.py) since none
                   exists in this environment — see addendum §6.
web/               The driver web app: one HTML/CSS/JS codebase, two real
                   layouts (resize the window — <900px is the mobile layout,
                   >=900px is the desktop layout). No build step.
ios-starter/       SwiftUI screens + APIClient, extended with Trust Engine+
                   (TrustBadge, Plug Watch report sheet, wallet/claim models).
android-starter/   The same screens/features in Kotlin/Jetpack Compose.
docs/              PRD, Postgres schema (production reference), OpenAPI spec,
                   and the Trust Engine+ addendum.
```

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
3. Build the operator dashboard and fleet module (PRD §2, roles beyond
   `driver`) — out of scope for this pass, which focused on the driver app.
