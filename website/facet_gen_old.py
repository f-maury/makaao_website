#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, csv, re, html, json
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from string import Template
from collections import defaultdict

#
makaao_csv_path = "./data/makaao_core.csv"  # AAb table
LOINC_PART_TEST_JSON = "./data/loinc_part_test_dict.json"  # LOINC test for each LOINC part
LOINC_LABELS_JSON    = "./data/loinc_labels.json"          # dict of labels for LOINC parts and test

# --------- Config ----------
DEFAULT_DIRS = ["./db", "./data", "."]
OUTPUT_DIR = Path("./db")
PAGES_SUBDIR = "/db"  # directory for generated pages
BASE_KG = "http://makaao.inria.fr/kg"
code_names =  "./data/code_names.csv" # file with labels correspondence table

# --------- Helpers ----------
def esc(s: str) -> str:  # sanitize strings for putting them in html pages
    return html.escape(s or "")


def read_csv_rows(csv_path: str) -> List[Dict[str, str]]:  # read a csv file, get a list of rows
    p = Path(csv_path)
    rows: List[Dict[str, str]] = []
    with p.open(newline="", encoding="utf-8") as f:
        rdr = csv.DictReader(f)
        for r in rdr:
            r = { (k or "").strip().lstrip("\ufeff"): (v or "").strip() for k, v in r.items() } # read non-empty lines from abb table
            if not r.get("aab_id", "").strip():
                continue
            rows.append(r)
    return rows

def page_href(slug: str) -> str:  # given a slug, return a page name
    return f"{PAGES_SUBDIR.rstrip('/')}/{slug}.html"

def normalize_id(s: str) -> str:  # remove initial 0s in a number string, ex: "009" -> "9"
    t = (s or "").strip()
    if not t:
        return ""
    m = re.fullmatch(r"0*(\d+)", t)
    return m.group(1) if m else t

def split_pipes(cell: str) -> List[str]:  # separate a string in a list of strings; separators : "|", "\r", "\n"
    if not cell:
        return []
    parts = re.split(r"[|\r\n]+", cell)
    return [p.strip() for p in parts if p.strip()]

def split_sources_per_item(src_cell: str, n_items: int) -> List[List[str]]:
    """Return list-of-lists aligned to items. If counts mismatch, replicate union."""
    if not src_cell:
        return [[] for _ in range(n_items)]
    groups = [g.strip() for g in src_cell.split("|")]
    if len(groups) == n_items:
        return [[s.strip() for s in re.split(r"[;]+", g) if s.strip()] for g in groups] # inside a single item, split the several sources around ";"
    else:
        print("split_sources_per_item : mismatch error !")
        return []

# --------- Link builders ----------
def uniprot_url(acc: str) -> str:  # from an identifier, build a link in a terminology
    return f"https://www.uniprot.org/uniprotkb/{acc}"

def umls_url(cui: str) -> str:
    return f"https://uts.nlm.nih.gov/uts/umls/concept/{cui}"

def chebi_url(code: str) -> str:
    return f"https://www.ebi.ac.uk/chebi/searchId.do?chebiId=CHEBI:{code}"

def orpha_url(num: str) -> str:
    return f"https://www.orpha.net/consor/cgi-bin/OC_Exp.php?lng=en&Expert={num}"

def omim_url(num: str) -> str:
    return f"https://omim.org/entry/{num}"

def snomed_url(num: str) -> str:
    return f"https://snomed.info/id/{num}"

def loinc_url_org(code: str) -> str:
    c = (code or "").strip()
    return f"https://loinc.org/{c}"

def loinc_url(code: str) -> str:
    c = (code or "").strip()
    return f"http://purl.bioontology.org/ontology/LNC/{c}"

