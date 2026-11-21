import json
import os
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from app import PostgresEvents, create_app

HERE = Path(__file__).parent
SAMPLE = json.loads((HERE / "sample.json").read_text(encoding="utf-8"))


@pytest.fixture
def no_database():
    dsn = "hostaddr=127.0.0.1 port=1 connect_timeout=1"
    with TestClient(create_app(PostgresEvents(dsn))) as client:
        yield client


def test_liveness_and_unavailable_database(no_database):
    assert no_database.get("/healthz").json() == {"status": "ok"}
    response = no_database.get("/readyz")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable."}


@pytest.mark.parametrize(
    "fields",
    [
        {"private_header": "private-value"},
        {"occurred_at": "2026-01-01T12:00:00"},
        {"action": "OTHER"},
        {"rule": "invalid rule name"},
        {"event_id": "not-a-uuid"},
    ],
)
def test_invalid_input_does_not_echo_body(no_database, fields):
    response = no_database.post("/events", json={**SAMPLE, **fields})
    assert response.status_code == 422
    assert response.json() == {"detail": "Invalid event."}


@pytest.fixture
def database():
    dsn = os.getenv("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("Set TEST_DATABASE_URL to a disposable PostgreSQL database")
    schema_name = f"test_{uuid4().hex}"
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema_name)))
        try:
            conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema_name)))
            conn.execute((HERE / "schema.sql").read_text(encoding="utf-8"))
            yield make_conninfo(dsn, options=f"-c search_path={schema_name}")
        finally:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))


def test_postgres_persistence_duplicate_and_summary(database):
    with TestClient(create_app(PostgresEvents(database))) as client:
        assert client.get("/readyz").status_code == 200
        assert client.get("/summary").json() == []
        response = client.post("/events", json=SAMPLE)
        assert response.status_code == 201
        assert response.json() == {"event_id": SAMPLE["event_id"]}
        assert (
            client.post("/events", json={**SAMPLE, "action": "BLOCK"}).status_code
            == 409
        )
        for _ in range(2):
            event = dict(SAMPLE, event_id=str(uuid4()), action="BLOCK", rule="DemoRule")
            assert client.post("/events", json=event).status_code == 201
    with TestClient(create_app(PostgresEvents(database))) as client:
        assert client.get("/summary").json() == [
            {"action": "BLOCK", "rule": "DemoRule", "count": 2},
            {"action": "ALLOW", "rule": "DemoDefault", "count": 1},
        ]
