#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import csv, json, os, re, time
from typing import Dict, Optional, Tuple, List
import requests

# --- config ---
INPUT_CSV   = "./data/makaao_core.csv"
OUTPUT_CSV  = "./data/code_names.csv"
UMLS_API_KEY = "67bd1b8b-87f0-40de-bf20-255e6f1721a3"  # required for UMLS + SNOMED

UNIPROT_JSON_URL       = "https://rest.uniprot.org/uniprotkb/{acc}"
UMLS_CONCEPT_URL       = "https://uts-ws.nlm.nih.gov/rest/content/current/CUI/{cui}"
UMLS_SOURCE_CODE_URL   = "https://uts-ws.nlm.nih.gov/rest/content/current/source/{sab}/{code}"
OLS4_TERM_API          = "https://www.ebi.ac.uk/ols4/api/ontologies/{onto}/terms"
HEADERS = {"Accept": "application/json"}

SNOMED_SABS = ["SNOMEDCT_US", "SNOMEDCT", "SNOMEDCT_CORE", "SNOMEDCT_UK"] # snomed versions to check

# ---------- helpers ----------
def split_items(cell: str) -> List[str]: # split a string around "|", ",", or ";"
    if not cell:
        return []
    return [s for s in re.split(r"[ \t\r\n|,;]+", cell.strip()) if s]

def split_items_pipe(cell: str) -> List[str]: # split a string around "|" only
    if not cell:
        return []
    return [s.strip() for s in re.split(r"[|\r\n]+", cell.strip()) if s.strip()]

def req_get(url: str, params: Optional[dict] = None, headers: Optional[dict] = None, # function to query a URL
            retries: int = 3, backoff: float = 0.7, timeout: int = 25) -> Optional[requests.Response]:
    last = None
    for i in range(retries): # retry 3 times max, if URI tmeporarily unavailable
        try:
            r = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
            if r.status_code in (200, 404):
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (2 ** i)); continue # if error, wait a bit before retrying
            return r
        except requests.RequestException as e:
            last = e
        time.sleep(backoff * (2 ** i))
    if last:
        raise last
    return None

# ---------- normalizers ----------
def norm_uniprot(x: str) -> Optional[str]: # normalize uniprot identififers: remove prefix
    x = re.sub(r"(?i)^UP:?(?=[A-Za-z0-9])", "", (x or "").strip())
    return x.upper() if re.fullmatch(r"[A-Za-z0-9]{6,10}", x) else None

def norm_umls(x: str) -> Optional[str]: # normalize CUI identififers: remove prefix
    m = re.fullmatch(r"(?i)(?:CUI:)?(C\d{7,8})", (x or "").strip())
    return m.group(1).upper() if m else None

def norm_snomed_prefixed(x: str) -> Optional[str]:
    """Accept only explicitly prefixed SNOMED codes from disease_id.""" # same normalization...
    m = re.fullmatch(r"(?i)SNOMED:(\d{3,18})", (x or "").strip())
    return m.group(1) if m else None

def norm_orpha(x: str) -> Optional[str]:
    m = re.fullmatch(r"(?i)ORPHA:(\d+)", (x or "").strip())
    return m.group(1) if m else None

def norm_chebi(x: str) -> Optional[str]:
    m = re.fullmatch(r"(?i)CHEBI:?(\d+)", (x or "").strip())
    return m.group(1) if m else None

def norm_loinc_part(x: str) -> Optional[str]:
    x = (x or "").strip().upper()
    x = re.sub(r"[\u2010-\u2015\u2212\uFE63\uFF0D]", "-", x)
    m = re.fullmatch(r"LP\d+(?:-\d+)?", x)
    return m.group(0) if m else None

# ---------- resolvers ----------
def uniprot_name(acc: str) -> Tuple[Optional[str], str]: # query a uniprot ID from Uniprot API, return english nmae and URI
    r = req_get(UNIPROT_JSON_URL.format(acc=acc))
    page = f"https://www.uniprot.org/uniprotkb/{acc}"
    if not r or r.status_code != 200:
        return None, page
    try:
        d = r.json()
    except json.JSONDecodeError:
        return None, page
    pd = d.get("proteinDescription") or {}
    name = (
        (((pd.get("recommendedName") or {}).get("fullName") or {}).get("value")) # try to get the best name
        or next((x.get("fullName", {}).get("value") for x in pd.get("submissionNames", []) if x.get("fullName")), None)
        or next((x.get("fullName", {}).get("value") for x in pd.get("alternativeNames", []) if x.get("fullName")), None)
        or d.get("uniProtkbId")
    )
    return name, page