def source_to_href(s: str) -> Optional[str]:  # PMID → PubMed, DOI → doi.org, http(s) kept, else None
    s = (s or "").strip()
    if not s:
        return None
    if s.lower().startswith("pmid:"):
        num = re.sub(r"(?i)^pmid:\s*", "", s)
        return f"https://pubmed.ncbi.nlm.nih.gov/{num}/"
    if re.match(r"^https?://", s, flags=re.I):
        return s
    m = re.search(r"(10\.\d{4,9}/\S+)", s)  # DOI
        # note: above line intentionally left as-is, even if long
    if m:
        return f"https://doi.org/{m.group(1)}"
    return None

def code_to_link(code: str) -> str:  # take identifiers with prefix, return proper URI
    c = (code or "").strip()
    up = c.upper()
    if up.startswith("UP:"):
        acc = c.split(":", 1)[1]
        return uniprot_url(acc)
    if up.startswith("CUI:"):
        cui = c.split(":", 1)[1].upper()
        return umls_url(cui)
    if up.startswith("CHEBI:"):
        che = c.split(":", 1)[1].upper()
        return chebi_url(che)
    if up.startswith("ORPHA:"):
        num = c.split(":", 1)[1]
        return orpha_url(num)
    if up.startswith("OMIM:"):
        num = c.split(":", 1)[1]
        return omim_url(num)
    if up.startswith("SCTID:"):
        num = c.split(":", 1)[1]
        return snomed_url(num)
    return "#"

# --------- code_names.csv loader ----------

def read_code_names(path: Optional[str]) -> Dict[str, str]:
    """Load code->English name mapping from a CSV at `path` with columns: source,id,name,url.""" # function to read code_name file (it has terminology ID - english label correspondance)
    names: Dict[str, str] = {}
    if not path:
        return names
    p = Path(path)
    if not p.exists():
        print("error : read_code_names : no code_names.csv found")
        return names

    with p.open(newline="", encoding="utf-8") as f:  # open file and check if it has header
        sample = f.read(4096)
        f.seek(0)
        sniff = csv.Sniffer()
        try:
            has_header = sniff.has_header(sample)
        except Exception:
            has_header = True

        if not has_header:
            return names

        rdr = csv.DictReader(f)
        hdr_lower = [h.strip().lower() for h in (rdr.fieldnames or [])]  # read column names in lowercase, check if id and name are there
        if not {"id", "name"}.issubset(set(hdr_lower)):
            return names  # require at least id + name

        for r in rdr:
            src  = (r.get("source") or r.get("Source") or "").strip().lower()
            code = (r.get("id") or r.get("ID") or "").strip()
            name = (r.get("name") or r.get("Name") or "").strip()
            if not code or not name:
                continue

            # Primary key: normalized version of the raw id (no prefix assumed)
            k = normalize_code_key(code) if 'normalize_code_key' in globals() else code
            names.setdefault(k, name)

            # Aliases by source
            if src == "uniprot":
                acc = code.upper()
                names.setdefault(acc, name)                  # "A1A4S6"
                names.setdefault(f"UP:{acc}", name)         # "UP:A1A4S6"

            elif src in {"chebi"}:
                m = re.fullmatch(r"0*(\d+)", code)
                if m:
                    n = m.group(1)
                    names.setdefault(f"CHEBI:{n}", name)

            elif src in {"umls", "cui"}:
                cui = code.upper()
                if re.fullmatch(r"C\d+", cui):
                    names.setdefault(cui, name)             # "C123456"
                    names.setdefault(f"CUI:{cui}", name)    # "CUI:C123456"
                    names.setdefault(f"UMLS:{cui}", name)   # optional alias

            elif src in {"orphanet", "orpha"}:
                # Support both bare numeric IDs and "ORPHA:12345" forms
                raw = code.strip()
                # strip optional "ORPHA:" prefix
                num = re.sub(r"(?i)^ORPHA:", "", raw)
                num = num.lstrip("0") or num  # keep at least something if all zeros
                # map "ORPHA:<num>" and bare "<num>" to the same name
                names.setdefault(f"ORPHA:{num}", name)
                names.setdefault(num, name)

    return names


