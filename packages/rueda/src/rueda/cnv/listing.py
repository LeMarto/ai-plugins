"""List documents on an issuer's CNV company page, one year per request.
Usage: rueda cnv list <CUIT> <year_from> [<year_to>] [--grep REGEX] [--preset NAME] [--class N]
Prints one TSV line per document, newest first: date (YYYY-MM-DD), time, document no.,
publicview uuid, title, section path on the page (several joined by " | ").
--grep keeps documents whose title or section matches REGEX (case-insensitive), e.g. "CANJE|CLASE XXIII".
--preset adds a stored pattern: issuance (suplementos, avisos de suscripción/resultado/complementarios,
  adendas, prospectos, Art. 10 LON), payments (avisos de pago and exchange-rate notices),
  credit (step 5c), management (step 5d).
--class N keeps titles naming class N in Arabic or Roman numerals (5 matches "CLASE 5" and "CLASE V").
Filters combine with AND. Years are fetched in parallel; a year that times out is reported on stderr."""
import re, sys, html
from concurrent.futures import ThreadPoolExecutor

import requests

from rueda.identify import from_roman, to_roman

URL = "https://www.cnv.gov.ar/SitioWeb/Empresas/Empresa/{cuit}?fdesde=1/1/{y}&fhasta=31/12/{y}"
TOK = re.compile(r'<div\b([^>]*)>|</div>|<h4 class="panel-title">.*?<strong>(.*?)</strong>|<tr>(.*?)</tr>', re.S)
CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
UUID = re.compile(r"publicview/([0-9a-fA-F-]{36})")
MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7, "ago": 8,
          "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12}
LATEST = "Última Información Recibida"  # repeats documents listed in their own section
PRESETS = {
    "issuance": r"SUPLEMENTO|AVISO DE SUSCRIPCI|AVISO DE RESULTADO|AVISO COMPLEMENTARIO|ADENDA|PROSPECTO|ART\. 10 LON",
    "payments": r"AVISO DE PAGO|TIPO DE CAMBIO",
    "credit": r"CANJE|REESTRUCTUR|CONSENTIMIENTO|RESCATE|INCUMPL|PR[OÓ]RROGA|ASAMBLEA.*(ON|OBLIG)|HECHO RELEVANTE",
    "management": r"AUTORIDADES|GERENTE|DESIGNACI|RENUNCIA|DESVINCULACI|CEO|CFO",
}


def text(s):
    return html.unescape(re.sub(r"<[^>]+>|\s+", " ", s)).strip()


def iso(s):
    m = re.match(r"(\d{1,2})\s+([a-zé]+)\.?\s+(\d{4})", s.lower())
    if m and m.group(2)[:3] in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)[:3]]:02d}-{int(m.group(1)):02d}"
    return s


def class_pattern(n):
    """Regex for 'CLASE n' in Arabic or Roman numerals, e.g. 5 -> CLASE 5, CLASE Nº 05, CLASE V."""
    k =int(n) if str(n).isdigit() else from_roman(str(n))
    if not k:
        raise SystemExit(f"--class {n!r} is not a number or Roman numeral")
    return re.compile(rf"CLASE\s*(?:N\s*[°º.]?\s*|NRO\.?\s*)?(?:0*{k}|{to_roman(k)})\b", re.I)


def parse(page):
    """Rows of the results block, each with the path of panel headings that contain it."""
    i = page.find('id="result1"')
    page = page[i:] if i >= 0 else page
    depth, stack, rows = 0, [], []
    for m in TOK.finditer(page):
        tok = m.group(0)
        if tok.startswith("<div"):
            depth += 1
            if re.search(r'class="panel"', m.group(1)):
                stack.append([depth, ""])
        elif tok == "</div>":
            if stack and stack[-1][0] == depth:
                stack.pop()
            depth -= 1
        elif m.group(2) is not None:
            if stack:
                stack[-1][1] = text(m.group(2))
        else:
            u = UUID.search(m.group(3))
            cells = [text(c) for c in CELL.findall(m.group(3))]
            if u and len(cells) >= 4:
                section = " > ".join(name for _, name in stack if name)
                rows.append((iso(cells[0]), cells[1], cells[3], u.group(1), cells[2], section))
    return rows


def merge(rows):
    """One row per uuid; sections joined, the 'latest' panel dropped when the document has its own."""
    docs = {}
    for r in rows:
        d = docs.setdefault(r[3], [r[:5], []])
        if r[5] and r[5] not in d[1]:
            d[1].append(r[5])
    out = []
    for base, secs in docs.values():
        own = [s for s in secs if s != LATEST] or secs
        out.append(base + (" | ".join(own),))
    return sorted(out, key=lambda r: (r[0], r[1]), reverse=True)


def year(cuit, y):
    try:
        page = requests.get(URL.format(cuit=cuit, y=y), timeout=180,
                            headers={"User-Agent": "Mozilla/5.0"}).text
    except requests.RequestException as e:
        print(f"FAIL {y}: {e}", file=sys.stderr)
        return []
    return parse(page)


def keep(r, pats, cls):
    return all(p.search(r[4] + " " + r[5]) for p in pats) and (not cls or cls.search(r[4]))


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    pats, cls = [], None
    for flag in ("--grep", "--preset", "--class"):
        while flag in args:
            i = args.index(flag)
            v = args[i + 1]
            del args[i:i + 2]
            if flag == "--grep":
                pats.append(re.compile(v, re.I))
            elif flag == "--preset":
                if v not in PRESETS:
                    sys.exit(f"unknown preset {v!r}; available: {', '.join(PRESETS)}")
                pats.append(re.compile(PRESETS[v], re.I))
            else:
                cls = class_pattern(v)
    if len(args) < 2 or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    cuit = args[0].replace("-", "")
    y0 = int(args[1]); y1 = int(args[2]) if len(args) > 2 else y0
    with ThreadPoolExecutor(6) as ex:
        rows = [r for rs in ex.map(lambda y: year(cuit, y), range(y1, y0 - 1, -1)) for r in rs]
    for r in merge(rows):
        if keep(r, pats, cls):
            print("\t".join(r))


if __name__ == "__main__":
    main()
