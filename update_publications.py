#!/usr/bin/env python3
"""Update publications.html from ORCID, Crossref and OpenAlex.

Usage:
    python update_publications.py [--orcid ORCID_ID] [--refresh]

ORCID supplies the list of works. The first time a work appears, its metadata (title, full
author list, journal, volume, pages, year, BibTeX) is looked up on Crossref and saved to
publications-data.json, keyed by DOI. Later runs render known works from that file, so the
page stays the same even when a service is slow or down. Citation counts come from OpenAlex
on each run and are saved too, so a failed lookup keeps the last known counts.

To correct a work, edit its entry in publications-data.json and re-run; edits are kept.
--refresh looks every work up again (overwriting edits) except entries with "pinned": true.
Preprints are looked up again on every run, so new versions (and their titles) show up; they
link to the newest version. A preprint is hidden once its published version is also on ORCID.

Graphical (TOC) abstracts for journal articles are downloaded into images/papers/ from PubMed
Central's open-access subset, or else from the Alexandrova lab's publications page. For other
papers, save the image there yourself (see ABSTRACT_IMAGE_DIR); saved images are never replaced.

All of these services allow automated access, so this runs daily in GitHub Actions
(.github/workflows/update-publications.yml).
"""

import argparse
import html
import json
import re
import sys
import time
import unicodedata
from itertools import groupby
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependencies. Install them with: pip install -r requirements.txt")
    sys.exit(1)

ORCID_ID = "0000-0001-9509-6807"
AUTHOR_NAME = "P Ajmera"
DATA_FILE = Path("publications-data.json")
HEADERS = {"User-Agent": "pujanajmera.github.io publications updater"}

# ORCID work types shown on the page (datasets, abstracts, etc. are left out).
INCLUDED_TYPES = {"journal-article", "preprint", "book-chapter", "conference-paper"}

# Preprint servers by DOI prefix, for records where Crossref doesn't name the server.
PREPRINT_PREFIXES = {
    "10.26434": "ChemRxiv",
    "10.1101": "bioRxiv",
    "10.64898": "bioRxiv",
    "10.48550": "arXiv",
    "10.21203": "Research Square",
}

# Optional graphical abstracts: images/papers/<doi slug>.<ext>, where the slug is
# the DOI with "/" replaced by "-" (e.g. 10.1021-acs.jctc.5c00138.png).
ABSTRACT_IMAGE_DIR = Path("images/papers")
ABSTRACT_IMAGE_EXTENSIONS = [".webp", ".png", ".jpg", ".jpeg", ".svg"]

# Formatting tags allowed through from Crossref titles (e.g. CO<sub>2</sub>, <i>PyCPET</i>).
TITLE_TAGS = ("i", "b", "sub", "sup")


def parse_args():
    parser = argparse.ArgumentParser(description="Update publications.html from ORCID, Crossref and OpenAlex.")
    parser.add_argument("--orcid", default=ORCID_ID, help=f"ORCID iD (default: {ORCID_ID})")
    parser.add_argument("--output", default="publications.html", help="Output HTML filename")
    parser.add_argument("--refresh", action="store_true", help="Look up every work on Crossref again (except pinned entries)")
    return parser.parse_args()


def get(url, **kwargs):
    """GET with retries when rate-limited (429/503), waiting as long as the server asks."""
    headers = {**HEADERS, **kwargs.pop("headers", {})}
    for attempt in range(4):
        response = requests.get(url, headers=headers, timeout=30, **kwargs)
        if response.status_code not in (429, 503):
            break
        wait = response.headers.get("Retry-After", "")
        time.sleep(min(30, int(wait)) if wait.isdigit() else 2 ** (attempt + 1))
    response.raise_for_status()
    return response


def clean_text(text):
    return " ".join((text or "").split()).strip()


def clean_doi(doi):
    """Normalize a DOI, dropping suffixes like "/v2" or "v2" (preprint versions, so links go
    to the latest version), ".s001" (supporting information) and ".abstract"."""
    doi = re.sub(r"^https?://(dx\.)?doi\.org/", "", doi.strip(), flags=re.I)
    doi = re.sub(r"(\.abstract|\.full|\.full\.pdf|\.pdf)$", "", doi)
    doi = re.sub(r"(/v\d+|(?<=\d)v\d+|\.s\d{3})$", "", doi)
    return doi.rstrip("./").lower()


