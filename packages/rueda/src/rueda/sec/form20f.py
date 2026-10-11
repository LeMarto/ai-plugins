"""Download an issuer's 20-F filings from SEC EDGAR and extract the debt sections.

Usage: rueda sec 20f <CIK|NYSE ticker> [--from YEAR] [--to YEAR] [--ua "name email"]
Lists every 20-F and 20-F/A (including the older filings.files pages), saves each
document's text to ./sec/ and, next to it, an _extract.txt with Item 13 (Defaults,
Dividend Arrearages and Delinquencies), the Item 5 indebtedness subsections and the
lines mentioning defaults, restructurings or exchange offers.
Prints one TSV line per filing: filing date, form, report date, URL, chars, Item 13
chars, indebtedness subsections, default-related lines. Filings before 2002 are on
paper.
SEC requires a User-Agent with a contact; --ua or SEC_USER_AGENT overrides the
default. Stdlib only.
"""

import argparse
import html
import json
import os
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

UA = os.environ.get("SEC_USER_AGENT", "argentina-on-factsheet research@example.com")
SUBS = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FULL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_dashes}.txt"
FORMS = {"20-F", "20-F/A"}
SEP = r"\s*[.\-\u2013\u2014:]?\s*"  # en and em dashes
ITEM13 = re.compile(rf"item\s*13{SEP}defaults", re.IGNORECASE)
ITEM14 = re.compile(rf"item\s*14{SEP}material", re.IGNORECASE)
ITEM5 = re.compile(rf"item\s*5{SEP}operating", re.IGNORECASE)
ITEM6 = re.compile(rf"item\s*6{SEP}directors", re.IGNORECASE)
DEBT_HEAD = re.compile(
    r"^\s*(our\s+)?(indebtedness|financial debt|debt)\b[^.]{0,60}$",
    re.IGNORECASE | re.MULTILINE,
)
DEFAULT = re.compile(
    r"\bdefault(s|ed)?\b|restructur|exchange offer|suspen\w* (the )?payment|"
    r"(did not|failed to|unable to) (pay|make)|\bunpaid\b|arrear|\bwaiver",
    re.IGNORECASE,
)
BLOCK = {
    "p",
    "div",
    "br",
    "tr",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "table",
    "pre",
}
KEYS = ["form", "filingDate", "reportDate", "accessionNumber", "primaryDocument"]


