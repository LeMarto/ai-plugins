"""Download an issuer's 20-F filings from SEC EDGAR and extract the debt sections (stdlib only).
Usage: rueda sec 20f <CIK|NYSE ticker> [--from YEAR] [--to YEAR] [--ua "name email"]
Lists every 20-F and 20-F/A (including the older filings.files pages), saves each
document's text to ./sec/ and, next to it, an _extract.txt with Item 13 (Defaults,
Dividend Arrearages and Delinquencies), the Item 5 indebtedness subsections and the
lines mentioning defaults, restructurings or exchange offers.
Prints one TSV line per filing: filing date, form, report date, URL, chars, Item 13
chars, indebtedness subsections, default-related lines. Filings before 2002 are on paper.
SEC requires a User-Agent with a contact; --ua or SEC_USER_AGENT overrides the default."""
import argparse, html, json, os, re, sys, time, urllib.request
from html.parser import HTMLParser

UA = os.environ.get("SEC_USER_AGENT", "argentina-on-factsheet research@example.com")
SUBS = "https://data.sec.gov/submissions/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc}"
FULL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_dashes}.txt"
FORMS = {"20-F", "20-F/A"}
SEP = r"\s*[.\-–—:]?\s*"
ITEM13 = re.compile(rf"item\s*13{SEP}defaults", re.I)
ITEM14 = re.compile(rf"item\s*14{SEP}material", re.I)
ITEM5 = re.compile(rf"item\s*5{SEP}operating", re.I)
ITEM6 = re.compile(rf"item\s*6{SEP}directors", re.I)
DEBT_HEAD = re.compile(r"^\s*(our\s+)?(indebtedness|financial debt|debt)\b[^.]{0,60}$", re.I | re.M)
DEFAULT = re.compile(r"\bdefault(s|ed)?\b|restructur|exchange offer|suspen\w* (the )?payment|"
                     r"(did not|failed to|unable to) (pay|make)|\bunpaid\b|arrear|\bwaiver", re.I)
BLOCK = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "table", "pre"}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts, self.skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if tag in BLOCK or tag in ("td", "th"):
            self.parts.append("\n" if tag in BLOCK else " ")

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def to_text(raw):
    if re.search(r"<(html|body|p|div|table)\b", raw[:20000], re.I):
        p = _Text()
        p.feed(raw)
        raw = "".join(p.parts)
    else:
        raw = html.unescape(re.sub(r"<[^>]+>", " ", raw))
    lines = (" ".join(l.split()) for l in raw.replace("\xa0", " ").splitlines())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines))


def get(url, ua):
    time.sleep(0.15)  # SEC fair-access limit is 10 requests per second
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Encoding": "identity"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf8", "replace")


def resolve_cik(arg, ua):
    if arg.isdigit():
        return int(arg)
    data = json.loads(get("https://www.sec.gov/files/company_tickers.json", ua))
    for row in data.values():
        if row["ticker"].upper() == arg.upper():
            return int(row["cik_str"])
    sys.exit(f"ticker {arg} not in SEC company_tickers.json; pass the CIK")


def filings(cik, ua):
    """Every filing of the forms in FORMS: dicts with form, filingDate, reportDate, accessionNumber, primaryDocument."""
    sub = json.loads(get(SUBS.format(name=f"CIK{cik:010d}.json"), ua))
    pages = [sub["filings"]["recent"]] + [json.loads(get(SUBS.format(name=f["name"]), ua))
                                          for f in sub["filings"].get("files", [])]
    out = []
    for pg in pages:
        keys = ["form", "filingDate", "reportDate", "accessionNumber", "primaryDocument"]
        for row in zip(*(pg.get(k, [""] * len(pg["form"])) for k in keys)):
            if row[0] in FORMS:
                out.append(dict(zip(keys, row)))
    return sorted(out, key=lambda f: f["filingDate"]), sub.get("name", "")


def longest(text, start, end):
    """Longest span from a start match to the next end match (skips the table of contents)."""
    best = ""
    for m in start.finditer(text):
        e = end.search(text, m.end())
        seg = text[m.start(): e.start() if e else m.start() + 20000]
        if len(seg) > len(best):
            best = seg
    return best


def extract(text, debt_chars=8000, max_hits=40):
    item13 = longest(text, ITEM13, ITEM14)
    item5 = longest(text, ITEM5, ITEM6)
    debt = [item5[m.start(): m.start() + debt_chars] for m in DEBT_HEAD.finditer(item5)]
    lines = text.splitlines()
    hits = [i for i, l in enumerate(lines) if DEFAULT.search(l)]
    ctx = ["\n".join(lines[max(0, i - 1): i + 2]) for i in hits[:max_hits]]
    return item13, debt, hits, ctx


def main(argv=None):
    p = argparse.ArgumentParser(prog="rueda sec 20f", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("issuer", help="CIK or ticker")
    p.add_argument("--from", dest="y0", type=int, default=2002)
    p.add_argument("--to", dest="y1", type=int, default=9999)
    p.add_argument("--ua", default=UA)
    p.add_argument("--out", default="sec")
    a = p.parse_args(argv)
    cik = resolve_cik(a.issuer, a.ua)
    fs, name = filings(cik, a.ua)
    print(f"# CIK {cik} {name}: {len(fs)} 20-F filings in EDGAR", file=sys.stderr)
    os.makedirs(a.out, exist_ok=True)
    for f in fs:
        if not a.y0 <= int(f["filingDate"][:4]) <= a.y1:
            continue
        acc = f["accessionNumber"]
        if f["primaryDocument"].endswith(".paper"):
            print("\t".join([f["filingDate"], f["form"], f["reportDate"], "paper filing, not in EDGAR"]))
            continue
        url = (ARCHIVE.format(cik=cik, acc=acc.replace("-", ""), doc=f["primaryDocument"]) if f["primaryDocument"]
               else FULL.format(cik=cik, acc_dashes=acc))
        try:
            text = to_text(get(url, a.ua))
        except Exception as e:
            print(f"FAIL {f['filingDate']} {url}: {e}", file=sys.stderr)
            continue
        base = os.path.join(a.out, f"{cik}_{f['filingDate']}_{f['form'].replace('/', '')}")
        open(base + ".txt", "w").write(text)
        item13, debt, hits, ctx = extract(text)
        with open(base + "_extract.txt", "w") as fh:
            fh.write(f"{f['form']} filed {f['filingDate']} for {f['reportDate']}\n{url}\n\n")
            fh.write("== ITEM 13\n" + (item13 or "not found") + "\n\n")
            for i, dsec in enumerate(debt, 1):
                fh.write(f"== ITEM 5 INDEBTEDNESS {i}\n{dsec}\n\n")
            fh.write(f"== DEFAULT-RELATED LINES ({len(hits)}, first {len(ctx)})\n" + "\n--\n".join(ctx) + "\n")
        print("\t".join([f["filingDate"], f["form"], f["reportDate"], url, str(len(text)),
                         str(len(item13)), str(len(debt)), str(len(hits))]))


if __name__ == "__main__":
    main()
