"""Download attachments of a CNV AIF publicview presentation.
Usage: rueda cnv dl <uuid> [<uuid> ...]
Saves each attachment and its extracted text (.txt) into ./docs/.
Handles PDF, ZIP (old filings: zipped .doc/.docx/.pdf), .docx and Word 97-2003 .doc
(text from the piece table). Documents embedded in a .doc (Acrobat objects, Outlook
attachments) are saved next to it as <file>.embN.<ext> and their text is appended.
A .txt with 0 chars means a scanned PDF: open the PDF with the Read tool.
Each request is tried 3 times; a UUID that still fails is reported as FAIL and the
others continue. Exit status 1 if any UUID or attachment failed."""
import html, io, json, logging, os, re, struct, sys, time, zipfile

import olefile, pypdf, requests

logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings do not affect the text

AIF = "https://aif2.cnv.gov.ar"
BLOB = "https://blob.cnv.gov.ar/BlobWebService.svc/"
UA = {"User-Agent": "Mozilla/5.0"}
OLE = b"\xd0\xcf\x11\xe0"
MAGIC = {b"%PDF": ".pdf", b"PK\x03\x04": ".zip", OLE: ".doc"}


def attachments(page):
    out, seen = [], set()
    for m in re.finditer(r'\[\{"idUploader.*?\}\]', html.unescape(page)):
        try:
            items = json.loads(m.group(0))
        except json.JSONDecodeError:
            continue
        for a in items:
            k = a.get("hash") or a["guid"]  # same file can be attached twice
            if k not in seen:
                seen.add(k); out.append(a)
    return out


def crude_text(data):
    """Old OLE .doc without a usable piece table: printable runs that contain words."""
    def runs(t, n):
        rs = re.findall(r"[\x20-\x7e\xa0-\xfe\r\n\t]{%d,}" % n, t)
        return "\n".join(r for r in rs if len(re.findall(r"[A-Za-z\xc0-\xfe]{3,}", r)) >= 2)
    a, b = runs(data.decode("latin1"), 6), runs(data.decode("utf-16le", "ignore"), 20)
    return a if len(a) > len(b) else b


def doc_text(ole):
    """Text of a Word 97-2003 document from its piece table; None if it has none."""
    if not ole.exists("WordDocument"):
        return None
    wd = ole.openstream("WordDocument").read()
    if struct.unpack_from("<H", wd, 2)[0] < 0xC1:  # nFib below Word 97: different layout
        return None
    table = "1Table" if struct.unpack_from("<H", wd, 0x0A)[0] & 0x0200 else "0Table"
    if not ole.exists(table):
        return None
    tb = ole.openstream(table).read()
    fc_clx, lcb_clx = struct.unpack_from("<II", wd, 0x01A2)  # FibRgFcLcb97.fcClx / lcbClx
    clx, i = tb[fc_clx:fc_clx + lcb_clx], 0
    while i < len(clx) and clx[i] == 1:  # skip Prc entries
        i += 3 + struct.unpack_from("<H", clx, i + 1)[0]
    if i >= len(clx) or clx[i] != 2:
        return None
    lcb = struct.unpack_from("<I", clx, i + 1)[0]
    plc, n = clx[i + 5:i + 5 + lcb], (lcb - 4) // 12
    cps = struct.unpack_from(f"<{n + 1}I", plc)
    out = []
    for k in range(n):
        fc = struct.unpack_from("<I", plc, 4 * (n + 1) + 8 * k + 2)[0]
        length = cps[k + 1] - cps[k]
        if fc & 0x40000000:  # 8-bit text
            fc = (fc & ~0x40000000) // 2
            out.append(wd[fc:fc + length].decode("cp1252", "replace"))
        else:
            out.append(wd[fc:fc + 2 * length].decode("utf-16le", "replace"))
    t = "".join(out)
    while True:  # drop field instructions (PAGE, EMBED ...), keep field results
        t2 = re.sub(r"\x13[^\x13\x14\x15]*\x14", "", t)
        t2 = re.sub(r"\x13[^\x13\x14\x15]*\x15", "", t2)
        if t2 == t:
            break
        t = t2
    t = t.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n").replace("\x0c", "\n")
    return re.sub(r"[\x00-\x08\x0e-\x1f]", "", t)


