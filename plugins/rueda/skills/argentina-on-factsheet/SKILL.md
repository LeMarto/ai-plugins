---
name: "argentina-on-factsheet"
description: "Builds a factsheet for an Argentine corporate bond (obligación negociable): terms, payment schedule, yield, the issuer's debt payment history (defaults, restructurings, exchanges) and a background check of the current CEO and CFO (corruption cases, failures of companies they led) from official CNV documents, rating agencies, SEC filings and public records, given a ticker, name or ISIN."
---

# Argentine corporate bond (ON) factsheet

Input: BYMA ticker (e.g. PLC5O), bond name or ISIN.
Output: a terms table, a table of future payments, the yield, the issuer's credit history and a background check of the current CEO and CFO, with the source of each figure.

Reply in the user's language. Document and section names below are in Spanish because that is how they appear on the CNV site; search for them as written.

Use WebSearch and WebFetch for searching and reading web pages. The shell can reach www.cnv.gov.ar, aif2.cnv.gov.ar and blob.cnv.gov.ar; use it for the CNV listing (step 2) and documents (step 3). WebFetch of www.cnv.gov.ar failed with a DNS error in testing.

## 0. Considerations
The tools are the `rueda` Python package, shipped as `rueda-0.1.1-py3-none-any.whl` in this skill's directory (`${CLAUDE_SKILL_DIR}`). Where a step says `rueda <command>`, run `uvx --from ${CLAUDE_SKILL_DIR}/rueda-0.1.1-py3-none-any.whl rueda <command>`. Run it from the scratchpad; the commands write `./docs/`, `./holidays/` and `./sec/` there. `uvx` installs the package's dependencies (requests, pypdf, olefile) on the first run. `rueda` without arguments lists the commands. For other Python, use `uv run --with <package>`.

## 1. Identify the bond

- `rueda identify <ticker> [<CUIT>] [<ISIN>]` gives the base ticker, quote currency (`O` = pesos, `D` = MEP dollars, `C` = cable dollars; PLC5O, PLC5D and PLC5C are the same bond), the class if the ticker carries digits (Arabic and Roman), and validates CUIT and ISIN check digits. Exit status 1 means a check digit failed: the identifier was garbled or mistyped; find it again.
- WebSearch `"{ticker} obligación negociable"`. Collect issuer, class number, ISIN and the issuer's CUIT. Sources with these fields: broker instrument pages (cohen.com.ar, facimexvalores.com.ar show issuer and ISIN) and ARCA's Bienes Personales valuation list (ticker, name and CUIT).
- The number in the ticker usually matches the class (PLC5 → class 5); confirm it against the ISIN in the suplemento.
- If the CUIT is missing: WebSearch `"CUIT {issuer}"` or take it from an aviso de suscripción.
- If two sources give different class or ISIN, report it to the user before continuing.

## 2. List the documents on the CNV site

- Run `rueda cnv list <CUIT> <year_from> [<year_to>] [--class N] [--preset NAME] [--grep REGEX]`. It fetches `https://www.cnv.gov.ar/SitioWeb/Empresas/Empresa/{CUIT}?fdesde=1/1/{y}&fhasta=31/12/{y}` one year per request, in parallel (1–30 s per year), and prints, newest first, date (YYYY-MM-DD), time, document number, publicview UUID, title and section path (e.g. `EMISIONES > Obligaciones Negociables > Suplementos`). Always pass `fdesde`: without it the page timed out in testing. Start at the bond's issue year; if the class does not appear, go back one year at a time.
- Filters combine with AND:
  - `--class 5` matches "CLASE 5", "CLASE Nº 05" and "CLASE V" in the title (BYMA often uses Roman numerals, the CNV Arabic).
  - `--preset issuance` keeps suplementos, avisos de suscripción, resultado and complementarios, adendas, prospectos and Art. 10 LON filings. `--preset payments` keeps avisos de pago and exchange-rate notices; with `--class` and `--grep` for the series, its first line is the latest aviso de pago. `credit` and `management` are the step 5c and 5d searches.
  - `--grep REGEX` matches title or section.
- Sections to check:
  - Emisiones → Obligaciones Negociables → Suplementos, Aviso de Suscripción, Avisos de Resultado, Aviso de Pago, Prospectos → Programas Globales.
  - Emisiones → Otra Información (Art. 10 LON).
  - Hechos Relevantes.
- Each document has a link `https://aif2.cnv.gov.ar/presentations/publicview/{uuid}`.
- Some avisos de resultado do not name the class ("AVISO DE RESULTADO DE COLOCACIÓN2"). Match them by date: they are published when the auction stated in the class's aviso de suscripción closes.
- If there are "Adicionales" classes or addenda, read the original suplemento and the additional ones. The outstanding amount is the sum.

