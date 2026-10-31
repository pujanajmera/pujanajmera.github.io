#!/usr/bin/env python3
"""Generate a static repos.html file from GitHub repository contributions."""

import html
import os
import sys
import textwrap
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: requests. Install with pip install requests")
    sys.exit(1)

GITHUB_API_URL = "https://api.github.com/graphql"
USERNAME = "pujanajmera"
OUTPUT_FILE = Path("repos.html")
TOKEN = os.getenv("GITHUB_TOKEN")

if not TOKEN:
    print("Missing GITHUB_TOKEN environment variable.")
    print("In GitHub Actions, use the built-in GITHUB_TOKEN or set a personal access token.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"bearer {TOKEN}",
    "Accept": "application/vnd.github.v3+json",
    "User-Agent": "github-actions-repo-generator",
}

QUERY = """
query Repos($login: String!, $first: Int!) {
  user(login: $login) {
    repositoriesContributedTo(first: $first, includeUserRepositories: true, privacy: PUBLIC, contributionTypes: [COMMIT, PULL_REQUEST], orderBy: {field: PUSHED_AT, direction: DESC}) {
      nodes {
        name
        owner { login }
        description
        url
        stargazerCount
        forkCount
        isFork
        updatedAt
        primaryLanguage { name }
        languages(first: 3, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            node { name }
          }
        }
      }
    }
  }
}
"""


def fetch_json(query, variables):
    response = requests.post(GITHUB_API_URL, json={"query": query, "variables": variables}, headers=HEADERS, timeout=30)
    response.raise_for_status()
    data = response.json()
    if data.get("errors"):
        raise RuntimeError(data["errors"])
    return data["data"]


def fetch_readme_snippet(owner, repo_name):
    url = f"https://api.github.com/repos/{owner}/{repo_name}/readme"
    response = requests.get(url, headers={**HEADERS, "Accept": "application/vnd.github.v3.raw"}, timeout=30)
    if response.status_code != 200:
        return None
    text = response.text
    if not text:
        return None
    snippet = textwrap.shorten(text.replace("\n", " ").strip(), width=220, placeholder="...")
    return snippet


def format_languages(repo_node):
    langs = [edge["node"]["name"] for edge in repo_node.get("languages", {}).get("edges", []) if edge.get("node") and edge["node"].get("name")]
    if not langs and repo_node.get("primaryLanguage"):
        langs = [repo_node["primaryLanguage"]["name"]]
    return langs[:3]


def html_escape(text):
    return html.escape(text or "")


def render_repo(repo_node, description, languages):
    title = html_escape(repo_node["name"])
    url = repo_node["url"]
    description_text = description or "No description available."
    description_text = html_escape(description_text)
    stars = repo_node.get("stargazerCount", 0)
    forks = repo_node.get("forkCount", 0)
    updated = repo_node.get("updatedAt", "")
    updated = updated[:10] if updated else ""
    language_text = ", ".join(languages) if languages else "No language"

    return f"""
<div class=\"repo-row\">
  <div class=\"repo-left\">
    <h2 class=\"repo-title\"><a href=\"{url}\" target=\"_blank\" rel=\"noopener noreferrer\">{title}</a></h2>
    <p class=\"repo-description\">{description_text}</p>
  </div>
  <div class=\"repo-stats\">
    <div>{render_stat('Stars', stars)}{render_stat('Forks', forks)}</div>
    <div class=\"repo-meta\">
      <div>{html_escape(language_text)}</div>
      <div>Updated {html_escape(updated)}</div>
    </div>
  </div>
</div>"""


def render_stat(label, value):
    return f"<span class=\"repo-stat\"><strong>{value}</strong><span>{label}</span></span>"


def build_html(repo_rows):
    return f"""<!DOCTYPE html>
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>GitHub Repositories | Pujan Ajmera</title>
  <meta name=\"description\" content=\"GitHub repositories and research software by Pujan Ajmera.\" />
  <link rel=\"icon\" href=\"favicon.svg\" type=\"image/svg+xml\" />
  <link rel=\"apple-touch-icon\" href=\"images/apple-touch-icon.png\" />
  <meta property=\"og:type\" content=\"website\" />
  <meta property=\"og:site_name\" content=\"Pujan Ajmera\" />
  <meta property=\"og:title\" content=\"GitHub Repositories | Pujan Ajmera\" />
  <meta property=\"og:description\" content=\"GitHub repositories and research software by Pujan Ajmera.\" />
  <meta property=\"og:url\" content=\"https://pujanajmera.github.io/repos.html\" />
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
    <h1>GitHub Repositories</h1>
  </header>
  <div class=\"repo-list\">
{''.join(repo_rows)}
  </div>
</body>
</html>"""


def main():
    print("Fetching repository contributions...")
    data = fetch_json(QUERY, {"login": USERNAME, "first": 100})
    user = data.get("user")
    if not user or not user.get("repositoriesContributedTo"):
        print("No repository data returned.")
        sys.exit(1)

    repos = [repo for repo in user["repositoriesContributedTo"]["nodes"] if not repo.get("isFork")]
    repos.sort(key=lambda repo: repo.get("updatedAt") or "", reverse=True)
    repo_rows = []
    for repo in repos:
        description = repo.get("description") or ""
        if not description:
            description = fetch_readme_snippet(repo["owner"]["login"], repo["name"]) or ""
        languages = format_languages(repo)
        repo_rows.append(render_repo(repo, description, languages))

    html_text = build_html(repo_rows)
    OUTPUT_FILE.write_text(html_text, encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE} with {len(repo_rows)} repositories.")


if __name__ == "__main__":
    main()
