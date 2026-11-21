import os
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg.rows import dict_row
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

Action = Literal["ALLOW", "BLOCK"]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    occurred_at: AwareDatetime
    action: Action
    rule: str = Field(max_length=64, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")


class EventGroup(BaseModel):
    action: Action
    rule: str
    count: int


class PostgresEvents:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def insert(self, event: Event) -> bool:
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            cursor = conn.execute(
                """
                INSERT INTO waf_events (event_id, occurred_at, action, rule)
                VALUES (%s, %s, %s, %s) ON CONFLICT (event_id) DO NOTHING
                """,
                (event.event_id, event.occurred_at, event.action, event.rule),
            )
            return cursor.rowcount == 1

    def summary(self) -> list[EventGroup]:
        with psycopg.connect(self.dsn, connect_timeout=3, row_factory=dict_row) as conn:
            rows = conn.execute(
                """
                SELECT action, rule, COUNT(*) AS count FROM waf_events
                GROUP BY action, rule ORDER BY count DESC, action, rule LIMIT 100
                """
            ).fetchall()
        return [EventGroup.model_validate(row) for row in rows]

    def ready(self) -> None:
        with psycopg.connect(self.dsn, connect_timeout=3) as conn:
            conn.execute("SELECT 1 FROM waf_events LIMIT 0")


def create_app(repository: PostgresEvents) -> FastAPI:
    app = FastAPI(title="Synthetic WAF Telemetry")

    @app.exception_handler(RequestValidationError)
    async def invalid_event(_request, _exc):
        return JSONResponse(status_code=422, content={"detail": "Invalid event."})

    @app.exception_handler(psycopg.Error)
    async def database_error(_request, _exc):
        return JSONResponse(
            status_code=503, content={"detail": "Database unavailable."}
        )

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def readiness():
        repository.ready()
        return {"status": "ready"}

    @app.post("/events", status_code=201)
    def ingest(event: Event):
        if not repository.insert(event):
            raise HTTPException(status_code=409, detail="Event ID already exists.")
        return {"event_id": event.event_id}

    @app.get("/summary")
    def summary() -> list[EventGroup]:
        return repository.summary()

    return app


app = create_app(PostgresEvents(os.environ.get("DATABASE_URL", "")))