def umls_name(cui: str) -> Tuple[Optional[str], str]: # try to query a UMLS CUI from UMLS API
    page = f"https://uts.nlm.nih.gov/uts/umls/concept/{cui}"
    r = req_get(UMLS_CONCEPT_URL.format(cui=cui), params={"apiKey": UMLS_API_KEY}) # use API key
    if not r or r.status_code != 200:
        return None, page
    try:
        d = r.json()
    except json.JSONDecodeError:
        return None, page
    return (d.get("result") or {}).get("name"), page # return name and URI

def snomed_name(code: str) -> Tuple[Optional[str], str]: # query SNOMED name from UMLS API (since SNOMED terms are integrated to UMLS)
    page = f"https://snomed.info/id/{code}"
    for sab in SNOMED_SABS:
        r = req_get(UMLS_SOURCE_CODE_URL.format(sab=sab, code=code), params={"apiKey": UMLS_API_KEY}) # use UMLS API key
        if r and r.status_code == 200:
            try:
                d = r.json()
            except json.JSONDecodeError:
                continue
            name = (d.get("result") or {}).get("name")
            if name:
                return name, page # return name and SNOMED URI
    return None, page

def _ols_label(resp_json: dict) -> Optional[str]: # extract first name from an Ontology Lookup Service (OLS) response
    terms = (resp_json.get("_embedded") or {}).get("terms") or []
    return terms[0].get("label") if terms else None

def orpha_name(orpha_id: str) -> Tuple[Optional[str], str]: # query Orpha code from OLS
    page = f"https://www.orpha.net/consor/cgi-bin/OC_Exp.php?lng=en&Expert={orpha_id}" # reconstruct Orphanet URL
    # Try short_form
    r = req_get(OLS4_TERM_API.format(onto="ordo"), params={"short_form": f"Orphanet_{orpha_id}"})
    if r and r.status_code == 200:
        try:
            name = _ols_label(r.json())
            if name:
                return name, page
        except json.JSONDecodeError:
            pass
    # Try IRI
    iri = f"http://www.orpha.net/ORDO/Orphanet_{orpha_id}" # use official orphanet uri if 1st URI did not work
    r = req_get(OLS4_TERM_API.format(onto="ordo"), params={"iri": iri})
    if r and r.status_code == 200:
        try:
            name = _ols_label(r.json())
            if name:
                return name, page
        except json.JSONDecodeError:
            pass
    # Try obo_id variants
    for obo in (f"Orphanet:{orpha_id}", f"ORPHA:{orpha_id}"):
        r = req_get(OLS4_TERM_API.format(onto="ordo"), params={"obo_id": obo}) # try querrying OBO ID instead of Orphanet
        if r and r.status_code == 200:
            try:
                name = _ols_label(r.json())
                if name:
                    return name, page # return name and page
            except json.JSONDecodeError:
                pass
    return None, page # if no name, we only return page

def chebi_name(num: str) -> Tuple[Optional[str], str]:
    page = f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:{num}"
    r = req_get(OLS4_TERM_API.format(onto="chebi"), params={"obo_id": f"CHEBI:{num}"}) # query OLS API for chebi ID
    if not r or r.status_code != 200:
        return None, page
    try:
        d = r.json()
    except json.JSONDecodeError:
        return None, page
    return _ols_label(d), page # name and page

