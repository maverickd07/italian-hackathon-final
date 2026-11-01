"""Literal, allowlisted JSON paths so SQLite and PostgreSQL can use expression indexes."""

from sqlalchemy import Numeric, Text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement


class UIProperty(FunctionElement):
    type = Text()
    inherit_cache = False

    def __init__(self, column, field):
        if not field.replace("_", "").isalnum():
            raise ValueError("Invalid property index")
        self.field = field
        super().__init__(column)


@compiles(UIProperty, "sqlite")
def sqlite_property(element, compiler, **kw):
    column = compiler.process(next(iter(element.clauses)), **kw)
    return f'''JSON_EXTRACT({column}, '$."{element.field}"')'''


@compiles(UIProperty, "postgresql")
def postgres_property(element, compiler, **kw):
    column = compiler.process(next(iter(element.clauses)), **kw)
    return f"(CAST({column} ->> '{element.field}' AS VARCHAR))"


class UINumber(UIProperty):
    """Safe numeric JSON value, also suitable for a database expression index."""

    type = Numeric()
    inherit_cache = False


@compiles(UINumber, "sqlite")
def sqlite_number(element, compiler, **kw):
    value = sqlite_property(element, compiler, **kw)
    return f"COALESCE(CAST({value} AS NUMERIC), 0)"


@compiles(UINumber, "postgresql")
def postgres_number(element, compiler, **kw):
    value = postgres_property(element, compiler, **kw)
    return f"(CASE WHEN {value} ~ '^-?[0-9]+(\\.[0-9]+)?$' THEN CAST({value} AS NUMERIC) ELSE 0 END)"


class UIPrefix(UIProperty):
    """Binary collation gives indexed prefix ranges consistent semantics on both databases."""

    inherit_cache = False


@compiles(UIPrefix, "sqlite")
def sqlite_prefix(element, compiler, **kw):
    return f"lower({sqlite_property(element, compiler, **kw)}) COLLATE BINARY"


@compiles(UIPrefix, "postgresql")
def postgres_prefix(element, compiler, **kw):
    return f'lower({postgres_property(element, compiler, **kw)}) COLLATE "C"'