def normalize_code_key(code: str) -> str:  # normalize codes: prefixes, uppercasing, etc...
    c = (code or "").strip()
    c = re.sub(r"\s+", "", c)
    m = re.match(r"(?i)^(CHEBI|CHE):(\d+)$", c)
    if m:
        return f"CHEBI:{m.group(2)}"
    m = re.match(r"(?i)^CUI:(C\d+)$", c)
    if m:
        return f"CUI:{m.group(1).upper()}"
    if ":" in c:
        pfx, rest = c.split(":", 1)
        return f"{pfx.upper()}:{rest}"
    return c.upper()

# --------- LOINC part → tests + labels loaders ----------
def read_loinc_part_test_map(path: Optional[str]) -> Dict[str, List[str]]: # function to read the csv file with a LOINC_part:[LOINC_tests] dict 
    if not path:
        return {}
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)

    out: Dict[str, List[str]] = {}
    for k, v in (raw or {}).items():
        key = (k or "").strip().upper()
        if not key:
            continue
        vals = v if isinstance(v, list) else [v]
        cleaned = {str(x).strip() for x in vals if x is not None and str(x).strip()}
        out[key] = sorted(cleaned)
    return out

def read_loinc_labels(path: Optional[str]) -> Dict[str, Dict[str, str]]: # function to read the csv file with a LOINC_part_or_test:english_label dict
    empty = {"parts": {}, "tests": {}}
    if not path:
        return empty
    p = Path(path)
    if not p.exists():
        return empty

    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    def _norm(d):
        return { (k or "").strip().upper(): str(v or "") for k, v in (d or {}).items() } # normalize the dictionnary

    return {
        "parts": _norm(data.get("parts")), # normalized labels in 2 sub-dicts
        "tests": _norm(data.get("tests")),
    }

# --------- Render helpers ----------
def render_items_with_sources(
    codes: List[str],
    sources_per_item: List[List[str]],
    names_map: Dict[str, str]
) -> str:  # build HTML lists
    if not codes:
        return "<p>-</p>"
    lis = []
    for i, code in enumerate(codes):  # taking a list of terminologies IDs
        key = normalize_code_key(code)
        name = names_map.get(key)  # try to get their name in the mapping Dict
        if not name:
            name = code_fallback_label(code)  # display code itself if no name
        href = code_to_link(code)  # try to put a link on the item ID

        srcs = sources_per_item[i] if i < len(sources_per_item) else []
        if srcs:
            anchors = []
            multi = len(srcs) > 1
            for j, s in enumerate(srcs, 1):  # try to display 1 link per source
                s_clean = (s or "").strip()
                link = source_to_href(s_clean)

                # Detect PubMed IDs like "PMID:12345678" (case-insensitive, optional spaces)
                pm = re.match(r"(?i)^pmid\s*:\s*(\d+)\s*$", s_clean)
                if pm:
                    label = f"PMID:{pm.group(1)}"
                else:
                    label = "source" if not multi else f"source{j}"

                if link:
                    anchors.append(
                        f'<a href="{esc(link)}" target="_blank">{esc(label)}</a>'
                    )
                else:
                    anchors.append(esc(label))

            suffix = ' <small>(' + ", ".join(anchors) + ')</small>'
        else:
            suffix = ""  # no link if no source.

        if href and href != "#":
            lis.append(
                f'<li><a target="_blank" href="{esc(href)}">{esc(name)}</a>{suffix}</li>'
            )
        else:
            lis.append(f"<li>{esc(name)}{suffix}</li>")
    return "<ul>" + "".join(lis) + "</ul>"  # return HTML list with sources and their links


def code_fallback_label(code: str) -> str:  # function that replaces shortened terminology prefixes with full terminology name
    c = (code or "").strip()
    up = c.upper()
    if up.startswith("UP:"):
        return c.replace("UP:", "UniProt ")
    if up.startswith("CUI:"):
        return c
    if up.startswith("CHEBI:"):
        return c.replace("CHEBI:", "ChEBI ")
    if up.startswith("CHE:"):
        return "ChEBI " + re.sub(r"(?i)^CHE:", "", c)
    if up.startswith("ORPHA:"):
        return c.replace("ORPHA:", "Orphanet ")
    if up.startswith("OMIM:"):
        return c
    if up.startswith("SCTID:"):
        return "SNOMED CT " + c.split(":", 1)[1]
    return c

