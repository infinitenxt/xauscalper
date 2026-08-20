"""Criterion: engine never sleeps.

GET /engine/health (no auth) returns 200 with running:true and a cycles
count that increases between two calls ~10s apart.
"""

import time

from .conftest import api_url
import httpx


def test_engine_health_cycles_increase_over_time():
    with httpx.Client(base_url=api_url(), timeout=30.0) as c:
        first = c.get("/engine/health")
        assert first.status_code == 200, f"GET /engine/health -> {first.status_code}: {first.text[:300]}"
        first_body = first.json()
        assert first_body["running"] is True, first_body

        time.sleep(10)

        second = c.get("/engine/health")
        assert second.status_code == 200, f"GET /engine/health -> {second.status_code}: {second.text[:300]}"
        second_body = second.json()
        assert second_body["running"] is True, second_body

        assert second_body["cycles"] > first_body["cycles"], (
            f"expected cycles to increase, got {first_body['cycles']} -> {second_body['cycles']}"
        )
