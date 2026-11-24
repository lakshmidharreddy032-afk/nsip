"""Workbench read load test (target: p95 < 300 ms for reads at 3x peak, ~900 submissions/day).

Tokens are minted by signing in through auth-service with a non-MFA demo role (data entry):
    locust -f scripts/load_test/locustfile.py --host http://localhost:8080 -u 50 -r 10 -t 5m --headless
"""
from __future__ import annotations

import os
import random

from locust import HttpUser, between, task

EMAIL = os.environ.get("LOAD_EMAIL", "dataentry@northstar.example")
PASSWORD = os.environ.get("LOAD_PASSWORD", "Northstar@2026!")


class Reviewer(HttpUser):
    wait_time = between(0.5, 2.0)

    def on_start(self) -> None:
        r = self.client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD}, name="auth: login")
        self.token = r.json()["token"]["access_token"]
        self.h = {"Authorization": f"Bearer {self.token}"}
        items = self.client.get("/api/v1/submissions?page_size=100", headers=self.h, name="queue").json()["items"]
        self.ids = [i["id"] for i in items] or ["missing"]

    @task(5)
    def queue(self) -> None:
        self.client.get(f"/api/v1/submissions?queue=review&page={random.randint(1, 3)}", headers=self.h, name="queue")

    @task(8)
    def detail(self) -> None:
        self.client.get(f"/api/v1/submissions/{random.choice(self.ids)}", headers=self.h, name="submission detail")

    @task(2)
    def dashboard(self) -> None:
        self.client.get("/api/v1/dashboards/ops", headers=self.h, name="ops dashboard")

    @task(1)
    def search(self) -> None:
        self.client.get("/api/v1/submissions?q=textiles", headers=self.h, name="search")
