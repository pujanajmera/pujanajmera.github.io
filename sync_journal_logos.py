#!/usr/bin/env python3
"""Synchronize local journal logo images into publications.html.

This script converts journal-name badge spans in publications.html into
local image badges sourced from the journal-logos folder. It will fail if a
required logo image file does not exist and print the exact filename to add.
"""

import argparse
import re
import sys
from pathlib import Path

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependencies. Install them with: pip install -r requirements.txt")
    sys.exit(1)

SUPPORTED_EXTENSIONS = [".svg", ".png", ".jpg", ".jpeg", ".webp"]


def parse_args():
    parser = argparse.ArgumentParser(
        description="Sync local journal logo image files into publications.html",
    )
    parser.add_argument(
        "--html",
        default="publications.html",
        help="HTML file to update (default: publications.html)",
    )
    parser.add_argument(
        "--logos",
        default="journal-logos",
        help="Folder containing journal logo image files (default: journal-logos)",
    )
    return parser.parse_args()


def clean_text(text):
    return " ".join(text.split()).strip()


def normalize_logo_filename(name):
    cleaned = re.sub(r"[^\w\s-]", "", (name or "")).strip().lower()
    return re.sub(r"[\s_]+", "-", cleaned)


def load_logo_index(logo_dir: Path):
    logo_files = {}
    for path in logo_dir.iterdir():
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            logo_files[path.stem.lower()] = path.name
    return logo_files


def find_logo_file(logo_files, slug):
    return logo_files.get(slug.lower())


def sync_logos(html_path: Path, logo_dir: Path):
    if not html_path.exists():
        print(f"Error: HTML file not found: {html_path}")
        sys.exit(1)
    if not logo_dir.exists():
        print(f"Error: Logo folder not found: {logo_dir}")
        sys.exit(1)

    soup = BeautifulSoup(html_path.read_text(encoding="utf-8"), "html.parser")
    logo_files = load_logo_index(logo_dir)
    missing = []
    updated = False

    for span in soup.select("span.journal-name-badge"):
        label = clean_text(span.get_text())
        if not label:
            continue

        slug = span.get("data-logo") or normalize_logo_filename(label)
        logo_filename = find_logo_file(logo_files, slug)
        if not logo_filename:
            missing.append((label, slug))
            continue

        wrapper = soup.new_tag("span")
        wrapper["class"] = "journal-badge journal-logo-badge"
        if span.has_attr("onclick"):
            wrapper["onclick"] = span["onclick"]
        if span.has_attr("title"):
            wrapper["title"] = span["title"]

        img = soup.new_tag("img")
        img["src"] = str(Path(logo_dir.name) / logo_filename)
        img["alt"] = f"{label} logo"
        img["loading"] = "lazy"
        wrapper.append(img)
        span.replace_with(wrapper)
        updated = True

    if missing:
        print("Missing journal logo files for the following badges:")
        for label, slug in missing:
            print(f"  {label} -> {logo_dir / (slug + '.svg')}")
        print("")
        print("Paste the corresponding logo image into the journal-logos folder and name it exactly as shown.")
        print("Supported extensions: .svg, .png, .jpg, .jpeg, .webp")
        print("Then rerun: python sync_journal_logos.py --html publications.html --logos journal-logos")
        sys.exit(1)

    if updated:
        html_path.write_text(str(soup), encoding="utf-8")
        print(f"Updated {html_path} with local journal logo images.")
    else:
        print("No journal-name badges found to sync in the HTML file.")


if __name__ == "__main__":
    args = parse_args()
    sync_logos(Path(args.html), Path(args.logos))
