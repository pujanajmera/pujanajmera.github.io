#!/usr/bin/env python3
"""Update publications.html from a Google Scholar profile.

Usage:
    python update_publications.py [--id GOOGLE_SCHOLAR_ID]

The script scrapes the profile page, detects archive/preprint entries,
and writes a publications page with clickable publication cards.
"""

import argparse
import html
import json
import random
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Install them with: pip install -r requirements.txt")
    sys.exit(1)

from sync_journal_logos import clean_text, normalize_logo_filename, sync_logos

SCHOLAR_ID = "5FVbzIYAAAAJ"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
}

ARXIV_KEYWORDS = {
    "arxiv": "arXiv",
    "biorxiv": "bioRxiv",
    "chemrxiv": "ChemRxiv",
    "medrxiv": "medRxiv",
    "researchsquare": "Research Square",
}

_JACS = ("https://pubs.acs.org/journal/jacsat", "JACS")
_JCTC = ("https://pubs.acs.org/journal/jctcce", "JCTC")
_PNAS = ("https://www.pnas.org", "PNAS")
_CHEM_SCI = ("https://www.rsc.org/journals-books-databases/about-journals/chem-sci/", "Chemical Science")
_ANGEW = ("https://onlinelibrary.wiley.com/journal/15213773", "Angew. Chem. Int. Ed.")
_JPCB = ("https://pubs.acs.org/journal/jpcbfk", "J. Phys. Chem. B")
_JPCL = ("https://pubs.acs.org/journal/jpclcd", "J. Phys. Chem. Lett.")
_JPCA = ("https://pubs.acs.org/journal/jpcafh", "J. Phys. Chem. A")

# Keys are journal names as they appear at the start of a Scholar venue line
# (lowercase, without volume/pages/year). Matching is exact, so e.g.
# "Nature Communications" does not match "nature".
JOURNALS = {
    "nature": ("https://www.nature.com", "Nature"),
    "science": ("https://www.science.org", "Science"),
    "pnas": _PNAS,
    "proc natl acad sci": _PNAS,
    "proceedings of the national academy of sciences": _PNAS,
    "acs catal": ("https://pubs.acs.org/journal/accacs", "ACS Catal."),
    "acs catalysis": ("https://pubs.acs.org/journal/accacs", "ACS Catal."),
    "j. am. chem. soc.": _JACS,
    "jacs": _JACS,
    "journal of the american chemical society": _JACS,
    "j. chem. phys.": ("https://aip.scitation.org/journal/jcp", "JCP"),
    "the journal of chemical physics": ("https://aip.scitation.org/journal/jcp", "JCP"),
    "j. chem. theory comput.": _JCTC,
    "journal of chemical theory and computation": _JCTC,
    "chem. sci.": _CHEM_SCI,
    "chemical science": _CHEM_SCI,
    "angew. chem. int. ed.": _ANGEW,
    "angewandte chemie international edition": _ANGEW,
    "j. phys. chem. b": _JPCB,
    "the journal of physical chemistry b": _JPCB,
    "j. phys. chem. lett.": _JPCL,
    "the journal of physical chemistry letters": _JPCL,
    "j. phys. chem. a": _JPCA,
    "the journal of physical chemistry a": _JPCA,
    "chem. comm.": ("https://www.rsc.org/journals-books-databases/about-journals/chemcomm/", "Chem. Commun."),
    "chemical communications": ("https://www.rsc.org/journals-books-databases/about-journals/chemcomm/", "Chem. Commun."),
    "chemical reviews": ("https://pubs.acs.org/journal/chreay", "Chem. Rev."),
    "journal of chemical information and modeling": ("https://pubs.acs.org/journal/jcisd8", "J. Chem. Inf. Model."),
}

JOURNAL_LOGO_DIR = "journal-logos"


def parse_args():
    parser = argparse.ArgumentParser(description="Update publications.html from Google Scholar.")
    parser.add_argument("--id", default=SCHOLAR_ID, help=f"Google Scholar user ID (default: {SCHOLAR_ID})")
    parser.add_argument("--count", type=int, default=25, help="Number of publications to fetch")
    parser.add_argument("--output", default="publications.html", help="Output HTML filename")
    parser.add_argument("--cache-file", default="scholar-profile.html", help="Local cache file for Google Scholar profile HTML")
    parser.add_argument("--cache-only", action="store_true", help="Skip fetching and parse from the local scholar profile cache")
    return parser.parse_args()


def fetch_profile_page(scholar_id, count, cache_file=None):
    url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en&pagesize={count}"
    last_error = None
    for attempt in range(1, 5):
        try:
            response = requests.get(url, headers=HEADERS, timeout=15)
            response.raise_for_status()
            html = response.text
            if cache_file:
                Path(cache_file).write_text(html, encoding="utf-8")
            return html
        except requests.exceptions.HTTPError as exc:
            last_error = exc
            status = exc.response.status_code if exc.response is not None else None
            if status not in (429, 503):
                break
            sleep_seconds = min(10, 2 ** attempt + random.random())
            print(f"Rate limited by Scholar (status={status}), retrying in {sleep_seconds:.1f}s...")
            time.sleep(sleep_seconds)
        except requests.RequestException as exc:
            last_error = exc
            sleep_seconds = min(10, 2 ** attempt + random.random())
            print(f"Network error fetching Scholar page, retrying in {sleep_seconds:.1f}s...")
            time.sleep(sleep_seconds)

    if cache_file and Path(cache_file).exists():
        print(f"Warning: fetch failed; loading cached profile from {cache_file}")
        return Path(cache_file).read_text(encoding="utf-8")

    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to fetch Google Scholar profile page.")


