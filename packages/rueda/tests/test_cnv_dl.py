import os

import pytest

from rueda.cnv import download as cnv_dl

FIX = os.path.join(os.path.dirname(__file__), "fixtures", "aa2000_aviso_pago_2003-01-17.zip.doc")


def test_zipped_word_doc_piece_table():
    # CNV filing of 17/01/2003: a zipped Word 97 .doc
    t = cnv_dl.totext(open(FIX, "rb").read())
    assert "se efectuó el pago de US$ 1.859.375" in " ".join(t.split())
    assert not any(c in t for c in "\x13\x14\x15\x00")


class FakeOle:
    def __init__(self, streams):
        self.streams = streams

    def listdir(self):
        return [p.split("/") for p in self.streams]

    def openstream(self, path):
        import io
        return io.BytesIO(self.streams["/".join(path)])


def test_embedded_objects_found():
    ole = FakeOle({"WordDocument": b"x", "ObjectPool/_1/CONTENTS": b"%PDF-1.4 ...",
                   "ObjectPool/_2/AttachContents": b"\x00\x01%PDF-1.3 ...", "ObjectPool/_3/Ole": b"\x01\x00"})
    got = dict(cnv_dl.embedded(ole))
    assert set(got) == {"ObjectPool/_1/CONTENTS", "ObjectPool/_2/AttachContents"}
    assert got["ObjectPool/_2/AttachContents"].startswith(b"%PDF")


def test_retry_on_connection_errors(monkeypatch):
    monkeypatch.setattr(cnv_dl.time, "sleep", lambda s: None)
    calls = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise cnv_dl.requests.ConnectionError("dns")
        return "ok"

    assert cnv_dl.retry(flaky) == "ok" and len(calls) == 3
    with pytest.raises(cnv_dl.requests.ConnectionError):
        cnv_dl.retry(lambda: (_ for _ in ()).throw(cnv_dl.requests.ConnectionError("down")))