def normalize_title(title):
    # Crossref titles can contain formatting tags (<i>…</i>) and entities (&gt;).
    title = html.unescape(re.sub(r"<[^>]+>", "", title or ""))
    return re.sub(r"[^a-z0-9]", "", title.lower())


# ---------- ORCID: the list of works ----------

def fetch_orcid_works(orcid):
    """Works on the ORCID record as dicts, newest first, in the types the page shows."""
    groups = get(f"https://pub.orcid.org/v3.0/{orcid}/works", headers={"Accept": "application/json"}).json()["group"]
    works = []
    for group in groups:
        summary = group["work-summary"][0]
        if summary["type"] not in INCLUDED_TYPES:
            continue
        ids = {e["external-id-type"]: e["external-id-value"] for e in group["external-ids"]["external-id"]}
        year = ((summary.get("publication-date") or {}).get("year") or {}).get("value")
        works.append({
            "doi": clean_doi(ids["doi"]) if ids.get("doi") else None,
            "doi_raw": ids["doi"].strip().lower() if ids.get("doi") else None,
            "title": clean_text(summary["title"]["title"]["value"]),
            "journal": clean_text((summary.get("journal-title") or {}).get("value")),
            "year": int(year) if year else None,
            "preprint": summary["type"] == "preprint",
        })
    return works


# ---------- Crossref: metadata, saved to the data file ----------

def lookup_doi_by_title(title, preprint=False):
    """Find a DOI on Crossref whose title matches exactly (ignoring case, punctuation and
    formatting tags), for ORCID works that have no DOI."""
    try:
        items = get(
            "https://api.crossref.org/works",
            params={"query.bibliographic": title, "rows": 10, "select": "DOI,title,type"},
        ).json()["message"]["items"]
    except (requests.RequestException, ValueError, KeyError):
        return None
    wanted = normalize_title(title)
    # "component" records are supporting-information files that share the paper's title.
    matches = [item for item in items
               if item.get("type") != "component"
               and any(normalize_title(t) == wanted for t in item.get("title", []))]
    preferred = "posted-content" if preprint else "journal-article"
    matches.sort(key=lambda item: item.get("type") != preferred)
    return clean_doi(matches[0]["DOI"]) if matches else None


def fetch_bibtex(doi):
    """Fetch a BibTeX entry for a DOI via doi.org content negotiation."""
    try:
        response = get(f"https://doi.org/{doi}", headers={"Accept": "application/x-bibtex; charset=utf-8"})
    except requests.RequestException:
        return None
    response.encoding = "utf-8"
    # Crossref titles can carry HTML formatting tags (e.g. <i>PyCPET</i>); BibTeX wants plain text.
    entry = re.sub(r"</?(?:i|b|em|strong|sub|sup|scp)>", "", response.text).strip()
    return entry if entry.startswith("@") else None


def clean_title(title):
    """Crossref title as safe HTML: entities decoded, only simple formatting tags kept."""
    text = html.escape(html.unescape(clean_text(title)), quote=False)
    tags = "|".join(TITLE_TAGS)
    return re.sub(rf"&lt;(/?)({tags})&gt;", r"<\1\2>", text)


def crossref_record(doi):
    try:
        return get(f"https://api.crossref.org/works/{doi}").json()["message"]
    except (requests.RequestException, ValueError, KeyError):
        return None


def preprint_versions(doi, first):
    """Crossref records for each version of a preprint, oldest first: "<doi>/v1", "<doi>/v2", ...
    Newer ChemRxiv DOIs only exist with a version suffix; older ones use the bare DOI (`first`,
    if found) as v1 and add "/v2" onward. Other servers give just `first`."""
    versions = [first] if first else []
    number = 1
    while True:
        record = crossref_record(f"{doi}/v{number}")
        if record:
            versions.append(record)
        elif number > 1 or not first:
            return versions
        number += 1


def doi_resolves(doi):
    try:
        response = requests.head(f"https://doi.org/{doi}", headers=HEADERS, timeout=30)
    except requests.RequestException:
        return False
    return response.status_code in (301, 302, 303, 307, 308)


