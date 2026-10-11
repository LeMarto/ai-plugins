"""Locate term passages in extracted document text (the .txt files from `rueda cnv dl`).
Usage: rueda on find-terms docs/*.txt [--keys rate,day_count] [--max 3] [--context 1] [--grep REGEX]
Prints, per file and key, the first --max matching lines with --context lines around
them and their line numbers. Matching ignores case and accents. A file with 0 chars
is a scanned PDF: open the PDF with the Read tool.
Keys: """
import argparse, re, sys, unicodedata

KEYS = {
    "isin": r"\bisin\b|\bcusip\b|common code",
    "amount": r"valor nominal (ofrecido|a emitir|total|en circulacion|emitido)|monto (de emision|a emitir|total)|aggregate principal amount",
    "issue_date": r"fecha de emision|issue date",
    "maturity": r"fecha de vencimiento|maturity date",
    "rate": r"tasa de interes|tasa fija|tasa variable|margen (aplicable|de corte)|tasa de referencia|badlar|tamar|interest rate",
    "day_count": r"30/360|\b36[05] dias|base (de|para el) calculo|dias (efectivamente )?transcurridos|day count",
    "payment_dates": r"fechas? de pago de (los )?intereses|interest payment date",
    "amortization": r"amortizacion|amortizar|pagadero en una (unica )?cuota|amortization",
    "min_purchase": r"denominacion(es)? minima|unidad minima de negociacion|monto minimo de suscripcion|minimum denomination",
    "business_day": r"dia habil|dias habiles|business day",
    "currency": r"moneda de (denominacion|suscripcion|pago|integracion)|tipo de cambio aplicable|dolar (mep|cable)|dollar.linked",
    "redemption": r"rescate|redemption|cambio de control|change of control",
    "ranking": r"garantia|rango|ranking|garantizad",
    "law": r"ley aplicable|jurisdiccion|governing law",
    "rating": r"calificacion|rating",
    "result": r"precio de emision|tasa (de corte|aplicable)|valor nominal a emitir|issue price",
}
__doc__ += ", ".join(KEYS)


def plain(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def scan(path, keys, max_hits, context, width=300):
    text = open(path, encoding="utf8", errors="replace").read()
    out = [f"== {path} ({len(text)} chars)"]
    if not text.strip():
        out.append("SCAN: no text extracted; open the PDF with the Read tool.")
        return out
    lines = text.splitlines()
    norm = [plain(l) for l in lines]
    for k, pat in keys.items():
        rx = re.compile(pat)
        hits = [i for i, l in enumerate(norm) if rx.search(l)]
        if not hits:
            out.append(f"[{k}] no match")
            continue
        out.append(f"[{k}] {len(hits)} matching lines" + (f", first {max_hits}" if len(hits) > max_hits else ""))
        shown, last = set(hits[:max_hits]), -1
        for i in hits[:max_hits]:
            lo = max(last + 1, i - context)
            if last >= 0 and lo > last + 1:
                out.append("    ...")
            for j in range(lo, min(len(lines), i + context + 1)):
                l = " ".join(lines[j].split())
                out.append(f"  {'>' if j in shown else ' '} L{j + 1}: {l[:width]}")
                last = j
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="rueda on find-terms", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("files", nargs="+")
    p.add_argument("--keys", help="comma-separated subset of keys")
    p.add_argument("--max", type=int, default=3, help="matches shown per key and file")
    p.add_argument("--context", type=int, default=1, help="lines shown before and after each match")
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
        print("\n".join(scan(f, keys, a.max, a.context)))


if __name__ == "__main__":
    main()
