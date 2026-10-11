"""Check bond identifiers before using them (stdlib only).
Usage: rueda identify <ticker|CUIT|ISIN|class> [...]
  PLC5O          ticker: base, quote currency (O pesos, D MEP, C cable), siblings, class from digits
  30-67822401-0  CUIT: check digit, company or person prefix
  USP7924AAC29   ISIN: check digit
  V, 5, XXIII    class number in Arabic and Roman form
Exit status 1 if any CUIT or ISIN fails its check digit."""
import re, sys

SUFFIX = {"O": "pesos", "D": "MEP dollars", "C": "cable dollars"}
ROMAN = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
         (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
CUIT_W = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def to_roman(n):
    out = ""
    for v, s in ROMAN:
        while n >= v:
            out, n = out + s, n - v
    return out


def from_roman(s):
    """Integer value of a canonical Roman numeral, else None."""
    s, n, i = s.upper(), 0, 0
    for v, r in ROMAN:
        while s.startswith(r, i):
            n, i = n + v, i + len(r)
    return n if i == len(s) and n and to_roman(n) == s else None


def cuit_digit(body):
    """Check digit for the first 10 CUIT digits; None if no digit is valid."""
    r = 11 - sum(int(c) * w for c, w in zip(body, CUIT_W)) % 11
    return {11: 0, 10: None}.get(r, r)


def isin_digit(body):
    """Luhn check digit over the first 11 ISIN characters (letters A=10 ... Z=35)."""
    digits = "".join(str(int(c, 36)) for c in body.upper())
    total = 0
    for i, c in enumerate(reversed(digits)):
        n = int(c) * (2 if i % 2 == 0 else 1)
        total += n - 9 if n > 9 else n
    return (10 - total % 10) % 10


def check(arg):
    """Returns (line, ok)."""
    s = arg.strip().upper()
    plain = s.replace("-", "")
    if re.fullmatch(r"\d{11}", plain):
        exp = cuit_digit(plain[:10])
        kind = "company" if plain[:2] in ("30", "33", "34") else "person" if plain[:2] in ("20", "23", "24", "27") else "unknown prefix"
        ok = exp is not None and exp == int(plain[10])
        fmt = f"{plain[:2]}-{plain[2:10]}-{plain[10]}"
        return f"{arg}\tCUIT\t{'valid' if ok else f'INVALID (expected check digit {exp})'}\t{fmt}\t{kind}", ok
    if re.fullmatch(r"[A-Z]{2}[A-Z0-9]{9}\d", s):
        exp = isin_digit(s[:11])
        ok = exp == int(s[11])
        return f"{arg}\tISIN\t{'valid' if ok else f'INVALID (expected check digit {exp})'}\tprefix {s[:2]}", ok
    cls = re.sub(r"^CLASE\s*", "", s)
    if re.fullmatch(r"\d{1,4}", cls) or from_roman(cls):
        n = int(cls) if cls.isdigit() else from_roman(cls)
        return f"{arg}\tclass\t{n}\t{to_roman(n)}", True
    if re.fullmatch(r"[A-Z0-9]{3,6}", s):
        base, cur = (s[:-1], SUFFIX[s[-1]]) if len(s) >= 5 and s[-1] in SUFFIX else (s, "unknown (no O/D/C suffix)")
        m = re.search(r"(\d+)$", base)
        cls = f"class {m.group(1)} ({to_roman(int(m.group(1)))}) if the ticker follows the class" if m else "class not in ticker"
        sib = " ".join(base + k for k in SUFFIX)
        return f"{arg}\tticker\tbase {base}\tquoted in {cur}\ttickers {sib}\t{cls}", True
    return f"{arg}\tunrecognized", True


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    results = [check(a) for a in args]
    for line, _ in results:
        print(line)
    sys.exit(0 if all(ok for _, ok in results) else 1)


if __name__ == "__main__":
    main()