def resolve_work(work):
    """Look a work up on Crossref. Returns a data-file entry, or None if not found."""
    doi = work["doi"] or lookup_doi_by_title(work["title"], work["preprint"])
    if not doi:
        return None
    record = crossref_record(doi)
    link_doi, first = doi, record
    if work["preprint"] or doi.split("/")[0] in PREPRINT_PREFIXES:
        versions = preprint_versions(doi, record)
        if versions:
            # Metadata from the newest version, year from the first; link to the bare DOI
            # (which always points at the newest version) unless it doesn't resolve.
            first, record = versions[0], versions[-1]
            if not doi_resolves(doi):
                link_doi = record["DOI"].lower()
    if record is None and work.get("doi_raw"):
        record = first = crossref_record(work["doi_raw"])
        link_doi = work["doi_raw"]
    if record is None:
        return None
    authors = []
    for author in record.get("author", []):
        if author.get("family"):
            authors.append([author.get("given", ""), author["family"]])
        elif author.get("name"):
            authors.append(["", author["name"]])
    date = (first.get("published") or first.get("issued") or {}).get("date-parts", [[None]])[0]
    preprint = work["preprint"] or record.get("type") == "posted-content"
    if preprint:
        servers = [i.get("name") for i in record.get("institution", []) if i.get("name")]
        venue = servers[0] if servers else PREPRINT_PREFIXES.get(doi.split("/")[0], "Preprint")
    else:
        venue = (record.get("short-container-title") or record.get("container-title") or [work["journal"]])[0]
    return {
        "doi": doi,
        "link_doi": link_doi,
        "title": clean_title((record.get("title") or [work["title"]])[0]),
        "authors": authors,
        "venue": venue,
        "volume": record.get("volume", ""),
        "pages": record.get("page", "") or record.get("article-number", ""),
        "year": date[0] if date and date[0] else work["year"],
        "preprint": preprint,
        "published_as": [clean_doi(r["id"]) for r in record.get("relation", {}).get("is-preprint-of", []) if r.get("id-type") == "doi"],
        "bibtex": fetch_bibtex(record.get("DOI", link_doi).lower()),
    }


def load_data():
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {}


