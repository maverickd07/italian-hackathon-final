from sqlalchemy import inspect
from test_migration import fixture_data, migrate

from app.db import Association, Object


def test_secondary_indexes_present_after_migration(client):
    assert migrate(client, fixture_data()).status_code == 204
    inspector = inspect(client.app.state.engine)
    for model in (Object, Association):
        expected = {
            i.name
            for i in model.__table__.indexes
            if client.app.state.engine.dialect.name == "postgresql"
            or i.name != "ix_objects_properties_gin"
        }
        actual = (
            set()
            if client.app.state.engine.dialect.name == "sqlite"
            else {i["name"] for i in inspector.get_indexes(model.__tablename__)}
        )
        # SQLite inspector cannot introspect expression indexes, so query its catalog.
        if client.app.state.engine.dialect.name == "sqlite":
            from sqlalchemy import text

            with client.app.state.engine.connect() as conn:
                actual = {
                    r[0]
                    for r in conn.execute(text("select name from sqlite_master where type='index'"))
                }
        assert expected <= actual