def embedded(ole):
    """(stream name, bytes) of PDF, ZIP or OLE files stored in the document's ObjectPool."""
    for path in ole.listdir():
        if path[0] != "ObjectPool":
            continue
        d = ole.openstream(path).read()
        for m in MAGIC:
            i = d.find(m, 0, 2048)
            if i >= 0:
                yield "/".join(path), d[i:]
                break


def totext(data, found=None):
    """Text of a PDF, ZIP, .docx or .doc. Embedded documents are appended to found as (name, bytes)."""
    if data[:4] == b"%PDF":
        return "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(io.BytesIO(data)).pages)
    if data[:2] == b"PK":
        z, out = zipfile.ZipFile(io.BytesIO(data)), []
        for n in z.namelist():
            d = z.read(n)
            if n == "word/document.xml":  # .docx
                x = re.sub(r"</w:p>", "\n", d.decode("utf8", "ignore"))
                out.append(html.unescape(re.sub(r"<[^>]+>", "", x)))
            elif not n.endswith((".xml", ".rels", "/")):
                out.append(totext(d, found))
        return "\n".join(out)
    if data[:4] == OLE:
        try:
            ole = olefile.OleFileIO(io.BytesIO(data))
        except Exception:
            return crude_text(data)
        try:
            t = doc_text(ole)
        except Exception:
            t = None
        parts = [crude_text(data) if t is None else t]
        for name, blob in embedded(ole):
            if found is not None:
                found.append((name, blob))
            try:
                parts.append(f"\n[embedded {name}]\n" + totext(blob, found))
            except Exception as e:
                parts.append(f"\n[embedded {name}: text extraction failed: {e}]")
        return "\n".join(parts)
    return crude_text(data)


def retry(fn, *args, tries=3, **kw):
    for k in range(tries):
        try:
            return fn(*args, **kw)
        except (requests.ConnectionError, requests.Timeout):
            if k == tries - 1:
                raise
            time.sleep(3 * (k + 1))


def download(uuid, outdir="docs"):
    """Saves the attachments of one presentation. Returns (saved paths, failed count)."""
    os.makedirs(outdir, exist_ok=True)
    s = requests.Session(); s.headers.update(UA)
    page = retry(s.get, f"{AIF}/presentations/publicview/{uuid}", timeout=30).text
    tok = re.search(r'id="RequestVerificationToken"[^>]*value="([^"]+)"', page) or \
          re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"', page)
    tok = tok.group(1) if tok else None
    saved, failed = [], 0
    atts = attachments(page)
    if not atts:
        print(f"FAIL {uuid}: no attachments in the publicview page (check the UUID)")
        return saved, 1
    for a in atts:
        guid, name = a["guid"], a["nombreArchivo"]
        try:
            key = retry(s.get, f"{AIF}/api/ValetKeyProvider/GetPublicValetKey/{guid}",
                        params={"operation": "DownloadBlob"}, timeout=30).json()["valetKeyData"]
            data = r = None
            for hdr in ({"X-CSRF-TOKEN": tok} if tok else {}, {}):
                r = retry(s.post, f"{BLOB}DownloadBlob/{guid}", data={"ValetKey": key}, headers=hdr, timeout=60)
                if r.ok and (r.content[:4] in (b"%PDF", OLE) or r.content[:2] == b"PK"):
                    data = r.content; break
        except Exception as e:
            print(f"FAIL {uuid} {name}: {e}"); failed += 1; continue
        if data is None:
            print(f"FAIL {uuid} {name}: {r.status_code} {r.content[:200]!r}"); failed += 1; continue
        path = os.path.join(outdir, f"{uuid[:8]}_{name}")
        open(path, "wb").write(data)
        found = []
        try:
            txt = totext(data, found)
        except Exception as e:
            txt = ""; print(f"WARN {path}: text extraction failed: {e}")
        open(path + ".txt", "w").write(txt)
        print(f"OK {path} ({len(data)} bytes, {len(txt)} chars)")
        saved.append(path)
        for i, (ename, blob) in enumerate(found, 1):
            epath = f"{path}.emb{i}{next(e for m, e in MAGIC.items() if blob.startswith(m))}"
            open(epath, "wb").write(blob)
            print(f"OK {epath} (embedded {ename}, {len(blob)} bytes; text included above)")
    return saved, failed


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if not args or args[0] in ("-h", "--help"):
        sys.exit(__doc__)
    bad = 0
    for u in args:
        try:
            bad += download(u)[1]
        except Exception as e:
            print(f"FAIL {u}: {e}"); bad += 1
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