# ---------- main ----------
def main():
    if not UMLS_API_KEY or UMLS_API_KEY.startswith("REPLACE_"):
        raise SystemExit("Set UMLS_API_KEY at top of script.") # display warning if no API key

    uni: List[str] = []
    cui: List[str] = []
    chebi: List[str] = []
    sct_from_dis: List[str] = []
    orpha_from_dis: List[str] = []
    umls_from_dis: List[str] = []
    loinc_map: Dict[str, str] = {}  # id -> name

    with open(INPUT_CSV, newline="", encoding="utf-8") as f: # open makaao core csv file to read the rows
        rdr = csv.DictReader(f)
        cols = {c.lower(): c for c in (rdr.fieldnames or [])}

        # New names first, then legacy fallbacks
        up_col        = cols.get("uniprot_id")
        cui_col       = cols.get("umls_id")
        cheb_col      = cols.get("chebi_id")
        dis_col       = cols.get("disease_id")
        loinc_id_col  = cols.get("loinc_part_id")
        loinc_nm_col  = cols.get("loinc_part")

        for row in rdr:
            if up_col and row.get(up_col):
                uni.extend(split_items(row[up_col])) # for each row, read columns of interest (for targets), and split the several items in them
            if cui_col and row.get(cui_col):
                cui.extend(split_items(row[cui_col]))
            if cheb_col and row.get(cheb_col):
                chebi.extend(split_items(row[cheb_col]))

            if dis_col and row.get(dis_col): # for each row, read columns of interest (for diseases), and split the several items in them
                for t in split_items(row[dis_col]):
                    sct = norm_snomed_prefixed(t) # try to nomalize, and to add to relevant list of disease from each terminology
                    if sct:
                        sct_from_dis.append(sct); continue
                    orp = norm_orpha(t)
                    if orp:
                        orpha_from_dis.append(orp); continue
                    cu = norm_umls(t)
                    if cu:
                        umls_from_dis.append(cu); continue

            if loinc_id_col and row.get(loinc_id_col): # split what is in the loinc column, normalize it, 
                ids = [norm_loinc_part(x) for x in split_items_pipe(row[loinc_id_col])] # get loinc parts from csv
                ids = [x for x in ids if x] # remove empty elements
                names = split_items_pipe(row.get(loinc_nm_col, "")) if loinc_nm_col else [] # get loinc names from csv
                for i, lid in enumerate(ids):
                    nm = names[i] if i < len(names) else "" # a add anmes for each loinc id
                    if lid not in loinc_map or not loinc_map[lid]:
                        loinc_map[lid] = nm

    # normalize and dedupe
    uni_ids    = sorted({v for v in (norm_uniprot(x) for x in uni) if v})
    cui_ids    = sorted({v for v in (norm_umls(x)    for x in cui) if v} | set(umls_from_dis))
    chebi_ids  = sorted({v for v in (norm_chebi(x)   for x in chebi) if v})
    sct_ids    = sorted(set(sct_from_dis))
    orpha_ids  = sorted(set(orpha_from_dis))
    loinc_ids  = sorted(loinc_map.keys())

    out_rows: List[Dict[str, str]] = []

    for acc in uni_ids: # add each term to a list, with its id, name, terminology, URI
        name, url = uniprot_name(acc)
        out_rows.append({"source": "UniProt", "id": acc, "name": name or "", "url": url})

    for c in cui_ids:
        name, url = umls_name(c)
        out_rows.append({"source": "UMLS", "id": c, "name": name or "", "url": url})

    for code in sct_ids:
        name, url = snomed_name(code)
        out_rows.append({"source": "SNOMEDCT", "id": code, "name": name or "", "url": url})

    for oid in orpha_ids:
        name, url = orpha_name(oid)
        out_rows.append({"source": "ORPHA", "id": oid, "name": name or "", "url": url})

    for ch in chebi_ids:
        name, url = chebi_name(ch)
        out_rows.append({"source": "ChEBI", "id": f"CHEBI:{ch}", "name": name or "", "url": url})

    for lid in loinc_ids:
        url = f"https://loinc.org/{lid}" # reconstruct URI for each LOINC ID
        name = loinc_map.get(lid, "") or "" # try to get name
        out_rows.append({"source": "LOINC", "id": lid, "name": name, "url": url})

    os.makedirs(os.path.dirname(OUTPUT_CSV) or ".", exist_ok=True) # write a csv file with columns: source, id, name, url
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["source", "id", "name", "url"])
        w.writeheader(); w.writerows(out_rows)

    print(f"Wrote {len(out_rows)} rows -> {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
