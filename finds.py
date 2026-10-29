"""Validated search contract shared by Flask and the serverless endpoint."""

import logging
import math

import requests

import craigslist
from classify import classify

log = logging.getLogger(__name__)


def parse_search_params(query=None):
    query = query or {}

    def number(key, default):
        value = query.get(key, default)
        if isinstance(value, (list, tuple)):
            if len(value) != 1:
                raise ValueError(f"Provide {key} only once.")
            value = value[0]
        try:
            result = float(value)
        except (ValueError, TypeError):
            raise ValueError(f"{key} must be a finite number.") from None
        if not math.isfinite(result):
            raise ValueError(f"{key} must be a finite number.")
        return result

    if ("lat" in query) != ("lon" in query):
        raise ValueError("Provide both lat and lon.")
    lat = number("lat", craigslist.CENTER_LAT)
    lon = number("lon", craigslist.CENTER_LON)
    radius = number("radius_km", craigslist.RADIUS_KM)
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Coordinates must be within latitude ±90 and longitude ±180.")
    if not 1 <= radius <= 25:
        raise ValueError("radius_km must be between 1 and 25.")
    return {"lat": lat, "lon": lon, "radius_km": radius}


def build_payload(query=None):
    selection = parse_search_params(query)
    rows, region = craigslist.search(**selection)
    finds = []
    for row in rows:
        category, glyph = classify(row["title"])
        finds.append(
            {
                "id": row["cl_id"],
                "title": row["title"],
                "url": row["url"],
                "thumb": row["thumb"],
                "lat": row["lat"],
                "lon": row["lon"],
                "neighborhood": row.get("neighborhood"),
                "category": category,
                "glyph": glyph,
            }
        )
    return {
        "center": {"lat": selection["lat"], "lon": selection["lon"]},
        "radius_km": selection["radius_km"],
        "region": region,
        "finds": finds,
    }


def search_response(query=None):
    try:
        return build_payload(query), 200
    except craigslist.UnsupportedLocation as exc:
        return {"error": str(exc), "finds": []}, 422
    except ValueError as exc:
        return {"error": str(exc), "finds": []}, 400
    except (requests.RequestException, craigslist.UpstreamError):
        log.exception("Craigslist search failed")
        return {
            "error": "Could not update from Craigslist. Please try again.",
            "finds": [],
        }, 502
