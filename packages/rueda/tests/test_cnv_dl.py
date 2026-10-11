"""Tests of the text extraction and the retries of `rueda cnv dl`."""

import io
import time
from pathlib import Path

import pytest
import requests

from rueda.cnv import download as cnv_dl

FIX = Path(__file__).parent / "fixtures" / "aa2000_aviso_pago_2003-01-17.zip.doc"


def test_zipped_word_doc_piece_table() -> None:
    """The text of a zipped Word 97 .doc comes from its piece table."""
    # CNV filing of 17/01/2003: a zipped Word 97 .doc
    t = cnv_dl.totext(FIX.read_bytes())
    assert "se efectuó el pago de US$ 1.859.375" in " ".join(t.split())
    assert not any(c in t for c in "\x13\x14\x15\x00")


class FakeOle:
    """The streams of an OLE file, listed and opened the way olefile does."""

    def __init__(self, streams: dict[str, bytes]) -> None:
        """Take {stream path joined by '/': content}."""
        self.streams = streams

    def listdir(self) -> list[list[str]]:
        """Return every stream path as a list of names."""
        return [p.split("/") for p in self.streams]

    def openstream(self, path: list[str]) -> io.BytesIO:
        """Return the content of a stream as a file object."""
        return io.BytesIO(self.streams["/".join(path)])


def test_embedded_objects_found() -> None:
    """PDFs in the ObjectPool are found, at the start of a stream or inside it."""
    ole = FakeOle(
        {
            "WordDocument": b"x",
            "ObjectPool/_1/CONTENTS": b"%PDF-1.4 ...",
            "ObjectPool/_2/AttachContents": b"\x00\x01%PDF-1.3 ...",
            "ObjectPool/_3/Ole": b"\x01\x00",
        }
    )
    got = dict(cnv_dl.embedded(ole))
    assert set(got) == {"ObjectPool/_1/CONTENTS", "ObjectPool/_2/AttachContents"}
    assert got["ObjectPool/_2/AttachContents"].startswith(b"%PDF")


def test_retry_on_connection_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """A request is tried three times; the third error is raised."""
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    calls: list[int] = []

    def flaky() -> str:
        calls.append(1)
        if len(calls) < 3:
            msg = "dns"
            raise requests.ConnectionError(msg)
        return "ok"

    assert cnv_dl.retry(flaky) == "ok"
    assert len(calls) == 3

    def down() -> None:
        calls.append(1)
        msg = "down"
        raise requests.ConnectionError(msg)

    with pytest.raises(requests.ConnectionError):
        cnv_dl.retry(down)
    assert len(calls) == 6
