import os
import re
from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool
from sqlalchemy.schema import CreateIndex, DropIndex

from app.ui_sql import UINumber, UIPrefix, UIProperty


def now():
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Object(Base):
    __tablename__ = "objects"
    id: Mapped[str] = mapped_column(Text, primary_key=True, default=lambda: str(uuid4().int))
    object_type: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    __table_args__ = (
        UniqueConstraint("object_type", "id"),
        Index("ix_objects_type_archive_id", "object_type", "archived", "id"),
        Index("ix_objects_properties_gin", "properties", postgresql_using="gin").ddl_if(
            dialect="postgresql"
        ),
    )


LEGACY_INDEX = Index(
    "ix_objects_legacy_lookup", Object.object_type, Object.properties["id_legacy"].as_string()
)


# Database-enforced identity covers ordinary create/PATCH as well as upsert.
CONTACT_EMAIL_INDEX = Index(
    "uq_active_contact_email",
    func.lower(UIProperty(Object.properties, "email")),
    unique=True,
    postgresql_where=(Object.object_type == "contacts")
    & Object.archived.is_(False)
    & (UIProperty(Object.properties, "email") != ""),
    sqlite_where=(Object.object_type == "contacts")
    & Object.archived.is_(False)
    & (UIProperty(Object.properties, "email") != ""),
)


# UI lookups use bounded prefix ranges and exact pipeline/filter predicates.
UI_INDEXES = []
for field in ("name", "domain", "firstname", "lastname", "email"):
    from sqlalchemy import func

    UI_INDEXES.append(
        Index(
            "ix_ui_search_" + field,
            Object.object_type,
            Object.archived,
            func.lower(UIProperty(Object.properties, field)),
            Object.id,
        )
    )
for label, fields in {
    "deal_stage": ("pipeline", "dealstage"),
    "deal_owner": ("pipeline", "commerciale", "dealstage"),
    "ticket_stage": ("hs_pipeline", "hs_pipeline_stage"),
    "ticket_priority": ("hs_pipeline", "hs_ticket_priority", "hs_pipeline_stage"),
    "ticket_owner": ("hs_pipeline", "assegnatario", "hs_ticket_priority", "hs_pipeline_stage"),
}.items():
    UI_INDEXES.append(
        Index(
            "ix_ui_" + label,
            Object.object_type,
            Object.archived,
            *(UIProperty(Object.properties, field) for field in fields),
            Object.id,
        )
    )
UI_INDEXES.append(
    Index("ix_ui_activity_date", Object.object_type, Object.archived, Object.created_at, Object.id)
)


class Association(Base):
    __tablename__ = "associations"
    from_type: Mapped[str] = mapped_column(Text, primary_key=True)
    from_id: Mapped[str] = mapped_column(Text, primary_key=True)
    to_type: Mapped[str] = mapped_column(Text, primary_key=True)
    to_id: Mapped[str] = mapped_column(Text, primary_key=True)
    type_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    __table_args__ = (
        ForeignKeyConstraint(["from_type", "from_id"], ["objects.object_type", "objects.id"]),
        ForeignKeyConstraint(["to_type", "to_id"], ["objects.object_type", "objects.id"]),
        Index("ix_associations_target", "to_type", "to_id"),
    )


class Metadata(Base):
    __tablename__ = "crm_metadata"
    namespace: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON().with_variant(JSONB, "postgresql"))


class ListMember(Base):
    __tablename__ = "list_members"
    list_id: Mapped[str] = mapped_column(Text, primary_key=True)
    record_id: Mapped[str] = mapped_column(Text, primary_key=True)


class UniqueValue(Base):
    __tablename__ = "unique_values"
    object_type: Mapped[str] = mapped_column(Text, primary_key=True)
    property_name: Mapped[str] = mapped_column(Text, primary_key=True)
    value: Mapped[str] = mapped_column(Text, primary_key=True)
    record_id: Mapped[str] = mapped_column(Text, index=True)


# Additional UI-only indexes; no change to migration or API schemas.
for field in ("name", "domain", "firstname", "lastname", "email"):
    UI_INDEXES.append(
        Index(
            "ix_ui_prefix_" + field,
            Object.object_type,
            Object.archived,
            UIPrefix(Object.properties, field),
            Object.id,
        )
    )
for label, fields in {
    "owner_deal": ("commerciale", "dealstage", "closedate"),
    "owner_ticket": ("assegnatario", "hs_pipeline_stage", "subject"),
    "task_due": ("hs_task_status", "hs_timestamp"),
}.items():
    UI_INDEXES.append(
        Index(
            "ix_ui_" + label,
            Object.object_type,
            Object.archived,
            *(UIProperty(Object.properties, field) for field in fields),
            Object.id,
        )
    )
