import re

from rueda.cnv.listing import PRESETS, class_pattern, iso, merge, parse
from rueda.on.find_terms import KEYS, scan
from rueda.sec.form20f import extract

PAGE = """<div id="result1"><div class="panel"><div class="panel-heading"><h4 class="panel-title"><a>
<strong>Última Información Recibida</strong></a></h4></div><div class="panel-body"><table>
<tr><td>12 nov. 2025</td><td>22:37</td><td>AVISO DE RESULTADO</td><td>3442432</td>
<td><a href="https://aif2.cnv.gov.ar/presentations/publicview/a989c0a2-b79e-4c95-872c-0f02847495d0">x</a></td></tr>
</table></div></div>
<div class="panel"><div class="panel-heading"><h4 class="panel-title"><a><strong>EMISIONES</strong></a></h4></div>
<div class="panel-body"><div class="panel"><div class="panel-heading"><h4 class="panel-title"><a>
<strong>Avisos de Resultado</strong></a></h4></div><div class="panel-body"><table>
<tr><td>12 nov. 2025</td><td>22:37</td><td>AVISO DE RESULTADO</td><td>3442432</td>
<td><a href="https://aif2.cnv.gov.ar/presentations/publicview/a989c0a2-b79e-4c95-872c-0f02847495d0">x</a></td></tr>
<tr><td>3 ene. 2025</td><td>09:00</td><td>SUPLEMENTO CLASE V</td><td>1</td>
<td><a href="https://aif2.cnv.gov.ar/presentations/publicview/00000000-0000-0000-0000-000000000001">x</a></td></tr>
</table></div></div></div></div></div>"""


def test_cnv_parse_sections_and_dates():
    rows = merge(parse(PAGE))
    assert [r[0] for r in rows] == ["2025-11-12", "2025-01-03"]
    assert rows[0][5] == "EMISIONES > Avisos de Resultado"  # 'latest' panel dropped
    assert iso("5 sept. 2024") == "2024-09-05"


def test_class_pattern():
    p = class_pattern(5)
    assert p.search("CLASE 5 ") and p.search("CLASE V -") and p.search("CLASE Nº 05")
    assert not p.search("CLASE 50") and not p.search("CLASE VI")


def test_find_terms(tmp_path):
    f = tmp_path / "s.txt"
    f.write_text("intro\nTasa de Interés: 8,125%\nbase de un año de 360 días\nDenominación Mínima: US$1.000\n")
    out = "\n".join(scan(str(f), KEYS, 3, 0))
    assert "> L2: Tasa de Interés" in out and "> L3:" in out and "> L4:" in out
    empty = tmp_path / "e.txt"
    empty.write_text("")
    assert "SCAN" in "\n".join(scan(str(empty), KEYS, 3, 0))


def test_sec_extract_skips_table_of_contents():
    text = ("Item 13. Defaults, Dividend Arrearages\nItem 14. Material Modifications\n"
            "Item 5. Operating and Financial Review\nIndebtedness\nWe did not pay the notes.\n"
            "Item 6. Directors\nItem 13. Defaults, Dividend Arrearages and Delinquencies\n"
            "We were unable to pay principal on our class 2 notes.\nItem 14. Material Modifications\n")
    item13, debt, hits, _ = extract(text)
    assert "class 2 notes" in item13
    assert len(debt) == 1 and "did not pay" in debt[0]
    assert hits


def test_presets_split_issuance_and_payments():
    pago = "PROGRAMA 2020 - SERIE :ON CLASE I SERIE 2021 - AVISO DE PAGO OBLIGACIONES NEGOCIABLES"
    fx = "AVISO DE TIPO DE CAMBIO - ON CLASE 3 - 5° CUOTA"
    sup = "FECHA PUBLIC.: 28-09-2021 - SUPLEMENTO DE CANJE - ONS CLASE 1 SERIE 2021 - SUPLEMENTO"
    res = "PROGRAMA GLOBAL - AVISO DE RESULTADO DE COLOCACIÓN2"
    iss, pay = re.compile(PRESETS["issuance"], re.I), re.compile(PRESETS["payments"], re.I)
    assert iss.search(sup) and iss.search(res) and not iss.search(pago) and not iss.search(fx)
    assert pay.search(pago) and pay.search(fx) and not pay.search(sup)