## 3. Get the document text

The `publicview` viewer loads the PDF with JavaScript; WebFetch returns only the empty page. In this order:

1. Download with `rueda cnv dl`, passing one or more `publicview` UUIDs:
   `rueda cnv dl <uuid> [<uuid> ...]`
   Run it from the scratchpad. It saves each attachment and its extracted text to `./docs/`. A `.txt` with 0 characters means the PDF is a scan: open the PDF with the Read tool. Avisos de pago are often scans.
   Old filings (zipped Word .doc) are read from the Word piece table. Documents embedded in a .doc (Acrobat objects, Outlook attachments, often whole prospectuses) are saved as `<file>.embN.pdf` and their text is appended to the .txt.
   Each request is tried 3 times. A UUID that still fails prints `FAIL` and the others continue; the exit status is 1 if anything failed, so check for `FAIL` lines and retry those UUIDs.
   How it works, in case the site changes: the publicview HTML embeds the attachments as JSON (`nombreArchivo`, `guid`). `GET https://aif2.cnv.gov.ar/api/ValetKeyProvider/GetPublicValetKey/{guid}?operation=DownloadBlob` returns `valetKeyData`, and `POST https://blob.cnv.gov.ar/BlobWebService.svc/DownloadBlob/{guid}` with form field `ValetKey=<valetKeyData>` returns the PDF. No login needed (verified October 2026).
