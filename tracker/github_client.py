"""Small GitHub REST client.

Method traps this encodes:
- Repo renames: an old name returns a redirect object instead of data, and parsers
  silently read zero. urllib follows the redirect, but every consumer must still pass
  `require_repo_object` so a zero is never trusted blind.
- The rendered /pulls page caps at 25; PR counts come from the search API.
- No token is ever written to a file. GITHUB_TOKEN is read from the environment only.
"""

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

API = "https://api.github.com"


class GithubError(RuntimeError):
    pass


class GithubClient:
    def __init__(self, token=None, min_interval=0.7):
        self.token = token or os.environ.get("GITHUB_TOKEN") or None
        self.min_interval = min_interval
        self._last = 0.0
        self.calls = []

    def _headers(self):
        h = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "paxeer-dev-tracker",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            h["Authorization"] = "Bearer " + self.token
        return h

    def get(self, path, params=None):
        url = API + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        wait = self.min_interval - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        req = urllib.request.Request(url, headers=self._headers())
        self.calls.append(path)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode()), r.status
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            try:
                payload = json.loads(body)
            except Exception:
                payload = {"message": body[:300]}
            payload["__http_status__"] = e.code
            return payload, e.code
        except urllib.error.URLError as e:
            return {"__http_status__": 0, "message": str(e.reason)}, 0

    def get_raw(self, url):
        """Stream a raw file. The contents API omits content above 1 MB."""
        req = urllib.request.Request(url, headers=self._headers())
        self.calls.append(url)
        try:
            with urllib.request.urlopen(req, timeout=90) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            return None

    # ---- rename-safe helpers -------------------------------------------------

    def list_org_repos(self, org):
        return self._paginate("/orgs/%s/repos" % org, {"per_page": 100, "type": "all"})

    def list_user_repos(self, user):
        return self._paginate("/users/%s/repos" % user, {"per_page": 100, "type": "owner"})

    def _paginate(self, path, params):
        out, page = [], 1
        while True:
            params = dict(params, page=page)
            data, status = self.get(path, params)
            if not isinstance(data, list):
                return {"__error__": data.get("__http_status__", status),
                        "message": data.get("message", "non-list response"), "items": out}
            out.extend(data)
            if len(data) < params["per_page"]:
                return {"items": out}
            page += 1
            if page > 20:
                return {"items": out, "__truncated__": True}

    @staticmethod
    def require_repo_object(payload):
        """A renamed repo can surface as a redirect object. Guard every read."""
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("full_name")) and "name" in payload