def save_data(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------- PubMed Central: graphical abstracts ----------
# Articles in PMC's open-access subset are mirrored, with their figures, in the
# pmc-oa-opendata bucket on AWS (https://pmc.ncbi.nlm.nih.gov/tools/pmcaws/).

PMC_BUCKET = "https://pmc-oa-opendata.s3.amazonaws.com"


def fetch_graphical_abstract(doi, pmcid):
    """Save an article's graphical (TOC) abstract from PMC's open-access bucket, if it has one."""
    try:
        listing = get(PMC_BUCKET, params={"list-type": "2", "prefix": f"PMC{pmcid}."}).text
        keys = re.findall(r"<Key>([^<]+)</Key>", listing)
        xml_keys = sorted((k for k in keys if k.endswith(".xml")), key=lambda k: int(k.split("/")[0].split(".")[1]))
        if not xml_keys:
            return None  # not in the open-access subset
        folder = xml_keys[-1].split("/")[0]  # newest version
        xml = get(f"{PMC_BUCKET}/{xml_keys[-1]}").text
        match = (re.search(r'<abstract[^>]*abstract-type="(?:toc|graphical)"[^>]*>(?:(?!</abstract>).)*?xlink:href="([^"]+)"', xml, re.S)
                 or re.search(r'<graphic\b[^>]*\bid="ga"[^>]*\bxlink:href="([^"]+)"', xml))
        if not match:
            return None
        name = Path(match.group(1)).stem
        image_key = next((k for k in keys if k.startswith(folder + "/") and Path(k).stem == name), None)
        if not image_key:
            return None
        image = get(f"{PMC_BUCKET}/{image_key}").content
    except requests.RequestException:
        return None
    ABSTRACT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = ABSTRACT_IMAGE_DIR / (abstract_image_slug(doi) + Path(image_key).suffix.lower())
    path.write_bytes(image)
    return path


# ---------- Alexandrova lab website: TOC images ----------
# The lab's publications page shows each paper's TOC graphic beside a link to its DOI.

LAB_PUBLICATIONS_URL = "https://alexandrova.chem.ucla.edu/publications/"


def fetch_lab_images():
    """{doi: image URL} from the lab's publications page, or {} if it can't be reached."""
    try:
        page = get(LAB_PUBLICATIONS_URL).text
    except requests.RequestException:
        return {}
    images = {}
    for item in page.split('<li class="wp-block-post')[1:]:
        dois = re.findall(r'href="https?://[^"]*?(10\.\d{4,}/[^"?#\s]+)', item)
        srcset = re.search(r'<img[^>]*\bsrcset="([^"]+)"', item)
        if not dois or not srcset:
            continue
        # The smallest size at least 600px wide (sharp at the page's ~150px), else the largest.
        sizes = sorted((int(w), url) for url, w in re.findall(r"(\S+)\s+(\d+)w", srcset.group(1)))
        url = next((url for w, url in sizes if w >= 600), sizes[-1][1])
        images.setdefault(clean_doi(dois[0]), url)
    return images


def save_image(doi, url):
    try:
        image = get(url).content
    except requests.RequestException:
        return None
    ABSTRACT_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    path = ABSTRACT_IMAGE_DIR / (abstract_image_slug(doi) + Path(url.split("?")[0]).suffix.lower())
    path.write_bytes(image)
    return path


def fetch_missing_graphical_abstracts(publications):
    """Download graphical abstracts for journal articles that don't have an image yet, from
    PubMed Central or else the lab website. Returns how many were found."""
    missing = [pub["entry"] for pub in publications
               if pub["entry"] and not pub["entry"]["preprint"] and not find_abstract_image(pub["entry"]["doi"])]
    lab_images = fetch_lab_images() if missing else {}
    found = 0
    for entry in missing:
        if entry.get("pmcid") and fetch_graphical_abstract(entry["doi"], entry["pmcid"]):
            found += 1
        elif entry["doi"] in lab_images and save_image(entry["doi"], lab_images[entry["doi"]]):
            found += 1
    return found


# ---------- OpenAlex: citation counts and PubMed Central ids ----------

def author_key(given, family):
    """First initial and family name, without case or accents: "a sadun", "d bim"."""
    name = f"{given.strip()[:1]} {family.split()[-1] if family.split() else ''}"
    return unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()


def fetch_openalex(dois):
    """{doi: (cited_by_count, PMC id or None, corresponding authors as author_key()s)} from
    OpenAlex, or {} if it can't be reached."""
    counts = {}
    for start in range(0, len(dois), 50):
        batch = dois[start:start + 50]
        try:
            results = get(
                "https://api.openalex.org/works",
                params={"filter": "doi:" + "|".join(batch), "select": "doi,cited_by_count,ids,authorships", "per-page": 50},
            ).json()["results"]
        except (requests.RequestException, ValueError, KeyError):
            return {}
        for work in results:
            if work.get("doi"):
                pmcid = (work.get("ids") or {}).get("pmcid")
                corresponding = [author_key(a["author"]["display_name"], a["author"]["display_name"])
                                 for a in work.get("authorships", []) if a.get("is_corresponding")]
                counts[clean_doi(work["doi"])] = (work["cited_by_count"], pmcid.rstrip("/").split("/")[-1] if pmcid else None,
                                                  corresponding)
    return counts


def collect_publications(works, data, refresh=False):
    """Merge ORCID works with saved metadata, looking up only what is new."""
    publications, unresolved, resolved = [], [], 0
    for index, work in enumerate(works):
        entry = data.get(work["doi"]) if work["doi"] else None
        if entry is None or ((refresh or entry.get("preprint")) and not entry.get("pinned")):
            fresh = resolve_work(work)
            if fresh:
                if entry and entry.get("pinned"):
                    fresh["pinned"] = True
                for key in ("citations", "pmcid", "corresponding"):
                    if entry and key in entry:
                        fresh[key] = entry[key]
                data[fresh["doi"]] = entry = fresh
                resolved += 1
        if entry is None:
            unresolved.append(work["title"])
        publications.append({"index": index, "work": work, "entry": entry})

    # Hide a preprint once its published version is on the list too.
    articles = [pub for pub in publications if not is_preprint(pub)]
    article_dois = {pub["entry"]["doi"] for pub in articles if pub["entry"]}
    article_titles = {normalize_title(title_of(pub)) for pub in articles}
    publications = [pub for pub in publications if not (
        is_preprint(pub) and pub["entry"]
        and (set(pub["entry"].get("published_as", [])) & article_dois or normalize_title(title_of(pub)) in article_titles)
    )]

    counts = fetch_openalex([pub["entry"]["doi"] for pub in publications if pub["entry"]])
    for pub in publications:
        if pub["entry"] and pub["entry"]["doi"] in counts:
            pub["entry"]["citations"], pmcid, corresponding = counts[pub["entry"]["doi"]]
            if pmcid:
                pub["entry"]["pmcid"] = pmcid
            # Only replaced when OpenAlex knows them, so a list added by hand is kept.
            if corresponding:
                pub["entry"]["corresponding"] = corresponding

    publications.sort(key=lambda pub: (-(year_of(pub) or 0), pub["index"]))
    return publications, unresolved, resolved, bool(counts)


def year_of(pub):
    return pub["entry"]["year"] if pub["entry"] else pub["work"]["year"]


def title_of(pub):
    return pub["entry"]["title"] if pub["entry"] else pub["work"]["title"]


def is_preprint(pub):
    return pub["entry"]["preprint"] if pub["entry"] else pub["work"]["preprint"]


# ---------- Rendering ----------

def abstract_image_slug(doi):
    return doi.replace("/", "-")


def find_abstract_image(doi):
    if not doi:
        return None
    for ext in ABSTRACT_IMAGE_EXTENSIONS:
        path = ABSTRACT_IMAGE_DIR / (abstract_image_slug(doi) + ext)
        if path.exists():
            return path.as_posix()
    return None


def format_author_list(authors, corresponding=()):
    """Format authors as "S. S. Chaturvedi, P. Ajmera, ..." with the site owner underlined
    and corresponding authors (author_key()s, e.g. "a alexandrova") starred."""
    own_initial, own_family = AUTHOR_NAME.split()
    names = []
    for given, family in authors:
        initials = " ".join(part[0] + "." for part in re.split(r"[\s.]+", given) if part)
        name = html.escape(f"{initials} {family}".strip())
        if family.lower() == own_family.lower() and given[:1].upper() == own_initial:
            name = f'<span class="author-name">{name}</span>'
        if author_key(given, family) in corresponding:
            name += '<span class="corresponding" title="Corresponding author">*</span>'
        names.append(name)
    return ", ".join(names)


def format_venue(entry):
    """E.g. "J. Am. Chem. Soc. 147, 32225–32237 (2025)", journal in italics."""
    venue = f"<cite>{html.escape(entry['venue'])}</cite>"
    if not entry.get("preprint"):
        if entry.get("volume"):
            venue += f" {html.escape(entry['volume'])}"
        if entry.get("pages"):
            venue += f", {html.escape(entry['pages']).replace('-', '–')}"
    if entry.get("year"):
        venue += f" ({entry['year']})"
    return venue


def render_pub_item(pub):
    work, entry = pub["work"], pub["entry"]
    if entry:
        doi = entry.get("link_doi") or entry["doi"]
        title_html = entry["title"]
        authors_html = format_author_list(entry["authors"], entry.get("corresponding", []))
        venue_html = format_venue(entry)
        bibtex = entry.get("bibtex")
        citations = entry.get("citations")
    else:
        # Not found on Crossref yet: show what ORCID has.
        doi, bibtex, citations = work["doi"], None, None
        title_html = html.escape(work["title"])
        authors_html = ""
        venue_html = " ".join(filter(None, [f"<cite>{html.escape(work['journal'])}</cite>" if work["journal"] else "",
                                            f"({work['year']})" if work["year"] else ""]))

    citation_html = ""
    if citations:  # nothing shown for 0 or unknown
        citation_label = "citation" if citations == 1 else "citations"
        citation_html = f'<span class="citation-count" aria-label="{citations} {citation_label}">Cited by {citations}</span>'

    external = 'target="_blank" rel="noopener noreferrer"'
    paper_href = html.escape(f"https://doi.org/{doi}") if doi else ""
    title_link = f'<a class="paper-title-text" href="{paper_href}" {external}>{title_html}</a>' if doi else f'<span class="paper-title-text">{title_html}</span>'
    actions = [f'<a class="paper-action" href="{paper_href}" {external}>Paper</a>'] if doi else []
    bibtex_html = ""
    if bibtex:
        actions.append('<button class="paper-action" type="button" data-cite aria-expanded="false">Cite</button>')
        bibtex_html = f'<pre class="paper-bibtex" hidden>{html.escape(bibtex)}</pre>'

    figure_src = find_abstract_image(entry["doi"] if entry else work["doi"])
    figure_html = ""
    if figure_src:
        figure_html = f'<a class="paper-figure" href="{paper_href}" {external}><img src="{html.escape(figure_src)}" alt="Graphical abstract" loading="lazy" /></a>'

    return (
        f'<li class="paper-card{" has-figure" if figure_html else ""}">'
        f'  <div class="paper-info">'
        f'    <div class="paper-title">{title_link}</div>'
        f'    <div class="paper-authors">{authors_html}</div>'
        f'    <div class="paper-meta-row"><div class="paper-meta">{venue_html}</div>{citation_html}</div>'
        f'    <div class="paper-actions">{"".join(actions)}</div>'
        f'    {bibtex_html}'
        f'  </div>'
        f'{figure_html}'
        f'</li>'
    )


def render_paper_list(pubs):
    return '  <ol class="paper-list">\n' + "\n".join(render_pub_item(pub) for pub in pubs) + "\n  </ol>\n"


def build_publications_sections(publications):
    """Preprints first, then journal articles grouped under year headings (newest first)."""
    preprints = [pub for pub in publications if is_preprint(pub)]
    articles = [pub for pub in publications if not is_preprint(pub)]
    sections = []
    if preprints:
        sections.append("<section>\n  <h2>Preprints</h2>\n" + render_paper_list(preprints) + "</section>\n")
    if articles:
        years = "".join(
            f'  <h3 class="paper-year">{year or "Undated"}</h3>\n' + render_paper_list(list(group))
            for year, group in groupby(articles, key=year_of)
        )
        sections.append("<section>\n  <h2>Journal articles</h2>\n" + years + "</section>\n")
    return "".join(sections)


def render_html(sections_html):
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Publications | Pujan Ajmera</title>
  <meta name=\"description\" content=\"Publications and preprints by Pujan Ajmera.\" />
  <link rel=\"icon\" href=\"favicon.svg\" type=\"image/svg+xml\" />
  <link rel=\"apple-touch-icon\" href=\"images/apple-touch-icon.png\" />
  <meta property=\"og:type\" content=\"website\" />
  <meta property=\"og:site_name\" content=\"Pujan Ajmera\" />
  <meta property=\"og:title\" content=\"Publications | Pujan Ajmera\" />
  <meta property=\"og:description\" content=\"Publications and preprints by Pujan Ajmera.\" />
  <meta property=\"og:url\" content=\"https://pujanajmera.github.io/publications\" />
  <meta property=\"og:image\" content=\"https://pujanajmera.github.io/images/profile.jpg\" />
  <meta name=\"twitter:card\" content=\"summary\" />
  <link rel=\"stylesheet\" href=\"style.css\" />
  <script src=\"site-config.js\"></script>
  <script src=\"site.js\"></script>
  <script src=\"publications.js\"></script>
</head>
<body>
  <nav>
    <a href=\"/\">Home</a>
    <a href=\"research\">Research</a>
    <a href=\"publications\">Publications</a>
    <a href=\"software\">Software</a>
    <a class=\"cv-link\" href=\"documents/CV.pdf\" target=\"_blank\" rel=\"noopener\">CV</a>
    <a href=\"news\">News</a>
  </nav>
  <header>
    <h1>Publications</h1>
  </header>
  {sections_html}
  <p class=\"page-note\">* Corresponding author. Citation counts from <a href=\"https://openalex.org\" target=\"_blank\" rel=\"noopener noreferrer\">OpenAlex</a>.</p>
</body>
</html>"""


def main():
    args = parse_args()
    # If ORCID can't be reached this raises, and nothing is written: the page keeps its last version.
    works = fetch_orcid_works(args.orcid)
    if not works:
        print(f"No works found on ORCID record {args.orcid}; leaving the page unchanged.")
        sys.exit(1)

    data = load_data()
    publications, unresolved, resolved, counts_updated = collect_publications(works, data, refresh=args.refresh)
    save_data(data)
    figures = fetch_missing_graphical_abstracts(publications)

    out_path = Path(args.output)
    out_path.write_text(render_html(build_publications_sections(publications)), encoding="utf-8")
    print(f"Updated {out_path} with {len(publications)} publications "
          f"({resolved} looked up on Crossref; citation counts {'updated' if counts_updated else 'unchanged, OpenAlex unavailable'}; "
          f"{figures} TOC figures downloaded).")
    if unresolved:
        print("Not found on Crossref yet (shown as ORCID lists them; add a DOI to the work on ORCID if it has none):")
        for title in unresolved:
            print(f"  {title}")


if __name__ == "__main__":
    main()
