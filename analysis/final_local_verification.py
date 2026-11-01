"""Read-only raw-source oracle plus a disposable local PostgreSQL full import.

Run with TEST_DATABASE_URL and SOURCE_DIRECTORY. Never uses Railway or a model.
The randomly named schema is removed even when validation fails.
"""

import contextlib
import io
import json
import os
import time
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url

from analysis.audit_sinergia import main as raw_audit
from app.db import Association, ListMember, Metadata, Object, init_db, make_engine, transaction
from app.migration import Source, migrate


def main():
    url = make_url(os.environ["TEST_DATABASE_URL"])
    if url.host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError("Verification must use a local disposable PostgreSQL schema")
    source_path = Path(os.environ["SOURCE_DIRECTORY"])
    print("Computing independent raw-CSV expectations", flush=True)
    started = time.monotonic()
    with contextlib.redirect_stdout(io.StringIO()):
        expected = raw_audit(source_path, Path("/tmp/relay-final-raw-audit.json"))
    report = {"raw_audit_seconds": round(time.monotonic() - started, 3), "model_called": False}
    schema = "final_verification_" + uuid4().hex
    admin = make_engine(url.render_as_string(hide_password=False))
    engine = None
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        engine = make_engine(
            url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
                hide_password=False
            )
        )
        init_db(engine)
        print("Importing all nine files into isolated local PostgreSQL", flush=True)
        started = time.monotonic()
        source = Source(source_path)
        try:
            with transaction(engine, write=True) as session:
                report["counts"] = migrate(session, source)
        finally:
            source.close()
        report["migration_seconds_excluding_network"] = round(time.monotonic() - started, 3)
        print(
            "Comparing every company revenue/class, dormant member, contact link and quote total",
            flush=True,
        )
        with transaction(engine) as session:
            companies = session.scalars(
                select(Object).where(Object.object_type == "companies")
            ).all()
            company_legacy = {row.id: row.properties["id_legacy"] for row in companies}
            actual_revenue = {
                row.properties["id_legacy"]: row.properties.get("fatturato_2025")
                for row in companies
            }
            assert actual_revenue == expected["company_revenue"], "R8 per-company revenue differs"
            for row in companies:
                value = Decimal(expected["company_revenue"][row.properties["id_legacy"]])
                grade = (
                    "A" if value >= 100000 else "B" if value >= 20000 else "C" if value > 0 else ""
                )
                assert row.properties.get("classe_cliente", "") == grade
            members = session.scalars(
                select(ListMember.record_id).where(ListMember.list_id == "1")
            ).all()
            assert sorted(company_legacy[i] for i in members) == expected["dormant"]
            contact_rows = session.scalars(
                select(Object).where(Object.object_type == "contacts")
            ).all()
            links = {}
            for from_id, to_id in session.execute(
                select(Association.from_id, Association.to_id).where(
                    Association.from_type == "contacts", Association.to_type == "companies"
                )
            ):
                links.setdefault(from_id, set()).add(company_legacy[to_id])
            assert {row.properties["id_legacy"] for row in contact_rows} == set(
                expected["contact_company"]
            )
            for row in contact_rows:
                company = expected["contact_company"][row.properties["id_legacy"]]
                assert links.get(row.id, set()) == ({company} if company else set())
            checked_quotes = 0
            for row in session.scalars(select(Object).where(Object.object_type == "deals")):
                legacy = row.properties["id_legacy"]
                if legacy in expected["quote_totals"]:
                    assert Decimal(row.properties["amount"]) == Decimal(
                        expected["quote_totals"][legacy]
                    )
                    assert row.properties["deal_currency_code"] == "EUR"
                    checked_quotes += 1
            assert checked_quotes == len(expected["quote_totals"])
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Metadata)
                    .where(Metadata.namespace == "automation")
                )
                == 0
            )
            report.update(
                companies_with_vat=sum(
                    bool(row.properties.get("partita_iva")) for row in companies
                ),
                revenue_total=str(
                    sum((Decimal(value) for value in actual_revenue.values()), Decimal(0))
                ),
                source_company_audit=expected["report"]["companies"]
                if "report" in expected
                else None,
                company_revenue_and_class_checked=len(companies),
                contact_company_associations_checked=len(contact_rows),
                quote_deal_totals_checked=checked_quotes,
                dormant_members_checked=len(members),
                associations=session.scalar(select(func.count()).select_from(Association)),
                migration_diagnostics=session.get(Metadata, ("migration", "last")).value["log"],
                assertions_passed=True,
            )
        Path(
            os.environ.get("VERIFICATION_OUTPUT", "analysis/final-local-full-verification.json")
        ).write_text(json.dumps(report, indent=2))
        print(
            json.dumps({k: v for k, v in report.items() if k != "migration_diagnostics"}, indent=2)
        )
    finally:
        if engine:
            engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


if __name__ == "__main__":
    main()
