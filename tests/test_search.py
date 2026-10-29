"""Behavior at the search API boundary, with synthetic source responses."""

import importlib.util
import io
import json
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock

import pytest
import requests

import app
import craigslist

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def source(monkeypatch):
    craigslist.resolve_region.cache_clear()
    calls = []

    def get(url, *, params, **kwargs):
        calls.append(dict(params))
        place = "vancouver" if params["lat"] > 45 or params["lat"] == 0 else "atlanta"
        payload = json.loads((FIXTURES / f"{place}.json").read_text(encoding="utf-8"))
        if params["lat"] != 0:
            payload["data"]["location"]["lat"] = round(params["lat"], 4)
            payload["data"]["location"]["lon"] = round(params["lon"], 4)
        response = Mock()
        response.json.return_value = payload
        return response

    monkeypatch.setattr(craigslist.requests, "get", get)
    return calls


@pytest.fixture(params=["flask", "serverless"])
def api(request):
    def call(query):
        if request.param == "flask":
            r = app.app.test_client().get("/api/finds?" + urlencode(query, doseq=True))
            return r.status_code, r.get_json()
        spec = importlib.util.spec_from_file_location(
            "serverless_test", Path(__file__).parents[1] / "api/finds.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        handler = object.__new__(module.handler)
        handler.path = "/api/finds?" + urlencode(query, doseq=True)
        handler.wfile = io.BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.do_GET()
        return handler.send_response.call_args.args[0], json.loads(
            handler.wfile.getvalue()
        )

    return call


def test_no_query_preserves_vancouver_default_payload_and_kilometers(api, source):
    status, body = api({})
    assert status == 200
    assert body["center"] == {"lat": 49.2606, "lon": -123.1140}
    assert body["radius_km"] == 25
    assert body["region"]["distance_unit"] == "km"
    assert source[-1]["search_distance"] == 25
    assert source[-1]["areaId"] == 16
    assert source[-1]["cc"] == "CA"
    assert body["finds"][0]["category"]


def test_custom_center_and_radius_reach_source_in_region_units(api, source):
    status, body = api({"lat": "33.75", "lon": "-84.39", "radius_km": "16.09344"})
    assert status == 200
    assert body["center"] == {"lat": 33.75, "lon": -84.39}
    assert body["radius_km"] == 16.09344
    assert body["region"]["area_id"] == 14
    assert body["region"]["distance_unit"] == "mi"
    assert source[-1]["areaId"] == 14
    assert source[-1]["cc"] == "US"
    assert source[-1]["lat"] == 33.75
    assert source[-1]["lon"] == -84.39
    assert source[-1]["search_distance"] == pytest.approx(10)
    assert "subAreaId" not in source[-1]
    assert len(body["finds"]) == 3


@pytest.mark.parametrize(
    "query",
    [
        {"lat": "nan", "lon": "0"},
        {"lat": "inf", "lon": "0"},
        {"lat": "91", "lon": "0"},
        {"lat": "0", "lon": "-181"},
        {"lat": "abc", "lon": "0"},
        {"lat": "10"},
        {"lon": "10"},
        {"radius_km": "0"},
        {"radius_km": "26"},
        {"radius_km": "nan"},
        {"radius_km": ""},
        {"lat": ["10", "20"], "lon": "30"},
    ],
)
def test_bad_search_is_400_without_source_request(api, source, query):
    status, body = api(query)
    assert status == 400
    assert body["error"]
    assert source == []


def test_unsupported_center_does_not_silently_return_vancouver(api, source):
    status, body = api({"lat": "0", "lon": "0", "radius_km": "10"})
    assert status == 422
    assert "cover" in body["error"].lower()
    assert body["finds"] == []


def test_source_failure_is_explicit_502(api, monkeypatch):
    monkeypatch.setattr(
        craigslist.requests, "get", Mock(side_effect=requests.Timeout("timeout"))
    )
    status, body = api({})
    assert status == 502
    assert body["error"]


def test_empty_feed_is_a_successful_empty_search(api, monkeypatch):
    payload = json.loads((FIXTURES / "vancouver.json").read_text(encoding="utf-8"))
    payload["data"]["items"] = []
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(craigslist.requests, "get", Mock(return_value=response))
    status, body = api({})
    assert status == 200
    assert body["finds"] == []


def test_resolved_region_is_reused_for_new_radius(source):
    craigslist.crawl(lat=33.75, lon=-84.39, radius_km=10)
    first_count = len(source)
    craigslist.crawl(lat=33.75, lon=-84.39, radius_km=20)
    assert len(source) == first_count + 1
    assert source[-1]["search_distance"] == pytest.approx(12.4274238)


@pytest.mark.parametrize(
    "field,value", [("lat", "invalid"), ("lon", None), ("areaId", "invalid")]
)
def test_malformed_source_metadata_is_upstream_error_not_client_error(
    api, monkeypatch, field, value
):
    payload = json.loads((FIXTURES / "vancouver.json").read_text(encoding="utf-8"))
    payload["data"]["location"][field] = value
    response = Mock()
    response.json.return_value = payload
    monkeypatch.setattr(craigslist.requests, "get", Mock(return_value=response))
    status, body = api({})
    assert status == 502
    assert body["error"] == "Could not update from Craigslist. Please try again."


def test_sparse_region_uses_search_unit_metadata_without_area_rows(api, monkeypatch):
    # A valid region can have no area rows, including when nearby extras exist.
    payload = json.loads((FIXTURES / "atlanta.json").read_text(encoding="utf-8"))
    payload["data"]["areas"] = {}
    payload["data"]["items"] = []
    response = Mock()
    response.json.return_value = payload
    request = Mock(return_value=response)
    monkeypatch.setattr(craigslist.requests, "get", request)
    craigslist.resolve_region.cache_clear()
    status, body = api({"lat": "33.75", "lon": "-84.39", "radius_km": "16.09344"})
    assert status == 200
    assert body["region"]["distance_unit"] == "mi"
    assert body["finds"] == []
    assert request.call_args.kwargs["params"]["search_distance"] == pytest.approx(10)
