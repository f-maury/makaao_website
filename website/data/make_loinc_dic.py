import re, json
from pathlib import Path
import pandas as pd

# --- inputs ---
CSV_PATH = "makaao_core.csv"     # CSV with column 'loinc_part_id'
TTL_PATH = "LOINC_2024-10-29.ttl"           # LOINC TTL file
OUT_JSON = "loinc_part_test_dict.json"      # {LP -> [test ids]}
OUT_LABELS_JSON = "loinc_labels.json"       # {"parts": {LP->label}, "tests": {TEST->label}}

# --- helpers ---
def split_pipes(cell: str):
    return [p.strip() for p in str(cell or "").split("|") if p and str(p).strip()] # separate elemnets of a string around "|", return as list

def tail_id(x: str) -> str | None: # filter a loinc string, to only retain the identifer
    s = str(x or "").strip()
    m = re.search(r'/LNC/([^/#>\s]+)>?$', s)
    if m: s = m.group(1)
    s = re.sub(r'^LNC[:/]', '', s, flags=re.I)
    return s.upper() if s else None

TEST_RE = re.compile(r'^\d{1,7}-\d{1,3}$')      # e.g., 61120-2
LP_RE   = re.compile(r'^LP\d+(?:-\d+)?$', re.I) # e.g., LP102314-4
def is_test_id(code: str) -> bool: return bool(TEST_RE.match(code or "")) # true if LOINC item code
def is_lp_part(code: str) -> bool: return bool(LP_RE.match(code or "")) # true if LOINC part code

# get object from LOINC "has_component" triples
HAS_COMPONENT_LINE = re.compile(
    r'(?:<http://purl\.bioontology\.org/ontology/LNC/has_component>|(?:^|\s)LNC:has_component)\s*<[^>]+?/LNC/([^>]+)>',
    re.IGNORECASE,
)

# get LOINC ID from triples where the subject is a LOINC item
SUBJ_START = re.compile(
    r'^\s*<[^>]+?/LNC/([^>]+)>\s+a\s+owl:Class\b',
    re.IGNORECASE
)

# get the prefLabel in English from a string
PREFLABEL_EN_LINE = re.compile(
    r'skos:prefLabel\s+(?P<q>"""|")(?P<label>.*?)(?P=q)@en\b',
    re.IGNORECASE
)
# English altLabel 
ALTLABEL_EN_TOKEN = re.compile(r'(?P<q>"""|")(?P<label>.*?)(?P=q)@en\b', re.IGNORECASE)

# --- 1) collect unique LP parts from CSV file where they are already listed-
df = pd.read_csv(CSV_PATH, dtype=str).fillna("")
if "loinc_part_id" not in df.columns:
    raise KeyError("Column 'loinc_part_id' not found in CSV")

parts = set()
for v in df["loinc_part_id"]:
    for tok in split_pipes(v):
        pid = tail_id(tok)
        if pid and is_lp_part(pid): # split to get the several LOINC parts ID per azab, if there are several
            parts.add(pid)

part_to_tests: dict[str, set[str]] = {p: set() for p in parts}
labels: dict[str, str] = {}  # initialize incomplete dicts

# --- 2) stream-parse TTL (has_component only, capture labels) ---
ttl_path = Path(TTL_PATH)
if not ttl_path.exists():
    raise FileNotFoundError(f"TTL not found: {TTL_PATH}") # open full LOINC terminology file

inside = False
cur_subj = None
cur_is_test = False
cur_pref_en = None
collecting_alt = False
cur_alt_en: list[str] = []

with ttl_path.open("r", encoding="utf-8", errors="ignore") as f: # logic to detect blocks of related rows inside the LOINC file
    for line in f:
        # detect start of a subject block
        m = SUBJ_START.match(line)
        if m:
            # if we were inside a previous block, finalize its label
            if inside and cur_subj:
                if cur_is_test:
                    chosen = max((s.strip() for s in cur_alt_en if s.strip()), key=len, default="") or (cur_pref_en or "").strip()
                else:
                    chosen = (cur_pref_en or "").strip()
                if chosen:
                    labels[cur_subj] = chosen

            # start new subject
            cur_subj = tail_id(m.group(1))
            cur_is_test = bool(cur_subj and is_test_id(cur_subj))
            inside = True
            cur_pref_en = None
            collecting_alt = False
            cur_alt_en = []

            # fall through to scan predicates on same line as header

        if not inside:
            continue

        # capture English prefLabel for this subject
        pm = PREFLABEL_EN_LINE.search(line)
        if pm and not cur_pref_en:
            cur_pref_en = pm.group("label").strip()

        # capture English altLabels for tests (prefer longest)
        if cur_is_test and ("skos:altLabel" in line or collecting_alt):
            # start or continue collecting
            if "skos:altLabel" in line:
                collecting_alt = True
            for mm in ALTLABEL_EN_TOKEN.finditer(line):
                lab = mm.group("label").strip()
                if lab:
                    cur_alt_en.append(lab)
            # altLabel list ends at ';' or '.'
            if ";" in line or line.strip().endswith("."):
                collecting_alt = False

        # only tests can have has_component -> LP parts
        if cur_is_test:
            for mm in HAS_COMPONENT_LINE.finditer(line):
                obj = tail_id(mm.group(1))
                if obj and is_lp_part(obj) and obj in part_to_tests:
                    part_to_tests[obj].add(cur_subj)

        # end of this subject block?
        if line.strip().endswith("."):
            # finalize label for this subject
            if cur_subj:
                if cur_is_test:
                    chosen = max((s.strip() for s in cur_alt_en if s.strip()), key=len, default="") or (cur_pref_en or "").strip() # for tests, we pick the longest english label (because it usually is more informative than short, abbreviated names)
                else:
                    chosen = (cur_pref_en or "").strip()
                if chosen:
                    labels[cur_subj] = chosen
            inside = False
            cur_subj = None
            cur_is_test = False
            cur_pref_en = None
            collecting_alt = False
            cur_alt_en = []

# --- 3) write JSONs ---
result = {p: sorted(list(v)) for p, v in part_to_tests.items()} # write a dict where LOINC parts are keys, and their associated LOINC tests are values
with open(OUT_JSON, "w", encoding="utf-8") as fh:
    json.dump(result, fh, ensure_ascii=False, indent=2)

all_tests = {t for tests in result.values() for t in tests}
labels_out = {
    "parts": {p: labels.get(p, "") for p in result.keys()}, # write a dict where ekys are ID of LOINC tests and parts, and values are their main english label
    "tests": {t: labels.get(t, "") for t in sorted(all_tests)},
}
with open(OUT_LABELS_JSON, "w", encoding="utf-8") as fh:
    json.dump(labels_out, fh, ensure_ascii=False, indent=2)

# --- 4) quick report ---
counts = (
    pd.DataFrame([(p, len(result[p])) for p in sorted(result.keys())],
                 columns=["loinc_part", "loinc_tests"])
    .sort_values(["loinc_tests","loinc_part"], ascending=[False, True])
    .reset_index(drop=True)
)

print(f"Unique CSV LP parts: {len(parts)}")
print(f"LP parts with ≥1 test (has_component): {sum(1 for v in result.values() if v)}")
print(f"Wrote: {OUT_JSON} and {OUT_LABELS_JSON}")
counts.head(20)
