"""Read source only; compare independent VAT parsers and audit checksum policy."""

import csv
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

from analysis.audit_sinergia import vat as independent_vat
from app.normalize import deleted, vat


def main(source, output):
    with source.open(encoding="cp1252", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    previous = re.compile(
        r"(?:partita\s*iva|p[.\s]*i[.\s]*v[.\s]*a)\s*[:=\-]?\s*(?:IT\s*)?(\d(?:\s*\d){10})(?!\d)",
        re.IGNORECASE,
    )
    report = {"source_sha256": hashlib.sha256(source.read_bytes()).hexdigest()}
    for title, selected in [("all", rows), ("active", [r for r in rows if not deleted(r)])]:
        counts = Counter()
        for row in selected:
            values = vat(row["note"])
            assert values == independent_vat(row["note"]), row["id_azienda"]
            counts["rows"] += 1
            counts["with_vat"] += bool(values)
            counts["previously_missed"] += bool(values) and not previous.search(row["note"])
            for value in values:
                total = sum(
                    int(digit) if i % 2 == 0 else sum(divmod(2 * int(digit), 10))
                    for i, digit in enumerate(value[:10])
                )
                valid = (10 - total % 10) % 10 == int(value[-1])
                counts["checksum_valid" if valid else "checksum_invalid"] += 1
        report[title] = dict(counts)
    report["policy"] = "R7 eleven ASCII digits; checksum audited, not a rejection condition."
    output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]), Path(sys.argv[2]))