def render_loinc_tests_section(row: Dict[str, str],
                               loinc_map: Dict[str, List[str]],
                               loinc_labels: Dict[str, Dict[str, str]]) -> str:
    def norm_lp(s: str) -> str:  # normalize LOINC items
        return re.sub(
            r"[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\uFE63\uFF0D]",
            "-",
            (s or "").strip().upper()
        )

    parts_raw = split_pipes(row.get("loinc_part_id", ""))
    if not parts_raw:
        return ""
    parts = [norm_lp(p) for p in parts_raw]

    part_names = split_pipes(row.get("loinc_part") or row.get("loinc_part_name", ""))
    csv_label_by_part: Dict[str, str] = {}
    for pid, pname in zip(parts, part_names):
        pname = (pname or "").strip()
        if pname:
            csv_label_by_part[pid] = pname

    parts_labels = (loinc_labels.get("parts") or {})
    tests_labels = (loinc_labels.get("tests") or {})

    blocks = []
    for lp in parts:
        csv_name = csv_label_by_part.get(lp, "")
        lp_label = (csv_name or (parts_labels.get(lp) or "").strip() or lp)

        tests = loinc_map.get(lp, [])
        if tests:
            lis = []
            for t in tests:
                t_id = norm_lp(t)
                if not t_id:
                    continue
                t_label = (tests_labels.get(t_id) or "").strip() or t_id
                lis.append(
                    f'<li>{esc(t_label)} '
                    f'(<a target="_blank" href="{esc(loinc_url_org(t_id))}">{esc(t_id)}</a>)</li>'
                )
            ul = f'<div class="loinc-tests-scroll"><ul>{"".join(lis)}</ul></div>'
        else:
            ul = "<p>-</p>"

        blocks.append(
            f"""
            <div class="mb-3">
              <h5 class="section-title">
                LOINC part: {esc(lp_label)}
                (<a target="_blank" href="{esc(loinc_url_org(lp))}">{esc(lp)}</a>)
              </h5>
              <div class="card"><div class="card-body list-small">{ul}</div></div>
            </div>
            """
        )

    return f"""
    <section class="mb-4">
      <h3 class="section-title">LOINC tests</h3>
      {''.join(blocks)}
    </section>
    """

