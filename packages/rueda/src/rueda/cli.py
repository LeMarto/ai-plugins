"""Tools for Argentine market instruments.
Usage: rueda <command> [args]
  identify          check a ticker, CUIT, ISIN or class number
  holidays          bank holidays, AR or US
  cnv list          documents on an issuer's CNV company page
  cnv dl            attachments of a CNV publicview presentation, with their text
  sec 20f           an issuer's 20-F filings from SEC EDGAR, with the debt sections
  on find-terms     term passages in extracted document text
  on terms-example  an example terms.json
  on schedule       payment schedule of an ON from terms.json
  on tir            yield, duration and parity from terms.json and a price
`rueda <command> -h` prints the command's usage."""
import importlib, sys

COMMANDS = {
    ("identify",): "rueda.identify:main",
    ("holidays",): "rueda.holidays:main",
    ("cnv", "list"): "rueda.cnv.listing:main",
    ("cnv", "dl"): "rueda.cnv.download:main",
    ("sec", "20f"): "rueda.sec.form20f:main",
    ("on", "find-terms"): "rueda.on.find_terms:main",
    ("on", "terms-example"): "rueda.on.schedule:example",
    ("on", "schedule"): "rueda.on.schedule:main",
    ("on", "tir"): "rueda.on.tir:main",
}


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    for n in (2, 1):
        target = COMMANDS.get(tuple(args[:n]))
        if target:
            module, fn = target.split(":")  # imported here so a command loads only its own dependencies
            return getattr(importlib.import_module(module), fn)(args[n:])
    sys.exit(__doc__)


if __name__ == "__main__":
    main()
