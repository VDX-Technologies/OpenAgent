"""
Tool · GitHub
=============
GitHub REST API (personal access token in ``GITHUB_TOKEN``):
list repos, issues and PRs, open issues/PRs, and clone a repo into a
local folder that becomes the coding workspace.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import httpx

from config.settings import get_settings
from tools import code_workspace

API = "https://api.github.com"


def _req(method: str, path: str, **kw) -> dict | list | str:
    tok = get_settings().github.token
    try:
        r = httpx.request(method, API + path, timeout=20, headers={
            "Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, **kw)
    except httpx.HTTPError as exc:
        return f"Error: GitHub unreachable: {exc}"
    if r.status_code >= 400:
        return f"Error: GitHub {r.status_code}: {r.text[:300]}"
    return r.json() if r.content else {}


def list_repos(limit: int = 20) -> str:
    """List the user's most recently updated repositories."""
    data = _req("GET", "/user/repos", params={"sort": "updated", "per_page": min(int(limit), 100)})
    if isinstance(data, str):
        return data
    return "\n".join(f"{r['full_name']}{' (private)' if r['private'] else ''} — {r.get('description') or ''}" for r in data)


def list_issues(repo: str, state: str = "open") -> str:
    """List issues (not PRs) of owner/repo."""
    data = _req("GET", f"/repos/{repo}/issues", params={"state": state, "per_page": 30})
    if isinstance(data, str):
        return data
    rows = [f"#{i['number']} {i['title']} ({i['user']['login']})" for i in data if "pull_request" not in i]
    return "\n".join(rows) or "No issues."


def create_issue(repo: str, title: str, body: str = "") -> str:
    """Open a new issue on owner/repo."""
    data = _req("POST", f"/repos/{repo}/issues", json={"title": title, "body": body})
    return data if isinstance(data, str) else f"Issue created: {data['html_url']}"


def list_pull_requests(repo: str, state: str = "open") -> str:
    """List pull requests of owner/repo."""
    data = _req("GET", f"/repos/{repo}/pulls", params={"state": state, "per_page": 30})
    if isinstance(data, str):
        return data
    return "\n".join(f"#{p['number']} {p['title']} [{p['head']['ref']} → {p['base']['ref']}]" for p in data) or "No PRs."


def create_pull_request(repo: str, title: str, head: str, base: str = "main", body: str = "") -> str:
    """Open a pull request from branch *head* into *base*."""
    data = _req("POST", f"/repos/{repo}/pulls", json={"title": title, "head": head, "base": base, "body": body})
    return data if isinstance(data, str) else f"PR opened: {data['html_url']}"


def clone_repo(repo: str, dest_dir: str = "~/Developer") -> str:
    """Clone owner/repo into *dest_dir* and make it the coding workspace."""
    dest = Path(dest_dir).expanduser() / repo.split("/")[-1]
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tok = get_settings().github.token
        url = f"https://x-access-token:{tok}@github.com/{repo}.git" if tok else f"https://github.com/{repo}.git"
        r = subprocess.run(["git", "clone", url, str(dest)], capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            return f"Error cloning: {r.stderr.replace(tok, '***') if tok else r.stderr}"
        # don't keep the token in .git/config; pushes authenticate via header
        subprocess.run(["git", "remote", "set-url", "origin", f"https://github.com/{repo}.git"], cwd=dest)
    return code_workspace.set_workspace(str(dest))


TOOLS = {
    "github_list_repos": list_repos, "github_list_issues": list_issues,
    "github_create_issue": create_issue, "github_list_pull_requests": list_pull_requests,
    "github_create_pull_request": create_pull_request, "github_clone_repo": clone_repo,
}

_S = {"type": "string"}
_R = {"type": "string", "description": "owner/repo"}
TOOL_DESCRIPTORS = [
    {"name": "github_list_repos", "description": "List the user's GitHub repositories.",
     "parameters": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "github_list_issues", "description": "List issues of a repo.",
     "parameters": {"type": "object", "properties": {"repo": _R, "state": _S}, "required": ["repo"]}},
    {"name": "github_create_issue", "description": "Open an issue on a repo.",
     "parameters": {"type": "object", "properties": {"repo": _R, "title": _S, "body": _S}, "required": ["repo", "title"]}},
    {"name": "github_list_pull_requests", "description": "List pull requests of a repo.",
     "parameters": {"type": "object", "properties": {"repo": _R, "state": _S}, "required": ["repo"]}},
    {"name": "github_create_pull_request", "description": "Open a PR from a pushed branch.",
     "parameters": {"type": "object", "properties": {"repo": _R, "title": _S, "head": _S, "base": _S, "body": _S},
                    "required": ["repo", "title", "head"]}},
    {"name": "github_clone_repo", "description": "Clone a GitHub repo locally and make it the coding workspace.",
     "parameters": {"type": "object", "properties": {"repo": _R, "dest_dir": _S}, "required": ["repo"]}},
]
