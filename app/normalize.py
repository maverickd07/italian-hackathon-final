"""Deterministic normalization of Sinergia source values."""

import re
import unicodedata
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit


def text(value):
    value = (value or "").strip()
    if "Ã" in value or "Â" in value:
        try:
            value = value.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return value


def norm(value):
    return " ".join(
        "".join(
            c
            for c in unicodedata.normalize("NFKD", text(value).lower())
            if not unicodedata.combining(c)
        ).split()
    )


def deleted(row):
    return norm(row.get("cancellato")) in {"s", "si", "1"}


def date(value):
    value = text(value)
    if not value:
        return None
    if re.fullmatch(r"\d{5}(?:[.,]\d+)?", value):
        return datetime(1899, 12, 30) + timedelta(days=float(value.replace(",", ".")))  # noqa: DTZ001 -- source civil dates
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%d-%m-%Y",
        "%d.%m.%y",
        "%d.%m.%Y",
    ):
        try:
            return datetime.strptime(value, fmt)  # noqa: DTZ007 -- timezone applied at import boundary
        except ValueError:
            pass
    raise ValueError(f"Unparsed date {value!r}")


def number(value, annual=False):
    value = norm(value)
    if not value:
        return None
    negative = "-" in value or ("(" in value and ")" in value)
    monthly = any(x in value for x in ("mese", "mensil"))
    multiplier = Decimal(1)
    if re.search(r"mln\b|milion[ei]\b", value):
        multiplier = Decimal(1000000)
    elif re.search(r"k\b|mila\b", value):
        multiplier = Decimal(1000)
    match = re.search(r"\d[\d.,\s]*", value)
    if not match:
        raise ValueError(f"Unparsed number {value!r}")
    token = re.sub(r"\s+", "", match[0]).rstrip(".,")
    if "," in token and "." in token:
        decimal_sep = "," if token.rfind(",") > token.rfind(".") else "."
        token = token.replace("." if decimal_sep == "," else ",", "").replace(decimal_sep, ".")
    elif "," in token or "." in token:
        sep = "," if "," in token else "."
        parts = token.split(sep)
        if len(parts[-1]) == 3 and all(len(part) == 3 for part in parts[1:]):
            token = "".join(parts)
        else:
            token = "".join(parts[:-1]) + "." + parts[-1]
    result = Decimal(token) * multiplier * (-1 if negative else 1)
    return result * 12 if annual and monthly else result


def domain(value):
    value = text(value).lower()
    if not value:
        return ""
    host = urlsplit(value if "://" in value else "//" + value).hostname or ""
    return host.removeprefix("www.").rstrip(".")


def vat(value):
    # R7 specifies eleven digits, not checksum validation. Recognize explicit
    # source labels only, including the abbreviated PI/P.I. form.
    found = re.findall(
        r"(?<!\w)(?:partita\s*iva|p[.\s]*i(?:[.\s]*v[.\s]*a)?)"
        r"[.\s]*[:=\-]?\s*(?:IT\s*)?([0-9](?:\s*[0-9]){10})(?!\w|\s+[0-9])",
        value,
        flags=re.IGNORECASE,
    )
    return list(dict.fromkeys(re.sub(r"\s", "", item) for item in found))


def emails(value):
    value = re.sub(r"\(at\)", "@", text(value), flags=re.IGNORECASE)
    value = re.sub(r"\s*@\s*", "@", value).lower()
    return list(
        dict.fromkeys(
            re.findall(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9-]+(?:\.[a-z0-9-]+)+", value)
        )
    )


def sku(value):
    digits = "".join(re.findall(r"\d", value))
    return "BF-" + digits.zfill(5) if digits else ""


def stage(value):
    value = norm(value)
    match = re.match(r"(r[1-4]|0?[1-7])\b", value)
    if match:
        return match[1].upper() if match[1].startswith("r") else match[1].zfill(2)
    return {
        "contatto": "01",
        "qualifica": "02",
        "presentazione": "03",
        "decisione": "04",
        "contratto": "05",
        "vinta": "06",
        "persa": "07",
        "da rinnovare": "R1",
        "in trattativa": "R2",
        "rinnovato": "R3",
        "non rinnovato": "R4",
    }.get(value, "UNKNOWN:" + value)


class Union:
    def __init__(self, ids):
        self.parent = {key: key for key in ids}

    def root(self, key):
        while self.parent[key] != key:
            self.parent[key] = self.parent[self.parent[key]]
            key = self.parent[key]
        return key

    def join(self, a, b):
        self.parent[self.root(a)] = self.root(b)
