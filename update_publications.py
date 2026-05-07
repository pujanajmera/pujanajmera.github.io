#!/usr/bin/env python3
"""Update publications.html from a Google Scholar profile.

Usage:
    python update_publications.py --id YOUR_GOOGLE_SCHOLAR_ID

The script scrapes the profile page, detects archive/preprint entries,
and writes a publications page with clickable publication cards.
"""

import argparse
import datetime
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Install them with: pip install -r requirements.txt")
    sys.exit(1)

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

JOURNAL_LOOKUP = {
    "nature": "https://www.nature.com",
    "science": "https://www.science.org",
    "pnas": "https://www.pnas.org",
    "acs catal": "https://pubs.acs.org/journal/accacs",
    "j. am. chem. soc.": "https://pubs.acs.org/journal/jacsat",
    "jacs": "https://pubs.acs.org/journal/jacsat",
    "j. chem. phys.": "https://aip.scitation.org/journal/jcp",
    "j. chem. theory comput.": "https://pubs.acs.org/journal/jctcce",
    "chem. sci.": "https://www.rsc.org/journals-books-databases/about-journals/chem-sci/",
    "anengw. chem. int. ed.": "https://onlinelibrary.wiley.com/journal/15213773",
    "chem": "https://pubs.acs.org",
    "proc natl acad sci": "https://www.pnas.org",
    "j. phys. chem. b": "https://pubs.acs.org/journal/jpcbfk",
    "j. phys. chem. lett.": "https://pubs.acs.org/journal/jpclcd",
    "j. phys. chem. a": "https://pubs.acs.org/journal/jpcafh",
    "chem. comm.": "https://www.rsc.org/journals-books-databases/about-journals/chemcomm/",
}


def parse_args():
    parser = argparse.ArgumentParser(description="Update publications.html from Google Scholar.")
    parser.add_argument("--id", required=True, help="Google Scholar user ID")
    parser.add_argument("--count", type=int, default=25, help="Number of publications to fetch")
    parser.add_argument("--output", default="publications.html", help="Output HTML filename")
    return parser.parse_args()


def fetch_profile_page(scholar_id, count):
    url = f"https://scholar.google.com/citations?user={scholar_id}&hl=en&pagesize={count}"
    response = requests.get(url, headers=HEADERS, timeout=15)
    response.raise_for_status()
    return response.text


def clean_text(text):
    return " ".join(text.split()).strip()


def guess_journal_link(venue_text):
    if not venue_text:
        return None
    lower = venue_text.lower()
    for key, link in JOURNAL_LOOKUP.items():
        if key in lower:
            return link
    return None


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
    return authors.replace(AUTHOR_NAME, f'<span class="author-name">{AUTHOR_NAME}</span>')


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
            "year_int": 0,
        })

    for pub in publications:
        pub["year_int"] = parse_year(pub)

    publications.sort(key=lambda item: (item["year_int"], item["index"]), reverse=True)
    return publications


