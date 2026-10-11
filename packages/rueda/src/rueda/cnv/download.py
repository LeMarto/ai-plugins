"""Download attachments of a CNV AIF publicview presentation.

Usage: rueda cnv dl <uuid> [<uuid> ...]
Saves each attachment and its extracted text (.txt) into ./docs/.
Handles PDF, ZIP (old filings: zipped .doc/.docx/.pdf), .docx and Word 97-2003 .doc
(text from the piece table). Documents embedded in a .doc (Acrobat objects, Outlook
attachments) are saved next to it as <file>.embN.<ext> and their text is appended.
A .txt with 0 chars means a scanned PDF: open the PDF with the Read tool.
Each request is tried 3 times; a UUID that still fails is reported as FAIL and the
others continue. Exit status 1 if any UUID or attachment failed.
"""

import html
import io
import json
import logging
import re
import struct
import sys
import time
import zipfile
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import IO, Any, ParamSpec, Protocol, TypeVar

import olefile
import pypdf
import requests

# font-encoding warnings do not affect the text
logging.getLogger("pypdf").setLevel(logging.ERROR)

AIF = "https://aif2.cnv.gov.ar"
BLOB = "https://blob.cnv.gov.ar/BlobWebService.svc/"
UA = {"User-Agent": "Mozilla/5.0"}
OLE = b"\xd0\xcf\x11\xe0"
MAGIC = {b"%PDF": ".pdf", b"PK\x03\x04": ".zip", OLE: ".doc"}
TRIES = 3  # attempts per request
MIN_WORDS = 2  # words that make a printable run count as text
NFIB_WORD97 = 0xC1  # lowest nFib with the Word 97 layout
CLXT_PRC, CLXT_PCDT = 1, 2  # entry types of the Clx: property modifiers, piece table

P = ParamSpec("P")
T = TypeVar("T")


class _Streams(Protocol):
    """The part of olefile.OleFileIO that `embedded` reads."""

    def listdir(self) -> list[list[str]]: ...

    def openstream(self, filename: list[str], /) -> IO[bytes]: ...


