from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db import now, transaction
from app.store import iso


def db(request: Request):
    write = request.method in {"POST", "PATCH", "PUT", "DELETE"} and not request.url.path.endswith(
        ("/search", "/batch/read")
    )
    with transaction(request.app.state.engine, write=write) as session:
        if session.bind.dialect.name == "postgresql" and request.url.path != "/health":
            exclusive = request.url.path in {"/__reset", "/__migrate"}
            function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
            session.execute(text(f"SELECT {function}(74102902)"))
        yield session


# Commit before sending a successful response, including constraint/connection errors.
DB = Annotated[Session, Depends(db, scope="function")]


def batch_result(results, started):
    return {
        "status": "COMPLETE",
        "results": results,
        "startedAt": iso(started),
        "completedAt": iso(now()),
    }