2. If the command fails and the session has browser tools (built-in browser or Claude in Chrome), read that browser's skill, open the `publicview` link and read the PDF.
3. Otherwise, search for a copy of the same PDF: WebSearch `"{issuer} suplemento clase {n}"` or `"{ISIN} suplemento"` (issuer's website, placement agent banks). Use a copy only if its ISIN and date match the CNV listing. ws.bolsar.info and docs.bondterminal.com reject WebFetch.
4. If no readable copy exists, send the user the `publicview` links for the suplemento and the aviso de resultados and ask them to attach the PDFs. Never fill in terms with estimates.

The WebFetch summary of the CNV listing can garble UUIDs; if the command gets no attachments, re-fetch the listing and check the UUID.

Suplementos of international classes run to hundreds of pages. Locate the terms with `rueda on find-terms docs/*.txt [--keys rate,day_count,...] [--max 3] [--context 1]`: it prints the matching lines, with line numbers, for issue date, maturity, rate, day count, payment dates, amortization, minimum purchase, business day, currency, redemption, ranking, law, rating and auction results (`--grep` adds a pattern). Read around those line numbers before filling a field; the summary term sheet near the start often defers to the aviso de resultados ("Será informada en el Aviso de Resultados"), and the day count and business-day rule are usually in the "Descripción de la Oferta" section further in.

Documents to read:
- Suplemento de prospecto of the class: terms and conditions.
- Aviso de resultados and addenda: issued amount, clearing rate, price, issue date.
- Avisos complementarios: ratings and changes to terms.
- Latest aviso de pago: dates and amounts per face value.
- Hechos relevantes after issuance: redemptions, buybacks, exchanges, amendments, defaults.

If a later notice amends the suplemento, the later one applies; state it in the notes.

## 4. Terms table

Columns: Field | Value | Source (document and date).

Fields:
- Issuer and CUIT; program; class; tickers (O/D/C); ISIN
- Denomination currency; subscription and payment currency (pesos, MEP, cable, dollar-linked with the applicable exchange rate)
- Issued amount; unit face value
- Minimum purchase (see below)
- Issue and settlement date; maturity
- Rate: fixed or floating (base rate + margin); day-count convention
- Interest frequency and payment dates
- Amortization: bullet or installments, with percentage and date of each
- Optional redemption, tax redemption, change of control
- Guarantees and ranking
- Governing law and jurisdiction
- Listing markets
- Current credit rating

Field absent from the documents: "Not stated".

### Minimum purchase

- Take it from the suplemento: search for "Denominación Mínima", "Unidad Mínima de Negociación" and "Monto Mínimo de Suscripción". Report the minimum face value and the increment above it (e.g. "US$1.000 VN y múltiplos de US$1"). The monto mínimo de suscripción applies only to the primary auction; say so if it differs.
- Amortizing bonds: give the outstanding value of that minimum lot after the last amortization, from the latest aviso de pago ("valor residual mínimo") or from `rueda on tir` (residual value line).
- The secondary-market lot (BYMA "lámina mínima") can differ from the suplemento and is not in CNV documents. Tell the user how to confirm it: the instrument page on open.bymadata.com.ar or their broker's order screen. Do not state a market lot you have not seen in a source.
- Give the approximate cost of the minimum lot printed by `rueda on tir` (dirty price per 100 original × minimum face value / 100), and label it as market data with its source and date.

## 4b. terms.json

Write the terms that the schedule and yield depend on to `terms.json` in the scratchpad, following the example printed by `rueda on terms-example` (PLC5, with the format in its `_comment`). Every field is `{"value": ..., "source": "document and date"}`. Use the latest amended value. If a required field is not in the documents, do not guess it: the commands stop and list what is missing; report it as "Not stated" and skip steps 5 and 5b.

- Payments: `first_payment_date` + `frequency_months` when the suplemento gives a regular cycle, or the explicit `payment_dates` list.
- `amortization`: percentage of original face value per date, adding up to 100.
- `business_day_calendars`: the cities in the suplemento's "Día Hábil" definition (`AR` for Buenos Aires, `US` for New York).
- `accrue_to_adjusted_date`: true only if the suplemento says interest accrues until the adjusted payment date.
- `last_payment_notice`: from the latest aviso de pago, converted to amounts per 100 face value (e.g. US$20.312.500 on US$500.000.000 → 4.0625). Floating rate: add the rate applied.
- `call_schedule` (optional): the fixed-price optional redemption windows, `[{"from": "YYYY-MM-DD", "to": "YYYY-MM-DD" (exclusive, optional), "price_pct": 104.25}]`, price as a percentage of outstanding principal (accrued interest is added). Leave out make-whole periods (Treasury + spread): the commands do not model them; mention them in the notes.

## 5. Payment schedule

- Run `rueda on schedule terms.json [--today YYYY-MM-DD] [--all] [--csv flows.csv]`. Pass today's date from the time tool.
- It prints the future payments per 100 original face value (date, interest, amortization, total, balance after), marks the next one, lists dates moved to a business day, and compares the latest aviso de pago with the computed amounts.
- `MISMATCH` means a term in terms.json is wrong (day count, dates, business-day rule, rate): find it in the documents and run again. Do not deliver a schedule that disagrees with an aviso de pago without explaining the difference.
- `WARN` lines about holidays: Argentine holidays come from api.argentinadatos.com for published years; later years use fixed, Easter-based and law 27.399 movable dates without puentes. Say in the notes that payment dates in those years may move by a day.
- Floating rate: amounts are projected with `base_rate` (name, rate, date) + `margin` and marked "(est.)"; name that rate and its date in the reply.
- Dollar-linked or dollar bonds payable in pesos: the schedule is in the denomination currency; state the applicable exchange rate per the suplemento.
- Amortizing or step-up structures the command cannot express (capitalization, PIK, rate steps): compute them separately in Python and say so.
- `--csv` writes every flow; use it if the user wants the schedule in a spreadsheet.

## 5b. Yield (TIR), always

Always compute it, even if the user did not ask. If no price can be found, say so in the yield section and skip the calculation; do not guess a price.

- Price: WebFetch the broker quote for the ticker in the bond's currency (for hard-dollar bonds use the D ticker, e.g. iol.invertironline.com/titulo/cotizacion/BCBA/{ticker}D/). Record source, price and quote time (or "time not shown"). It is market data, not CNV data.
- Run `rueda on tir terms.json --price P --quote-date YYYY-MM-DD [--compare-tir PCT]`. Use the quote date, or today if the page shows none.
- It computes settlement (T+1 business day in Buenos Aires), accrued interest under the suplemento's day count, residual, effective annual TIR on actual/365 time from settlement, Macaulay and modified duration, parity = dirty price / (residual + accrued), and the minimum lot's residual value and cost.
- Price convention: BYMA usually quotes per 100 original face value, dirty (accrued included), but pages rarely say so. The command assumes that (`--convention dirty-original`) and also prints the table for clean and per-100-residual quotes. State which one is assumed and how to confirm it (BYMA instrument sheet or broker; the price drops by about one coupon on the ex-date if quotes are dirty).
- If a public source shows a TIR (e.g. inversoy.com.ar), pass it with `--compare-tir` and mention the difference in basis points.
- Callable bonds (terms.json has `call_schedule`): the command adds a table with cash, total return and TIR if the whole issue is called at each window start (and the worst date; `--calls-all` lists every payment date), the yield to worst, and a warning when the price is above the current call value. Report the yield to worst next to the TIR; if the price is above the call value, say that a call would return less than the price paid.
- O/D/C tickers can give slightly different yields because of the MEP/cable spread; say so.

## 5c. Issuer credit history, always

Check whether the issuer (and companies merged into it) ever missed a payment or restructured debt. Cover from 2000, or from the issuer's first debt if later. Do it in a subagent if available: it reads many documents.

Classify each event; do not call anything a default unless a source does:
- (a) payment default: principal or interest not paid on the due date, even if later cured by extensions or a restructuring;
- (b) distressed exchange that a rating agency rated SD/RD/D;
- (c) refinancing forced by BCRA rules (e.g. Comunicación A 7106, 2020–2022);
- (d) voluntary liability management: tender offers, early redemptions, voluntary exchanges, consent solicitations.

Sources, in this order:
1. CNV listing for every year: `rueda cnv list <CUIT> 2000 <this year> --preset credit` (titles with CANJE, REESTRUCTUR, CONSENTIMIENTO, RESCATE, INCUMPL, PRÓRROGA, bondholder assemblies and HECHO RELEVANTE).
   - The AIF goes back to about 2000 for long-listed issuers. Older titles are generic ("HECHO RELEVANTE - HECHO RELEVANTE", "ACTA DE ASAMBLEA"), so open the documents near crisis years (2001–2002, 2019–2020) instead of trusting titles.
   - Old attachments are zipped Word files; `rueda cnv dl` extracts their text, including prospectuses embedded as PDF objects inside them.
   - "RECOMPRA" filings are usually share buybacks, not bond buybacks; check before counting them.
   - Bondholder assemblies that extend a maturity, and prospectus risk factors saying "no hemos pagado ciertas obligaciones de deuda a su vencimiento", are evidence of (a).
   - Merged companies keep their own CUIT page, which may start later than the issuer's.
2. SEC filings, if the issuer files a 20-F (e.g. it has ADRs). `rueda sec 20f <NYSE ticker or CIK> [--from YEAR] [--to YEAR]` lists every 20-F, including the older `filings.files` pages, saves each one's text to `./sec/`, and writes an `_extract.txt` with Item 13 ("Defaults, Dividend Arrearages and Delinquencies"), the Item 5 indebtedness subsections and the lines mentioning defaults, restructurings or exchange offers. Read the extracts for the crisis years first; open the full text when an extract is empty or cut. Filings before 2002 are on paper only (listed as such).
3. Ratings:
   - FIX SCR pages work with WebFetch: issuer page `fixscr.com/emisor/view?type=emisor&id={id}` and reports `fixscr.com/reportes-web/view?id={id}`.
   - moodys.com, spglobal.com and cbonds return 403; use search-result titles and snippets, or Fitch press releases republished on marketscreener.com.
   - Searches for "SD"/"RD" plus a company name mostly return sovereign results; search `"{issuer}" "selective default" OR "restricted default" OR "distressed debt exchange"`.
4. News, only to fill gaps and dates. Do not trust web summaries that say an issuer "never defaulted": check against filings.

Output: a chronological table with date, event, instruments, class (a–d) and source (publicview link with its date, 20-F year, or URL). Follow it with 2–4 lines of conclusions and a list of what could not be verified.

## 5d. Management: current CEO and CFO, always

Identify who holds each role today, then check their career for corruption cases and for failures (bankruptcies) of companies they led. Do it in a subagent if available, in parallel with 5c.

### Who they are
- In Argentine filings the CEO is usually the "Gerente General", "Director Ejecutivo" or "CEO"; the CFO is the "Gerente de Administración y Finanzas", "Director de Finanzas" or "CFO". The Presidente del Directorio is not the CEO unless the filings say so; report the chair separately only if they are also an executive.
- Sources, most authoritative first:
  1. CNV listing: the latest "NÓMINA DE AUTORIDADES" filing (section `INFORMACIÓN SOCIETARIA > Nóminas > de Autoridades`) and later Hechos Relevantes about appointments or departures (`--preset management`). A later departure overrides the nómina.
  2. The latest prospecto or suplemento, section "Directores, Administradores, Gerentes y Miembros del Órgano de Fiscalización" (or "Gerencia de primera línea"). It usually has short bios with previous positions.
  3. For issuers that file a 20-F, or whose parent does, use Item 6 "Directors, Senior Management and Employees".
  4. The company's website and recent news, to confirm the person is still in the role.
- Record for each person: name, role, start date in the role, and source with date. If sources disagree on who holds a role, report both, with dates.

### Career history
- Build a list of previous employers and roles, with years. Start from the prospectus or 20-F bio; fill gaps with the company's site, news and search snippets from professional profiles. Mark entries taken only from a professional profile as self-reported.

### Checks
For each person, and for each company where they held a senior role (director, CEO, CFO, general manager) during their tenure:
- **Corruption and fraud.**
  - WebSearch `"{name}" corrupción OR soborno OR coimas OR procesado OR imputado OR "lavado de dinero"` and `"{name}" fraud OR bribery OR indicted OR SEC`.
  - Check whether the person or their companies appear in well-known Argentine cases (e.g. Cuadernos, Odebrecht, Vialidad) and in foreign enforcement actions (SEC/DOJ FCPA actions, the World Bank debarment list, OFAC sanctions).
  - The CIJ (cij.gov.ar) and the Boletín Oficial can confirm court rulings and sanctions.
- **Company failures.**
  - WebSearch `"{company}" "concurso preventivo" OR quiebra` and `"{company}" bankruptcy OR "Chapter 11"` for each company where they held a senior role.
  - Confirm that the failure happened during their tenure or within about two years after they left. Use the Boletín Oficial or court edicts for Argentine concursos.
- **CNV and BCRA sanctions.**
  - Search the person's name together with "CNV sumario" or "sanción", and with "BCRA sumario".

### Rules
- Verify identity before attributing anything: namesakes are common. A match must share career details (employer, role, dates) or an ID number (DNI/CUIT). If identity cannot be confirmed, say so and do not attribute the case.
- Classify each finding by its procedural status, using the source's wording:
  - conviction (condena);
  - indictment (procesamiento or acusación formal);
  - under investigation (imputado or investigado);
  - mentioned only (named in news or a filing, with no proceeding against them);
  - acquitted or dismissed (sobreseído or absuelto).
- Never describe an investigation as a conviction.
- Separate personal involvement from cases against a company where the person merely worked. Say whether the case covers their period and role.
- Every finding needs a source (URL or document with date). Do not rely on a single uncorroborated blog or social-media post.
- "Nothing found" means nothing was found in the sources searched. State which sources and queries were used; do not say the person "has a clean record".

Output: per person, the name, role, start date and source, then a career table (company | role | years | source). Then a findings table with columns date | person | event | company | status | personal or company-level | source, or "Nothing found in: …". End with 2–3 lines of conclusions and a list of what could not be verified.

## 6. Delivery

In the reply, in this order:
1. One-line identification: issuer, class, ISIN, maturity.
2. Terms table.
3. Payment schedule table.
4. Yield: price used (source, time, convention), TIR, duration, parity, and the alternative-convention table.
5. Issuer credit history (step 5c): conclusions first, then the table.
6. Management (step 5d): CEO and CFO, careers, findings and conclusions.
7. Notes: amendments, hechos relevantes, fields not stated, estimates.
8. "Sources:" with the `publicview` link (or the copy used) and the date of each document.

Add one line stating this is not financial advice. State that prices and yield are market data, not CNV data. If the user wants to keep the schedule, offer to put it in a spreadsheet.

## Identification example (verified October 2026)

PLC5O → Pluspetrol S.A., CUIT 30-67822401-0, ISIN USP7924AAC29, 8.125% per year (30/360), interest on May 18 and November 18 starting May 18, 2026, full amortization on May 18, 2031. Issued 18/11/2025 at 98.916% (yield 8.375%); minimum US$1.000 and multiples of US$1.000; business days in Buenos Aires and New York. Its terms.json is the output of `rueda on terms-example`.
CNV page: `https://www.cnv.gov.ar/SitioWeb/Empresas/Empresa/30678224010?fdesde=1/1/2025`

## Credit history example (verified October 2026)

IRSA (CUIT 30-52532274-9, IRCOO = Clase XXIII):
- Payment defaults (a) in 2001–2002. ON Clase 02 principal was unpaid at maturity on 24/12/2001; holders extended it month by month. The US$80M syndicated loan and Goldman Sachs instalments were also unpaid. Everything was cured in the November 2002 refinancing, together with US$100M of convertibles.
- In 2020 the Clase I exchange was forced by A 7106 (c).
- In 2022 the exchange of the ex-IRCP 2023 notes was regulatory-motivated (c/d).
- The 2016 tenders, the 2021–2023 early redemptions and the 2025 exchange of Clase XIV for Clase XXIV were voluntary (d).
- No SD/RD/D rating found. FIX rated it AAA(arg) in June 2026.
- Key evidence: the 20-F for FY2002 (Item 5) and the CNV prospectus of 18/10/2002 (publicview `019369eb-d90e-49a0-98e3-928f1cfc1561`).