def journal_name(venue_text):
    """Return the journal part of a venue line, e.g. "Chemical Science 17 (22), ..." -> "Chemical Science"."""
    return re.split(r",|\s\d", clean_text(venue_text or ""), maxsplit=1)[0].strip()


def match_journal(venue_text):
    """Return (url, badge_text) for a known journal, or None."""
    return JOURNALS.get(journal_name(venue_text).lower())


def fetch_public_link(citation_url):
    try:
        response = requests.get(citation_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
    except requests.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")
    title_link = soup.select_one("a.gsc_oci_title_link")
    if title_link and title_link.get("href"):
        return title_link["href"]
    return None


AUTHOR_NAME = "P Ajmera"


def get_archive_label(venue_text, direct_link):
    candidates = [venue_text or "", direct_link or ""]
    for raw in candidates:
        lower = raw.lower()
        for keyword, label in ARXIV_KEYWORDS.items():
            if keyword in lower:
                return label
    return None


def format_authors(authors):
    if not authors:
        return authors
    escaped_name = html.escape(AUTHOR_NAME)
    return html.escape(authors).replace(escaped_name, f'<span class="author-name">{escaped_name}</span>')


def js_open(url):
    """Build an onclick-safe window.open call for an HTML attribute."""
    return html.escape(f"window.open({json.dumps(url)}, '_blank')")


def parse_year(pub):
    if pub.get("year"):
        try:
            return int(pub["year"])
        except ValueError:
            pass
    if pub.get("venue_line"):
        match = re.search(r"(19|20)\d{2}", pub["venue_line"])
        if match:
            return int(match.group(0))
    return 0


def parse_citations(row):
    citation_tag = row.select_one("td.gsc_a_c a")
    if not citation_tag:
        return None
    citation_text = clean_text(citation_tag.text)
    if not citation_text:
        return 0
    try:
        return int(citation_text.replace(",", ""))
    except ValueError:
        return None


def find_publications(html):
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("tr.gsc_a_tr")
    publications = []

    for idx, row in enumerate(rows):
        title_tag = row.select_one("a.gsc_a_at")
        if not title_tag:
            continue

        title = clean_text(title_tag.text)
        scholar_link = urljoin("https://scholar.google.com", title_tag["href"])
        gray_lines = [clean_text(line.text) for line in row.select(".gs_gray")]
        authors = gray_lines[0] if len(gray_lines) > 0 else ""
        venue_line = gray_lines[1] if len(gray_lines) > 1 else ""
        year_tag = row.select_one("td.gsc_a_y span")
        year = clean_text(year_tag.text) if year_tag else ""
        citations = parse_citations(row)

        direct_link_tag = row.select_one(".gs_or_ggsm a")
        direct_link = None
        if direct_link_tag and direct_link_tag.get("href"):
            direct_link = urljoin("https://scholar.google.com", direct_link_tag["href"])
            if urlparse(direct_link).scheme == "":
                direct_link = "https://scholar.google.com" + direct_link

        publication_link = fetch_public_link(scholar_link)

        publications.append({
            "index": idx,
            "title": title,
            "scholar_link": scholar_link,
            "publication_link": publication_link,
            "direct_link": direct_link,
            "authors": authors,
            "venue_line": venue_line,
            "year": year,
            "citations": citations,
            "year_int": 0,
        })

    for pub in publications:
        pub["year_int"] = parse_year(pub)

    publications.sort(key=lambda item: (item["year_int"], item["index"]), reverse=True)
    total = len(publications)
    for idx, pub in enumerate(publications, start=1):
        pub["rank"] = total - idx + 1
    return publications


def render_pub_item(pub):
    archive_label = get_archive_label(pub["venue_line"], pub["direct_link"])
    journal_href = None
    journal_badge_html = ""

    if archive_label is None:
        journal = match_journal(pub["venue_line"])
        if journal:
            journal_href, badge_text = journal
            logo_key = normalize_logo_filename(badge_text)
            journal_badge_html = (
                f'<span class="journal-badge journal-name-badge" data-logo="{logo_key}" onclick="event.stopPropagation(); {js_open(journal_href)};" title="Open journal website">'
                f'{html.escape(badge_text)}'
                f'</span>'
            )
        else:
            journal_text = journal_name(pub["venue_line"])
            if journal_text:
                journal_badge_html = f'<span class="journal-badge text-badge">{html.escape(journal_text)}</span>'

    label_html = ""
    if archive_label:
        label_html = f'<span class="label arxiv">{archive_label}</span>'

    venue_html = html.escape(clean_text(pub["venue_line"]))
    if journal_href and venue_html:
        venue_html = f'<a class="venue-link" href="{html.escape(journal_href)}" target="_blank" rel="noopener noreferrer">{venue_html}</a>'

    meta_parts = [format_authors(pub["authors"]) ] if pub["authors"] else []
    if venue_html:
        meta_parts.append(venue_html)
    elif pub.get("year"):
        meta_parts.append(html.escape(pub["year"]))

    meta_html = " | ".join(meta_parts)

    citation_html = ""
    if pub.get("citations") is not None:
        citation_label = "citation" if pub["citations"] == 1 else "citations"
        citation_html = (
            f'<span class="citation-count" aria-label="{pub["citations"]} {citation_label}">'
            f'Cited by {pub["citations"]}'
            f'</span>'
        )

    link_target = pub.get("publication_link") or pub["direct_link"] or pub["scholar_link"]
    number_html = ""
    if pub.get("rank") is not None:
        number_html = f'<span class="paper-number">{pub["rank"]}</span>'
    return (
        f'<li class="paper-card" onclick="{js_open(link_target)}">'
        f'  <div class="paper-info">'
        f'    <div class="paper-title">{number_html}<span class="paper-title-text">{html.escape(pub["title"])}</span> {label_html}</div>'
        f'    <div class="paper-meta-row"><div class="paper-meta">{meta_html}</div>{citation_html}</div>'
        f'  </div>'
        f'  <div class="paper-logo">{journal_badge_html}</div>'
        f'</li>'
    )


def build_publications_sections(publications):
    recent_items = []
    old_items = []

    for pub in publications:
        item_html = render_pub_item(pub)
        if pub["year_int"] and pub["year_int"] < 2022:
            old_items.append(item_html)
        else:
            recent_items.append(item_html)

    return recent_items, old_items


def render_html(recent_items_html, old_items_html):
    recent_section = (
        "<section>\n"
        "  <h2>Publications/Preprints from graduate studies</h2>\n"
        "  <ol class=\"paper-list\">\n"
        f"{chr(10).join(recent_items_html)}\n"
        "  </ol>\n"
        "</section>\n"
    ) if recent_items_html else ""

    old_section = (
        "<section>\n"
        "  <h2>Publications before graduate studies</h2>\n"
        "  <ol class=\"paper-list\">\n"
        f"{chr(10).join(old_items_html)}\n"
        "  </ol>\n"
        "</section>\n"
    ) if old_items_html else ""

    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>Publications + Preprints | Pujan Ajmera</title>
  <meta name=\"description\" content=\"Publications and preprints by Pujan Ajmera.\" />
  <link rel=\"icon\" href=\"favicon.svg\" type=\"image/svg+xml\" />
  <link rel=\"apple-touch-icon\" href=\"images/apple-touch-icon.png\" />
  <meta property=\"og:type\" content=\"website\" />
  <meta property=\"og:site_name\" content=\"Pujan Ajmera\" />
  <meta property=\"og:title\" content=\"Publications + Preprints | Pujan Ajmera\" />
  <meta property=\"og:description\" content=\"Publications and preprints by Pujan Ajmera.\" />
  <meta property=\"og:url\" content=\"https://pujanajmera.github.io/publications.html\" />
  <meta property=\"og:image\" content=\"https://pujanajmera.github.io/images/profile.jpg\" />
  <meta name=\"twitter:card\" content=\"summary\" />
  <link rel=\"stylesheet\" href=\"style.css\" />
  <script src=\"site-config.js\"></script>
  <script src=\"site.js\"></script>
</head>
<body>
  <nav>
    <a href=\"index.html\">Home</a>
    <a href=\"publications.html\">Publications</a>
    <a class=\"cv-link\" href=\"cv.html\">CV</a>
    <a href=\"repos.html\">Repositories</a>
    <a href=\"news.html\">News</a>
  </nav>
  <header>
    <h1>Publications + Preprints</h1>
  </header>
  {recent_section}
  {old_section}
  <footer>
    <p>Generated from Google Scholar content. Preprints are labeled by archive type.</p>
  </footer>
</body>
</html>"""


def main():
    args = parse_args()
    if args.cache_only:
        cache_path = Path(args.cache_file)
        if not cache_path.exists():
            print(f"Cache-only mode requested but cache file does not exist: {cache_path}")
            sys.exit(1)
        html = cache_path.read_text(encoding="utf-8")
    else:
        html = fetch_profile_page(args.id, args.count, cache_file=args.cache_file)

    publications = find_publications(html)
    if not publications:
        print("No publications found. Check your Google Scholar ID or page visibility.")
        sys.exit(1)

    recent_items, old_items = build_publications_sections(publications)
    output_html = render_html(recent_items, old_items)
    out_path = Path(args.output)
    out_path.write_text(output_html, encoding="utf-8")
    print(f"Updated {out_path} with {len(publications)} publications.")

    sync_logos(out_path, Path(JOURNAL_LOGO_DIR))


if __name__ == "__main__":
    main()