UI_INDEXES.extend(
    [
        Index(
            "ix_ui_company_revenue",
            Object.object_type,
            Object.archived,
            UINumber(Object.properties, "fatturato_2025").desc(),
            Object.id,
        ),
        Index(
            "ix_ui_company_class_revenue",
            Object.object_type,
            Object.archived,
            UIProperty(Object.properties, "classe_cliente"),
            UINumber(Object.properties, "fatturato_2025").desc(),
            Object.id,
        ),
        Index(
            "ix_ui_users_active",
            Metadata.namespace,
            func.lower(UIProperty(Metadata.value, "attivo")),
            Metadata.key,
        ),
        Index(
            "ix_ui_users_email", Metadata.namespace, func.lower(UIProperty(Metadata.value, "email"))
        ),
        Index(
            "ix_ui_users_manager", Metadata.namespace, UIProperty(Metadata.value, "responsabile")
        ),
    ]
)


# A company/deal index must not index hundreds of thousands of history objects.
# Predicates exactly match the object-type predicates used by UI queries.
for index in UI_INDEXES:
    if index.table is not Object.__table__ or index.name == "ix_ui_activity_date":
        continue
    name = index.name
    if "company" in name or name.endswith(("_name", "_domain")):
        scope = ["companies"]
    elif name.endswith(("_firstname", "_lastname", "_email")):
        scope = ["contacts"]
    elif "deal" in name:
        scope = ["deals"]
    elif "ticket" in name:
        scope = ["tickets"]
    elif "task" in name:
        scope = ["tasks"]
    else:
        continue
    predicate = Object.object_type.in_(scope)
    index.dialect_options["postgresql"]["where"] = predicate
    index.dialect_options["sqlite"]["where"] = predicate


def make_engine(url=None):
    url = url or os.getenv("DATABASE_URL", "sqlite:///./crm.db")
    if os.getenv("RAILWAY_ENVIRONMENT_ID") and not url.startswith(
        ("postgres://", "postgresql://", "postgresql+psycopg://")
    ):
        raise RuntimeError("Railway requires persistent PostgreSQL via DATABASE_URL")
    if url.startswith(("postgres://", "postgresql://")):
        url = "postgresql+psycopg://" + url.split("://", 1)[1]
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    engine = create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def configure_sqlite(dbapi, _):
            import sqlite3
            import time

            dbapi.execute("PRAGMA foreign_keys=ON")
            dbapi.execute("PRAGMA busy_timeout=30000")
            # First-open WAL setup can return SQLITE_BUSY immediately despite the
            # busy timeout when another worker is opening the same fresh file.
            for attempt in range(50):
                try:
                    if dbapi.execute("PRAGMA journal_mode").fetchone()[0] != "wal":
                        dbapi.execute("PRAGMA journal_mode=WAL")
                    break
                except sqlite3.OperationalError as exc:
                    if "locked" not in str(exc).lower() or attempt == 49:
                        raise
                    time.sleep(0.05)
            dbapi.create_function(
                "regexp",
                2,
                lambda pattern, value: bool(value is not None and re.search(pattern, str(value))),
                deterministic=True,
            )

    return engine


def init_db(engine):
    # Serialize first-start DDL across Railway workers/replicas.
    with engine.begin() as conn:
        if engine.dialect.name == "postgresql":
            conn.execute(text("SELECT pg_advisory_xact_lock(74102901)"))
        elif engine.dialect.name == "sqlite":
            # Serialize check/create DDL when two local workers start together.
            conn.exec_driver_sql("BEGIN IMMEDIATE")
        Base.metadata.create_all(conn)
        conn.execute(CreateIndex(LEGACY_INDEX, if_not_exists=True))
        conn.execute(CreateIndex(CONTACT_EMAIL_INDEX, if_not_exists=True))
        for index in UI_INDEXES:
            if (
                engine.dialect.name == "postgresql"
                and index.dialect_options["postgresql"].get("where") is not None
            ):
                # Upgrade only our former unscoped indexes, once, under the DDL lock.
                unscoped = conn.scalar(
                    text(
                        "SELECT i.indpred IS NULL FROM pg_index i JOIN pg_class c ON c.oid=i.indexrelid WHERE c.relname=:name AND c.relnamespace=current_schema()::regnamespace"
                    ),
                    {"name": index.name},
                )
                if unscoped:
                    conn.execute(DropIndex(index, if_exists=True))
            conn.execute(CreateIndex(index, if_not_exists=True))


@contextmanager
def transaction(engine, write=False):
    with Session(engine, expire_on_commit=False) as session:
        try:
            if write and engine.dialect.name == "sqlite":
                # SQLite has no SELECT FOR UPDATE; acquire the write lock before reading.
                session.execute(text("BEGIN IMMEDIATE"))
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
