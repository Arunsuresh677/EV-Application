from __future__ import annotations

import math

from fastapi import APIRouter, Depends, HTTPException, Query

from .. import auth, db

router = APIRouter(tags=["stations"])


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _connector_summary(row: dict) -> dict:
    return {
        "id": row["id"],
        "type": row["type"],
        "power_kw": row["power_kw"],
        "status": row["status"],
        "reliability_score": row["reliability_score"],
        "guaranteed": bool(row["guaranteed"]),
    }


@router.get("/stations/search")
def search_stations(
    lat: float,
    lng: float,
    radius_km: float = 10,
    connector_type: str | None = None,
    min_power_kw: float | None = None,
    available_only: bool = False,
    user: dict = Depends(auth.get_current_user),
):
    conn = db.get_conn()
    stations = db.rows_to_list(conn.execute("SELECT * FROM stations").fetchall())
    results = []

    for station in stations:
        distance = _haversine_km(lat, lng, station["lat"], station["lng"])
        if distance > radius_km:
            continue

        connectors = db.rows_to_list(
            conn.execute("SELECT * FROM connectors WHERE station_id=?", (station["id"],)).fetchall()
        )
        if connector_type:
            connectors = [c for c in connectors if c["type"] == connector_type]
        if min_power_kw is not None:
            connectors = [c for c in connectors if c["power_kw"] >= min_power_kw]
        if not connectors:
            continue

        available = [c for c in connectors if c["status"] == "available"]
        if available_only and not available:
            continue

        tariff = db.row_to_dict(
            conn.execute("SELECT * FROM tariffs WHERE operator_id=? ORDER BY created_at DESC LIMIT 1", (station["operator_id"],)).fetchone()
        )
        avg_score = sum(c["reliability_score"] for c in connectors) / len(connectors)

        results.append(
            {
                "id": station["id"],
                "name": station["name"],
                "lat": station["lat"],
                "lng": station["lng"],
                "distance_km": round(distance, 2),
                "min_price_per_kwh": tariff["rate"] if tariff else None,
                "connectors_available": len(available),
                "connectors_total": len(connectors),
                "reliability_score": round(avg_score, 1),
            }
        )

    results.sort(key=lambda s: s["distance_km"])
    return results


@router.get("/stations/{station_id}")
def get_station(station_id: str, user: dict = Depends(auth.get_current_user)):
    conn = db.get_conn()
    station = db.row_to_dict(conn.execute("SELECT * FROM stations WHERE id=?", (station_id,)).fetchone())
    if station is None:
        raise HTTPException(status_code=404, detail="Station not found")

    connectors = db.rows_to_list(conn.execute("SELECT * FROM connectors WHERE station_id=?", (station_id,)).fetchall())
    tariff = db.row_to_dict(
        conn.execute("SELECT * FROM tariffs WHERE operator_id=? ORDER BY created_at DESC LIMIT 1", (station["operator_id"],)).fetchone()
    )
    available = [c for c in connectors if c["status"] == "available"]
    avg_score = sum(c["reliability_score"] for c in connectors) / len(connectors) if connectors else 0

    return {
        "id": station["id"],
        "name": station["name"],
        "address": station["address"],
        "lat": station["lat"],
        "lng": station["lng"],
        "distance_km": None,
        "min_price_per_kwh": tariff["rate"] if tariff else None,
        "connectors_available": len(available),
        "connectors_total": len(connectors),
        "reliability_score": round(avg_score, 1),
        "connectors": [_connector_summary(c) for c in connectors],
        "tariff": {"pricing_model": tariff["pricing_model"], "rate": tariff["rate"]} if tariff else None,
    }
