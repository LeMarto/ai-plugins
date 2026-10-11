"""Tests of the text tools: the CNV listing, find-terms and the 20-F extract."""

import re
from pathlib import Path

from rueda.cnv.listing import PRESETS, class_pattern, iso, merge, parse
from rueda.on.find_terms import KEYS, scan
from rueda.sec.form20f import extract

PANEL = '<div class="panel"><div class="panel-heading"><h4 class="panel-title"><a>'
BODY = '<div class="panel-body">'
PUBLICVIEW = "https://aif2.cnv.gov.ar/presentations/publicview"


def row(day: str, hour: str, title: str, number: str, uuid: str) -> str:
    """Return one document row of the company page."""
    return (
        f"<tr><td>{day}</td><td>{hour}</td><td>{title}</td><td>{number}</td>\n"
        f'<td><a href="{PUBLICVIEW}/{uuid}">x</a></td></tr>\n'
    )


RESULTADO = row(
    "12 nov. 2025",
    "22:37",
    "AVISO DE RESULTADO",
    "3442432",
    "a989c0a2-b79e-4c95-872c-0f02847495d0",
)
SUPLEMENTO = row(
    "3 ene. 2025",
    "09:00",
    "SUPLEMENTO CLASE V",
    "1",
    "00000000-0000-0000-0000-000000000001",
)
PAGE = (
    f'<div id="result1">{PANEL}\n'
    f"<strong>Última Información Recibida</strong></a></h4></div>{BODY}<table>\n"
    f"{RESULTADO}</table></div></div>\n"
    f"{PANEL}<strong>EMISIONES</strong></a></h4></div>\n"
    f"{BODY}{PANEL}\n"
    f"<strong>Avisos de Resultado</strong></a></h4></div>{BODY}<table>\n"
    f"{RESULTADO}{SUPLEMENTO}</table></div></div></div></div></div>"
)


def test_cnv_parse_sections_and_dates() -> None:
    """A document listed twice comes out once, under its own section."""
    rows = merge(parse(PAGE))
    assert [r[0] for r in rows] == ["2025-11-12", "2025-01-03"]
    assert rows[0][5] == "EMISIONES > Avisos de Resultado"  # 'latest' panel dropped
    assert iso("5 sept. 2024") == "2024-09-05"


def test_class_pattern() -> None:
    """A class matches in Arabic and Roman form, and not as a prefix of another."""
    p = class_pattern(5)
    assert p.search("CLASE 5 ")
    assert p.search("CLASE V -")
    assert p.search("CLASE Nº 05")
    assert not p.search("CLASE 50")
    assert not p.search("CLASE VI")


def test_find_terms(tmp_path: Path) -> None:
    """Term lines are found ignoring accents; an empty file is reported as a scan."""
    f = tmp_path / "s.txt"
    f.write_text(
        "intro\nTasa de Interés: 8,125%\nbase de un año de 360 días\n"
        "Denominación Mínima: US$1.000\n"
    )
    out = "\n".join(scan(str(f), KEYS, 3, 0))
    assert "> L2: Tasa de Interés" in out
    assert "> L3:" in out
    assert "> L4:" in out
    empty = tmp_path / "e.txt"
    empty.write_text("")
    assert "SCAN" in "\n".join(scan(str(empty), KEYS, 3, 0))


def test_sec_extract_skips_table_of_contents() -> None:
    """Item 13 and the debt subsection come from the body, not the contents."""
    text = (
        "Item 13. Defaults, Dividend Arrearages\nItem 14. Material Modifications\n"
        "Item 5. Operating and Financial Review\nIndebtedness\n"
        "We did not pay the notes.\n"
        "Item 6. Directors\nItem 13. Defaults, Dividend Arrearages and Delinquencies\n"
        "We were unable to pay principal on our class 2 notes.\n"
        "Item 14. Material Modifications\n"
    )
    item13, debt, hits, _ = extract(text)
    assert "class 2 notes" in item13
    assert len(debt) == 1
    assert "did not pay" in debt[0]
    assert hits


def test_presets_split_issuance_and_payments() -> None:
    """The issuance and payments presets match disjoint sets of titles."""
    pago = (
        "PROGRAMA 2020 - SERIE :ON CLASE I SERIE 2021 - "
        "AVISO DE PAGO OBLIGACIONES NEGOCIABLES"
    )
    fx = "AVISO DE TIPO DE CAMBIO - ON CLASE 3 - 5° CUOTA"
    sup = (
        "FECHA PUBLIC.: 28-09-2021 - SUPLEMENTO DE CANJE - "
        "ONS CLASE 1 SERIE 2021 - SUPLEMENTO"
    )
    res = "PROGRAMA GLOBAL - AVISO DE RESULTADO DE COLOCACIÓN2"
    iss = re.compile(PRESETS["issuance"], re.IGNORECASE)
    pay = re.compile(PRESETS["payments"], re.IGNORECASE)
    assert iss.search(sup)
    assert iss.search(res)
    assert not iss.search(pago)
    assert not iss.search(fx)
    assert pay.search(pago)
    assert pay.search(fx)
    assert not pay.search(sup)