def attachments(page: str) -> list[dict[str, Any]]:
    """Return the attachment records of a publicview page, each file once."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for m in re.finditer(r'\[\{"idUploader.*?\}\]', html.unescape(page)):
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        for a in items:
            k = a.get("hash") or a["guid"]  # same file can be attached twice
            if k not in seen:
                seen.add(k)
                out.append(a)
    return out


def crude_text(data: bytes) -> str:
    """Old OLE .doc without a usable piece table: printable runs that contain words."""

    def runs(t: str, n: int) -> str:
        rs = re.findall(rf"[\x20-\x7e\xa0-\xfe\r\n\t]{{{n},}}", t)
        return "\n".join(
            r for r in rs if len(re.findall(r"[A-Za-z\xc0-\xfe]{3,}", r)) >= MIN_WORDS
        )

    a, b = runs(data.decode("latin1"), 6), runs(data.decode("utf-16le", "ignore"), 20)
    return a if len(a) > len(b) else b


def doc_text(ole: "olefile.OleFileIO[str]") -> str | None:
    """Text of a Word 97-2003 document from its piece table; None if it has none."""
    if not ole.exists("WordDocument"):
        return None
    wd = ole.openstream("WordDocument").read()
    if struct.unpack_from("<H", wd, 2)[0] < NFIB_WORD97:  # older: different layout
        return None
    table = "1Table" if struct.unpack_from("<H", wd, 0x0A)[0] & 0x0200 else "0Table"
    if not ole.exists(table):
        return None
    tb = ole.openstream(table).read()
    fc_clx, lcb_clx = struct.unpack_from(
        "<II", wd, 0x01A2
    )  # FibRgFcLcb97.fcClx / lcbClx
    clx, i = tb[fc_clx : fc_clx + lcb_clx], 0
    while i < len(clx) and clx[i] == CLXT_PRC:  # skip Prc entries
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != CLXT_PCDT:
        return None
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc, n = clx[i + 5 : i + 5 + lcb], (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc)
    out = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        length = cps[k + 1] - cps[k]
        if fc & 0x40000000:  # 8-bit text
            fc = (fc & ~0x40000000) // 2
            out.append(wd[fc : fc + length].decode("cp1252", "replace"))
        else:
            out.append(wd[fc : fc + 2 * length].decode("utf-16le", "replace"))
    t = "".join(out)
    while True:  # drop field instructions (PAGE, EMBED ...), keep field results
        t2 = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", t)
        t2 = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", t2)
        if t2 == t:
            break
        t = t2
    t = (
        t.replace("\r", "\n")
        .replace("\x07", "\t")
        .replace("\x0b", "\n")
        .replace("\x0c", "\n")
    )
    return re.sub(r"[\x00-\x08\x0e-\x1f]", "", t)


def embedded(ole: _Streams) -> Iterator[tuple[str, bytes]]:
    """Yield (stream name, bytes) of the PDF, ZIP or OLE files in the ObjectPool."""
    for path in ole.listdir():
        if path[0] != "ObjectPool":
            continue
        d = ole.openstream(path).read()
        for m in MAGIC:
            i = d.find(m, 0, 2048)
            if i >= 0:
                yield "/".join(path), d[i:]
                break


def _zip_text(data: bytes, found: list[tuple[str, bytes]] | None) -> str:
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for n in z.namelist():
            d = z.read(n)
            if n == "word/document.xml":  # .docx
                x = re.sub(r"</w:p>", "\n", d.decode("utf8", "ignore"))
                out.append(html.unescape(re.sub(r"<[^>]+>", "", x)))
            elif not n.endswith((".xml", ".rels", "/")):
                out.append(totext(d, found))
    return "\n".join(out)


def _ole_text(data: bytes, found: list[tuple[str, bytes]] | None) -> str:
    # olefile and the piece-table parser raise anything on a damaged filing: each
    # step falls back to the printable runs or reports the part it could not read
    try:
        ole: olefile.OleFileIO[str] = olefile.OleFileIO(io.BytesIO(data))
    except Exception:  # noqa: BLE001
        return crude_text(data)
    try:
        t = doc_text(ole)
    except Exception:  # noqa: BLE001
        t = None
    parts = [crude_text(data) if t is None else t]
    for name, blob in embedded(ole):
        if found is not None:
            found.append((name, blob))
        try:
            parts.append(f"\n[embedded {name}]\n" + totext(blob, found))
        except Exception as e:  # noqa: BLE001
            parts.append(f"\n[embedded {name}: text extraction failed: {e}]")
    return "\n".join(parts)


def totext(data: bytes, found: list[tuple[str, bytes]] | None = None) -> str:
    """Text of a PDF, ZIP, .docx or .doc.

    Embedded documents are appended to found as (name, bytes).
    """
    if data[:4] == b"%PDF":
        return "\n".join(
            p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages
        )
    if data[:2] == b"PK":
        return _zip_text(data, found)
    if data[:4] == OLE:
        return _ole_text(data, found)
    return crude_text(data)


def retry(fn: Callable[P, T], *args: P.args, **kw: P.kwargs) -> T:
    """Call fn, trying again after a connection error or a timeout."""
    for k in range(TRIES - 1):
        try:
            return fn(*args, **kw)
        except (requests.ConnectionError, requests.Timeout):
            time.sleep(3 * (k + 1))
    return fn(*args, **kw)


def _is_file(r: requests.Response) -> bool:
    return r.ok and (r.content[:4] in (b"%PDF", OLE) or r.content[:2] == b"PK")


def _blob(s: requests.Session, guid: str, tok: str | None) -> requests.Response:
    # the download of one attachment, asked with the CSRF token and then without
    key = retry(
        s.get,
        f"{AIF}/api/ValetKeyProvider/GetPublicValetKey/{guid}",
        params={"operation": "DownloadBlob"},
        timeout=30,
    ).json()["valetKeyData"]

    def post(hdr: dict[str, str]) -> requests.Response:
        return retry(
            s.post,
            f"{BLOB}DownloadBlob/{guid}",
            data={"ValetKey": key},
            headers=hdr,
            timeout=60,
        )

    r = post({"X-CSRF-TOKEN": tok} if tok else {})
    return r if _is_file(r) else post({})


def download(uuid: str, outdir: str = "docs") -> tuple[list[str], int]:
    """Save the attachments of one presentation.

    Returns (saved paths, failed count).
    """
    out = sys.stdout.write
    Path(outdir).mkdir(parents=True, exist_ok=True)
    s = requests.Session()
    s.headers.update(UA)
    page = retry(s.get, f"{AIF}/presentations/publicview/{uuid}", timeout=30).text
    m = re.search(
        r'id="RequestVerificationToken"[^>]*value="([^"]+)"', page
    ) or re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page)
    tok = m.group(1) if m else None
    saved: list[str] = []
    failed = 0
    atts = attachments(page)
    if not atts:
        out(f"FAIL {uuid}: no attachments in the publicview page (check the UUID)\n")
        return saved, 1
    for a in atts:
        guid, name = a["guid"], a["nombreArchivo"]
        try:
            r = _blob(s, guid, tok)
        except (requests.RequestException, KeyError, TypeError) as e:
            out(f"FAIL {uuid} {name}: {e}\n")
            failed += 1
            continue
        if not _is_file(r):
            out(f"FAIL {uuid} {name}: {r.status_code} {r.content[:200]!r}\n")
            failed += 1
            continue
        data = r.content
        path = Path(outdir) / f"{uuid[:8]}_{name}"
        path.write_bytes(data)
        found: list[tuple[str, bytes]] = []
        try:
            txt = totext(data, found)
        except Exception as e:  # noqa: BLE001
            # pypdf raises anything on a damaged file: keep the file, without text
            txt = ""
            out(f"WARN {path}: text extraction failed: {e}\n")
        Path(f"{path}.txt").write_text(txt)
        out(f"OK {path} ({len(data)} bytes, {len(txt)} chars)\n")
        saved.append(str(path))
        for i, (ename, blob) in enumerate(found, 1):
            ext = next(e for magic, e in MAGIC.items() if blob.startswith(magic))
            epath = f"{path}.emb{i}{ext}"
            Path(epath).write_bytes(blob)
            size = len(blob)
            out(f"OK {epath} (embedded {ename}, {size} bytes; text included above)\n")
    return saved, failed


def main(argv: list[str] | None = None) -> None:
    """Run `rueda cnv dl`."""
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    bad = 0
    for u in args:
        try:
            bad += download(u)[1]
        except Exception as e:  # noqa: BLE001
            # whatever fails for one UUID is reported and the others continue
            sys.stdout.write(f"FAIL {u}: {e}\n")
            bad += 1
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