# --------- HTML skeleton (updated header + adaptive layout) ----------
HTML_HEAD = Template("""<!DOCTYPE html>
<html lang="en">
<head>
  <!-- Google Tag Manager -->
  <script>
    (function(w,d,s,l,i){ w[l]=w[l]||[];w[l].push({'gtm.start': new Date().getTime(),event:'gtm.js'});
      var f=d.getElementsByTagName(s)[0], j=d.createElement(s), dl=l!='dataLayer'?'&l='+l:'';
      j.async=true; j.src='https://www.googletagmanager.com/gtm.js?id='+i+dl; f.parentNode.insertBefore(j,f);
    })(window,document,'script','dataLayer','GTM-NTLRKKHC');
  </script>

  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="description" content="$meta_desc">
  <meta name="author" content="MAKAAO">
  <title>MAKAAO – $title</title>

  <link href="https://fonts.googleapis.com/css?family=Roboto:400,700&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css" crossorigin="anonymous">
  <link rel="stylesheet" href="https://cdn.datatables.net/1.13.4/css/dataTables.bootstrap4.min.css">
  <link rel="icon" href="/pictures/favicon.png" type="image/png">

  <style>
    :root{
      --banner-h: clamp(120px, 20vw, 220px);
    }
    body { font-family: 'Roboto', sans-serif; }
    h1 { text-align:center; font-weight:700; }
    .syns { text-align:center; color:#6c757d; margin-top:-.25rem; }
    .section-title { margin-bottom:.5rem; }
    .card-body ul { margin:0; }
    /* slightly distinct grey for sources and their links */
    .list-small li small,
    .list-small li small a {
      color:#5c636a;
    }

    /* Wider content container on large screens */
    @media (min-width:1200px){
      .container.container-wide{ max-width: 1320px; }
    }
    @media (min-width:1600px){
      .container.container-wide{ max-width: 1440px; }
    }

    /* Banner spacing */
    .banner-wrap{
      padding-top: 36px;    /* space from top of page */
      padding-bottom: 24px; /* space before navbar */
    }
    /* Two-image responsive banner */
    .banner-pair{
      display: flex;
      height: var(--banner-h);
      gap: 0;
    }
    .banner-pair a{
      flex: 1 1 50%;
      width: 50%;
      height: 100%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .banner-pair a img{
      max-height: 100%;
      max-width: 100%;
      height: 100%;
      width: auto;
      object-fit: contain;
      display: block;
    }
    /* Phone layout: stack banners */
    @media (max-width: 575.98px){
      .banner-pair{
        flex-direction: column;
        height: auto;
      }
      .banner-pair a{
        width: 100%;
        height: 140px;
      }
    }

    /* LOINC tests list */
    .loinc-tests-scroll { max-height: 240px; overflow-y: auto; padding-right: .25rem; }
    .loinc-tests-scroll ul { list-style: none; margin: 0; padding-left: 0; }
    .loinc-tests-scroll li { padding: .25rem .5rem; }
    .loinc-tests-scroll li:nth-child(odd) { background-color: #f8f9fa; }
  </style>
</head>
<body>
  <noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-NTLRKKHC" height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>

  <header class="bg-white">
    <div class="container container-wide banner-wrap">
      <div class="banner-pair">
        <a href="https://makaao.inria.fr">
          <img src="/pictures/makaao_logo_2.png"  alt="MAKAAO home">
        </a>
        <a href="https://www.filieresmaladiesrares.fr/">
          <img src="/pictures/funding.png"        alt="Filières Maladies Rares">
        </a>
      </div>

      <div id="button_bar" class="d-flex flex-wrap mb-3 mt-2">
        <a href="https://makaao.inria.fr" class="btn btn-primary mr-2 mb-2">Home</a>
        <a href="https://makaao.inria.fr/tree.html" class="btn btn-primary mr-2 mb-2">Autoantibody Tree</a>
        <a href="https://makaao.inria.fr/sparql.html" class="btn btn-primary mr-2 mb-2">SPARQL</a>
        <a href="https://makaao.inria.fr/download.html" class="btn btn-primary mr-2 mb-2">Download</a>
        <a href="https://makaao.inria.fr/contact.html" class="btn btn-primary mr-2 mb-2">Contact</a>
        <a href="https://makaao.inria.fr/about.html" class="btn btn-primary mr-2 mb-2">About</a>
      </div>
    </div>
  </header>
""")

# end of the HTML file
HTML_TAIL = """
  <footer class="bg-light text-center py-4">
    <img src="/pictures/footer.png" alt="Partner logos" class="img-fluid w-100 mb-2">
  </footer>
  <script defer src="https://code.jquery.com/jquery-3.6.0.min.js" crossorigin="anonymous"></script>
  <script defer src="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/js/bootstrap.bundle.min.js" crossorigin="anonymous"></script>
  <script defer src="https://cdn.datatables.net/1.13.4/js/jquery.dataTables.min.js"></script>
  <script defer src="https://cdn.datatables.net/1.13.4/js/dataTables.bootstrap4.min.js"></script>
</body>
</html>
"""