def render_pub_item(pub):
    link_target = pub["direct_link"] or pub["scholar_link"]
    archive_label = get_archive_label(pub["venue_line"], pub["direct_link"])
    is_archive = archive_label is not None
    journal_href = None
    journal_badge_html = ""

    if not is_archive:
        journal_href = guess_journal_link(pub["venue_line"])
        if journal_href:
            parsed = urlparse(journal_href)
            journal_logo_url = f"https://logo.clearbit.com/{parsed.netloc}"
            journal_badge_html = (
                f'<span class="journal-badge" onclick="event.stopPropagation(); window.open(\'{journal_href}\', \'_blank\');" title="Open journal website">'
                f'<img src="{journal_logo_url}" alt="Journal logo" loading="lazy" onerror="this.style.display=\'none\'" />'
                f'</span>'
            )
        else:
            journal_text = pub["venue_line"].split(",")[0] if pub["venue_line"] else ""
            if journal_text:
                journal_badge_html = f'<span class="journal-badge text-badge">{journal_text}</span>'

    label_html = ""
    if archive_label:
        label_html = f'<span class="label arxiv">{archive_label}</span>'

    venue_html = clean_text(pub["venue_line"])
    if journal_href and venue_html:
        venue_html = f'<a class="venue-link" href="{journal_href}" target="_blank" rel="noopener noreferrer">{venue_html}</a>'

    meta_parts = [format_authors(pub["authors"]) ] if pub["authors"] else []
    if venue_html:
        meta_parts.append(venue_html)
    elif pub.get("year"):
        meta_parts.append(pub["year"])

    meta_html = " | ".join(meta_parts)

    link_target = pub.get("publication_link") or pub["direct_link"] or pub["scholar_link"]
    return (
        f'<li class="paper-card" onclick="window.open(\'{link_target}\', \'_blank\')">'
        f'  <div class="paper-title"><span class="paper-title-text">{pub["title"]}</span> {label_html} {journal_badge_html}</div>'
        f'  <div class="paper-meta">{meta_html}</div>'
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


def render_html(recent_items_html, old_items_html, scholar_id):
    updated = datetime.date.today().strftime("%B %d, %Y")
    recent_section = (
        "<section>\n"
        "  <h2>Publications</h2>\n"
        "  <ol>\n"
        f"{chr(10).join(recent_items_html)}\n"
        "  </ol>\n"
        "</section>\n"
    ) if recent_items_html else ""

    old_section = (
        "<section>\n"
        "  <h2>Papers before graduate studies</h2>\n"
        "  <ol>\n"
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
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 0; padding: 2rem; max-width: 760px; line-height: 1.6; color: #111; background: #f8f9fb; }}
    header {{ margin-bottom: 1.5rem; }}
    nav {{ margin-bottom: 1.5rem; }}
    nav a {{ margin-right: 1rem; color: #0366d6; text-decoration: none; }}
    nav a:hover {{ text-decoration: underline; }}
    section {{ background: #fff; border-radius: 10px; padding: 1.5rem; box-shadow: 0 1px 2px rgba(0,0,0,0.08); margin-bottom: 1.5rem; }}
    h1, h2 {{ margin-top: 0; }}
    ol {{ padding-left: 1.25rem; margin: 0; }}
    li {{ margin-bottom: 0; list-style: none; }}
    .paper-card {{ cursor: pointer; padding: 1rem; border-radius: 0.75rem; transition: background 0.16s ease; border-bottom: 1px solid rgba(0,0,0,0.08); }}
    .paper-card:last-child {{ border-bottom: none; }}
    .paper-card:hover {{ background: rgba(0,0,0,0.04); }}
    .paper-title {{ display: flex; align-items: center; flex-wrap: wrap; gap: 0.75rem; margin-bottom: 0.35rem; }}
    .paper-title-text {{ color: #111; font-weight: 600; text-decoration: none; }}
    .paper-title a {{ color: #111; font-weight: 600; text-decoration: none; }}
    .paper-title span {{ color: #111; font-weight: 600; text-decoration: none; }}
    .author-name {{ font-weight: 600; color: #111; }}
    .paper-meta {{ color: #444; font-size: 0.95rem; }}
    .label.arxiv {{ background:#bb0000; color:#fff; padding:0.18rem 0.45rem; border-radius:999px; font-size:0.78rem; text-transform:uppercase; letter-spacing:0.05em; }}
    .journal-badge {{ display:inline-flex; align-items:center; margin-left:0.35rem; }}
    .journal-badge img {{ width: 32px; height: 32px; object-fit: contain; border-radius: 6px; box-shadow: 0 0 0 1px rgba(0,0,0,0.08); }}
    .journal-badge.text-badge {{ display:inline-flex; align-items:center; background:#eef4ff; color:#0638a6; padding:0.25rem 0.5rem; border-radius:0.6rem; font-size:0.85rem; }}
    .venue-link {{ color: inherit; text-decoration: none; }}
    .venue-link:hover {{ text-decoration: none; }}
    footer {{ color:#666; font-size:0.95rem; }}
  </style>
</head>
<body>
  <header>
    <h1>Publications + Preprints</h1>
    <p>Updated from Google Scholar profile <strong>{scholar_id}</strong> on {updated}.</p>
  </header>
  <nav>
    <a href=\"index.html\">Home</a>
    <a href=\"publications.html\">Publications</a>
  </nav>
  {recent_section}
  {old_section}
  <footer>
    <p>Generated from Google Scholar content. Preprints are labeled by archive type.</p>
  </footer>
</body>
</html>"""


def main():
    args = parse_args()
    html = fetch_profile_page(args.id, args.count)
    publications = find_publications(html)
    if not publications:
        print("No publications found. Check your Google Scholar ID or page visibility.")
        sys.exit(1)

    recent_items, old_items = build_publications_sections(publications)
    output_html = render_html(recent_items, old_items, args.id)
    out_path = Path(args.output)
    out_path.write_text(output_html, encoding="utf-8")
    print(f"Updated {out_path} with {len(publications)} publications.")


if __name__ == "__main__":
    main()
