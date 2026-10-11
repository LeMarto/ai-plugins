"""Locate term passages in extracted document text (.txt files from `rueda cnv dl`).

Usage: rueda on find-terms docs/*.txt [--keys rate,day_count] [--max 3]
       [--context 1] [--grep REGEX]
Prints, per file and key, the first --max matching lines with --context lines around
them and their line numbers. Matching ignores case and accents. A file with 0 chars
is a scanned PDF: open the PDF with the Read tool.
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

KEYS = {
    "isin": r"\bisin\b|\bcusip\b|common code",
    "amount": (
        r"valor nominal (ofrecido|a emitir|total|en circulacion|emitido)"
        r"|monto (de emision|a emitir|total)|aggregate principal amount"
    ),
    "issue_date": r"fecha de emision|issue date",
    "maturity": r"fecha de vencimiento|maturity date",
    "rate": (
        r"tasa de interes|tasa fija|tasa variable|margen (aplicable|de corte)"
        r"|tasa de referencia|badlar|tamar|interest rate"
    ),
    "day_count": (
        r"30/360|\b36[05] dias|base (de|para el) calculo"
        r"|dias (efectivamente )?transcurridos|day count"
    ),
    "payment_dates": r"fechas? de pago de (los )?intereses|interest payment date",
    "amortization": (
        r"amortizacion|amortizar|pagadero en una (unica )?cuota|amortization"
    ),
    "min_purchase": (
        r"denominacion(es)? minima|unidad minima de negociacion"
        r"|monto minimo de suscripcion|minimum denomination"
    ),
    "business_day": r"dia habil|dias habiles|business day",
    "currency": (
        r"moneda de (denominacion|suscripcion|pago|integracion)"
        r"|tipo de cambio aplicable|dolar (mep|cable)|dollar.linked"
    ),
    "redemption": r"rescate|redemption|cambio de control|change of control",
    "ranking": r"garantia|rango|ranking|garantizad",
    "law": r"ley aplicable|jurisdiccion|governing law",
    "rating": r"calificacion|rating",
    "result": (
        r"precio de emision|tasa (de corte|aplicable)|valor nominal a emitir"
        r"|issue price"
    ),
}
USAGE = f"{__doc__}Keys: {', '.join(KEYS)}"


def plain(s: str) -> str:
    """Return s in lower case and without accents."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)
    ).lower()


def scan(
    path: str, keys: dict[str, str], max_hits: int, context: int, width: int = 300
) -> list[str]:
    """Return the report of one file: per key, the matching lines with context."""
    text = Path(path).read_text(encoding="utf8", errors="replace")
    out = [f"== {path} ({len(text)} chars)"]
    if not text.strip():
        out.append("SCAN: no text extracted; open the PDF with the Read tool.")
        return out
    lines = text.splitlines()
    norm = [plain(line) for line in lines]
    for k, pat in keys.items():
        rx = re.compile(pat)
        hits = [i for i, line in enumerate(norm) if rx.search(line)]
        if not hits:
            out.append(f"[{k}] no match")
            continue
        out.append(
            f"[{k}] {len(hits)} matching lines"
            + (f", first {max_hits}" if len(hits) > max_hits else "")
        )
        shown, last = set(hits[:max_hits]), -1
        for i in hits[:max_hits]:
            lo = max(last + 1, i - context)
            if last >= 0 and lo > last + 1:
                out.append("    ...")
            for j in range(lo, min(len(lines), i + context + 1)):
                line = " ".join(lines[j].split())
                out.append(f"  {'>' if j in shown else ' '} L{j + 1}: {line[:width]}")
                last = j
    return out


def main(argv: list[str] | None = None) -> None:
    """Run `rueda on find-terms`."""
    p = argparse.ArgumentParser(
        prog="rueda on find-terms",
        description=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("files", nargs="+")
    p.add_argument("--keys", help="comma-separated subset of keys")
    p.add_argument("--max", type=int, default=3, help="matches shown per key and file")
    p.add_argument(
        "--context", type=int, default=1, help="lines shown before and after each match"
    )
    p.add_argument("--grep", help="extra pattern, reported as key 'grep'")
    a = p.parse_args(argv)
    keys = dict(KEYS)
    if a.keys:
        unknown = set(a.keys.split(",")) - set(KEYS)
        if unknown:
            sys.exit(f"unknown keys {sorted(unknown)}; available: {', '.join(KEYS)}")
        keys = {k: KEYS[k] for k in a.keys.split(",")}
    if a.grep:
        keys["grep"] = plain(a.grep)
    for f in a.files:
        sys.stdout.write("\n".join(scan(f, keys, a.max, a.context)) + "\n")


if __name__ == "__main__":
    main()