class _Text(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag: str, _attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.skip += 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self.skip -= 1
        if tag in BLOCK or tag in ("td", "th"):
            self.parts.append("\n" if tag in BLOCK else " ")

    def handle_data(self, data: str) -> None:
        if not self.skip:
            self.parts.append(data)


def to_text(raw: str) -> str:
    """Return the text of an HTML or plain-text filing, one block per line."""
    if re.search(r"<(html|body|p|div|table)\b", raw[:20000], re.IGNORECASE):
        p = _Text()
        p.feed(raw)
        raw = "".join(p.parts)
    else:
        raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = (" ".join(line.split()) for line in raw.replace("\xa0", " ").splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def get(url: str, ua: str) -> str:
    """Return the body of an SEC URL, pausing first as its fair-access rule asks."""
    time.sleep(0.15)  # SEC fair-access limit is 10 requests per second
    # S310: every URL is built from the https constants above
    req = urllib.request.Request(  # noqa: S310
        url, headers={"User-Agent": ua, "Accept-Encoding": "identity"}
    )
    with urllib.request.urlopen(req, timeout=60) as r:  # noqa: S310
        body: bytes = r.read()
    return body.decode("utf8", "replace")


def resolve_cik(arg: str, ua: str) -> int:
    """Return the CIK for a CIK or an NYSE ticker."""
    if arg.isdigit():
        return int(arg)
    data = json.loads(get("https://www.sec.gov/files/company_tickers.json", ua))
    for row in data.values():
        if row["ticker"].upper() == arg.upper():
            return int(row["cik_str"])
    sys.exit(f"ticker {arg} not in SEC company_tickers.json; pass the CIK")


def filings(cik: int, ua: str) -> tuple[list[dict[str, str]], str]:
    """Every filing of the forms in FORMS, oldest first, and the issuer's name.

    Each filing is a dict with the fields in KEYS.
    """
    sub = json.loads(get(SUBS.format(name=f"CIK{cik:010d}.json"), ua))
    pages = [sub["filings"]["recent"]] + [
        json.loads(get(SUBS.format(name=f["name"]), ua))
        for f in sub["filings"].get("files", [])
    ]
    out: list[dict[str, str]] = []
    for pg in pages:
        cols = (pg.get(k, [""] * len(pg["form"])) for k in KEYS)
        out.extend(
            dict(zip(KEYS, row, strict=True))
            for row in zip(*cols, strict=False)
            if row[0] in FORMS
        )
    return sorted(out, key=lambda f: f["filingDate"]), sub.get("name", "")


def longest(text: str, start: re.Pattern[str], end: re.Pattern[str]) -> str:
    """Longest span from a start match to the next end match.

    Taking the longest skips the table of contents.
    """
    best = ""
    for m in start.finditer(text):
        e = end.search(text, m.end())
        seg = text[m.start() : e.start() if e else m.start() + 20000]
        if len(seg) > len(best):
            best = seg
    return best


def extract(
    text: str, debt_chars: int = 8000, max_hits: int = 40
) -> tuple[str, list[str], list[int], list[str]]:
    """Pull the debt passages out of a 20-F.

    Returns (Item 13, Item 5 indebtedness subsections, indexes of the lines that
    mention a default, the first of those lines with their context).
    """
    item13 = longest(text, ITEM13, ITEM14)
    item5 = longest(text, ITEM5, ITEM6)
    debt = [
        item5[m.start() : m.start() + debt_chars] for m in DEBT_HEAD.finditer(item5)
    ]
    lines = text.splitlines()
    hits = [i for i, line in enumerate(lines) if DEFAULT.search(line)]
    ctx = ["\n".join(lines[max(0, i - 1) : i + 2]) for i in hits[:max_hits]]
    return item13, debt, hits, ctx


def main(argv: list[str] | None = None) -> None:
    """Run `rueda sec 20f`."""
    p = argparse.ArgumentParser(
        prog="rueda sec 20f",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("issuer", help="CIK or ticker")
    p.add_argument("--from", dest="y0", type=int, default=2002)
    p.add_argument("--to", dest="y1", type=int, default=9999)
    p.add_argument("--ua", default=UA)
    p.add_argument("--out", default="sec")
    a = p.parse_args(argv)
    cik = resolve_cik(a.issuer, a.ua)
    fs, name = filings(cik, a.ua)
    sys.stderr.write(f"# CIK {cik} {name}: {len(fs)} 20-F filings in EDGAR\n")
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in fs:
        if not a.y0 <= int(f["filingDate"][:4]) <= a.y1:
            continue
        acc = f["accessionNumber"]
        row = [f["filingDate"], f["form"], f["reportDate"]]
        if f["primaryDocument"].endswith(".paper"):
            sys.stdout.write("\t".join([*row, "paper filing, not in EDGAR"]) + "\n")
            continue
        url = (
            ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=f["primaryDocument"])
            if f["primaryDocument"]
            else FULL.format(cik=cik, acc_dashes=acc)
        )
        try:
            text = to_text(get(url, a.ua))
        except Exception as e:  # noqa: BLE001
            # whatever fails for one filing is reported and the others continue
            sys.stderr.write(f"FAIL {f['filingDate']} {url}: {e}\n")
            continue
        base = out_dir / f"{cik}_{f['filingDate']}_{f['form'].replace('/', '')}"
        Path(f"{base}.txt").write_text(text)
        item13, debt, hits, ctx = extract(text)
        with Path(f"{base}_extract.txt").open("w") as fh:
            fh.write(
                f"{f['form']} filed {f['filingDate']} for {f['reportDate']}\n{url}\n\n"
            )
            fh.write("== ITEM 13\n" + (item13 or "not found") + "\n\n")
            fh.writelines(
                f"== ITEM 5 INDEBTEDNESS {i}\n{dsec}\n\n"
                for i, dsec in enumerate(debt, 1)
            )
            fh.write(
                f"== DEFAULT-RELATED LINES ({len(hits)}, first {len(ctx)})\n"
                + "\n--\n".join(ctx)
                + "\n"
            )
        counts = [len(text), len(item13), len(debt), len(hits)]
        sys.stdout.write("\t".join([*row, url, *map(str, counts)]) + "\n")


if __name__ == "__main__":
    main()