# function to build a full individual aab page
def render_page(
    row: Dict[str, str],
    id_to_name: Dict[str, str],
    children_of: Dict[str, List[str]],
    names_map: Dict[str, str],
    loinc_map: Dict[str, List[str]],
    loinc_labels: Dict[str, Dict[str, str]]
) -> str:
    aid = normalize_id(row.get("aab_id", ""))
    title = row.get("name_en", "").strip() or f"aab_{aid}"  # basic info aab_id, and name_en
    meta_desc = title

    syns = [s for s in split_pipes(row.get("syn_en", "")) if s]
    syn_html = ('<p class="syns">' + "; ".join(esc(s) for s in syns) + "</p>") if syns else ""

    # Targets (UP, CUI/UMLS, CHE/ChEBI)
    t_codes: List[str] = []
    t_sources_lists: List[List[str]] = []

    up_codes = split_pipes(row.get("uniprot_id", ""))
    up_srcs = split_sources_per_item(row.get("uniprot_source", ""), len(up_codes))
    t_codes += up_codes
    t_sources_lists += up_srcs

    cui_codes = split_pipes(row.get("umls_id", ""))
    cui_srcs = split_sources_per_item(row.get("umls_source", ""), len(cui_codes))
    t_codes += cui_codes
    t_sources_lists += cui_srcs

    che_codes = split_pipes(row.get("chebi_id", ""))
    che_srcs = split_sources_per_item(row.get("chebi_source", ""), len(che_codes))
    t_codes += che_codes
    t_sources_lists += che_srcs

    targets_html = render_items_with_sources(t_codes, t_sources_lists, names_map)

    # Diseases
    d_codes = split_pipes(row.get("disease_id", ""))
    d_srcs = split_sources_per_item(row.get("disease_source", ""), len(d_codes))
    diseases_html = render_items_with_sources(d_codes, d_srcs, names_map)

    # Parents
    parent_ids = [normalize_id(x) for x in split_pipes(row.get("parent_id", ""))]
    if parent_ids:
        pli = []
        for pid in parent_ids:
            if not pid:
                continue
            pname = id_to_name.get(pid, f"aab_{pid}")
            pli.append(f'<li><a href="{esc(page_href("aab_"+pid))}">{esc(pname)}</a></li>')
        parents_html = "<ul>" + "".join(pli) + "</ul>" if pli else "<p>-</p>"
    else:
        parents_html = "<p>-</p>"

    # Children
    kids = children_of.get(aid, [])
    if kids:
        li = [
            f'<li><a href="{esc(page_href("aab_"+cid))}">{esc(id_to_name.get(cid, "aab_"+cid))}</a></li>'
            for cid in sorted(kids, key=lambda x: (id_to_name.get(x, "").lower(), x))
        ]
        children_html = "<ul>" + "".join(li) + "</ul>"
    else:
        children_html = "<p>-</p>"

    # LOINC section
    loinc_html = render_loinc_tests_section(row, loinc_map, loinc_labels)

    # -------- Cross-references: HPO ----------
    raw_hpo = split_pipes(row.get("hpo_id", "") or row.get("hpo", ""))
    hpo_ids: List[str] = []
    seen_hpo = set()
    for x in raw_hpo:
        t = (x or "").strip().upper().replace("_", ":")
        t = re.sub(r"^HPO:", "HP:", t)
        m = re.fullmatch(r"HP:(\d+)", t)
        if m:
            t = f"HP:{m.group(1).zfill(7)}"
        elif re.fullmatch(r"\d{7}", t):
            t = f"HP:{t}"
        elif not re.fullmatch(r"HP:\d{7}", t):
            continue

        if t not in seen_hpo:
            seen_hpo.add(t)
            hpo_ids.append(t)

    if hpo_ids:
        hpo_lis = "".join(
            f'<li><a target="_blank" href="{esc(f"https://hpo.jax.org/browse/term/{hid}")}">{esc(hid)}</a></li>'
            for hid in hpo_ids
        )
        hpo_html = f"""
        <section class="mb-4">
          <h3 class="section-title">HPO</h3>
          <div class="card"><div class="card-body list-small"><ul>{hpo_lis}</ul></div></div>
        </section>
        """
    else:
        hpo_html = """
        <section class="mb-4">
          <h3 class="section-title">HPO</h3>
          <div class="card"><div class="card-body"><p>-</p></div></div>
        </section>
        """

    kg_uri = f"{BASE_KG}/aab_{aid}"
    kg_html = f'<p>{esc(title)} (<a target="_blank" href="{esc(kg_uri)}">MAK:AAB_{aid}</a>)</p>'

    head = HTML_HEAD.substitute(meta_desc=esc(meta_desc), title=esc(title))
    body = f"""
  <main class="container container-wide py-4">
    <h1 class="mb-2">{esc(title)}</h1>
    {syn_html}

    <section class="mb-4">
      <div class="row">
        <div class="col-md-6">
          <h3 class="section-title">Targets</h3>
          <div class="card"><div class="card-body list-small">{targets_html}</div></div>
        </div>
        <div class="col-md-6">
          <h3 class="section-title">Related diseases</h3>
          <div class="card"><div class="card-body list-small">{diseases_html}</div></div>
        </div>
      </div>
    </section>

    <section class="mb-4">
      <div class="row">
        <div class="col-md-6">
          <h3 class="section-title">Parents</h3>
          <div class="card"><div class="card-body">{parents_html}</div></div>
        </div>
        <div class="col-md-6">
          <h3 class="section-title">Children</h3>
          <div class="card"><div class="card-body">{children_html}</div></div>
        </div>
      </div>
    </section>

    <section class="mb-4">
      <h2 class="section-title">Cross-references</h2>

      {hpo_html}

      <section class="mb-4">
        <h3 class="section-title">Corresponding item in MAKAAO knowledge base</h3>
        <div class="card"><div class="card-body">{kg_html}</div></div>
      </section>

      {loinc_html}
    </section>
  </main>
"""
    return head + body + HTML_TAIL



