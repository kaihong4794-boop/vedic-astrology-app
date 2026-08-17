"""City-name geocoding (Photon / OpenStreetMap) + timezone lookup.

Uses Photon (https://photon.komoot.io) rather than Nominatim directly:
Nominatim's public instance blocks most datacenter/cloud IP ranges
(including typical PaaS hosts like Render), while Photon serves the same
OSM data and works reliably from server-side deployments.
"""
from __future__ import annotations

import httpx
from timezonefinder import TimezoneFinder

_tf = TimezoneFinder()

PHOTON_URL = "https://photon.komoot.io/api/"
USER_AGENT = "VedicAstrologyWebApp/1.0"


def _display_name(props: dict) -> str:
    parts = [
        props.get("name"),
        props.get("city") if props.get("city") != props.get("name") else None,
        props.get("state"),
        props.get("country"),
    ]
    return "，".join(p for p in parts if p)


async def search_city(query: str, limit: int = 5) -> list[dict]:
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            PHOTON_URL,
            params={"q": query, "limit": limit},
            headers={"User-Agent": USER_AGENT},
        )
        resp.raise_for_status()
        data = resp.json()

    out = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        lon, lat = feature["geometry"]["coordinates"]
        tz = _tf.timezone_at(lat=lat, lng=lon)
        name = _display_name(props)
        if not name:
            continue
        out.append({
            "display_name": name,
            "lat": lat,
            "lon": lon,
            "timezone": tz,
        })
    return out