# --------- Main ----------
def main():
    csv_path = makaao_csv_path
    rows = read_csv_rows(csv_path)

    # code_names.csv
    names_map = read_code_names(code_names)

    # LOINC part -> tests map
    loinc_map = read_loinc_part_test_map(LOINC_PART_TEST_JSON)
    if not loinc_map:
        print("[warn] loinc_part_test_dict.json not found or empty — LOINC section will be omitted.", file=sys.stderr)

    # LOINC labels
    loinc_labels = read_loinc_labels(LOINC_LABELS_JSON)
    if not (loinc_labels.get("parts") or loinc_labels.get("tests")):
        print("[warn] loinc_labels.json not found or empty — LOINC names will fall back to IDs.", file=sys.stderr)

    # Build name map and children map
    id_to_name: Dict[str, str] = {}
    children_of: Dict[str, List[str]] = defaultdict(list)
    for r in rows:
        aid = normalize_id(r.get("aab_id", ""))
        id_to_name[aid] = r.get("name_en", "").strip() or f"aab_{aid}"

    # Support multi-parents
    for r in rows:
        aid = normalize_id(r.get("aab_id", ""))
        parent_ids = [normalize_id(x) for x in split_pipes(r.get("parent_id", ""))]
        for pid in parent_ids:
            if pid:
                children_of[pid].append(aid)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug_map: Dict[str, str] = {}

    count = 0
    for r in rows:
        aid = normalize_id(r.get("aab_id", ""))
        slug = f"aab_{aid}"
        html_out = render_page(r, id_to_name, children_of, names_map, loinc_map, loinc_labels)
        (OUTPUT_DIR / f"{slug}.html").write_text(html_out, encoding="utf-8")
        slug_map[f"{BASE_KG}/aab_{aid}"] = slug
        count += 1

    (OUTPUT_DIR / "slug_map.json").write_text(json.dumps(slug_map, indent=2), encoding="utf-8") # write dict of slug for each aab to a json file

    print(f"CSV: {csv_path}")
    print(f"Rows read (non-empty aab_id): {len(rows)}")
    print(f"Pages written: {count}")
    if not names_map:
        print("[warn] code_names.csv not found — items will show codes instead of English names.", file=sys.stderr)

if __name__ == "__main__":
    main()
