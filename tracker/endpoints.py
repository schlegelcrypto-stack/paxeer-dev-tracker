"""Endpoint liveness probes with controls.

Method traps encoded:
- Wildcard DNS: *.vercel.app resolves any name, so a 200 alone proves nothing.
- SPAs return 200 for every route: compare bytes against a nonsense-path control
  before calling a route live.
- This container re-signs TLS, so certificate checks use CT logs (certspotter),
  never the TLS handshake.
"""

import json
import urllib.error
import urllib.request

CONTROL_PATH = "/gideon-nonexistent-control-path-7f3a"
CT_URL = "https://api.certspotter.com/v1/issuances?domain=%s&include_subdomains=true&expand=dns_names"


def probe(url, timeout=15):
    row = {"url": url, "status": None, "control_status": None, "spa_suspect": False,
           "bytes": 0, "error": None}
    row["status"], row["bytes"] = _fetch(url)
    row["control_status"], control_bytes = _fetch(url.rstrip("/") + CONTROL_PATH)
    if row["status"] == 200 and row["control_status"] == 200 and row["bytes"] == control_bytes:
        row["spa_suspect"] = True
    return row


def _fetch(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "paxeer-dev-tracker"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, len(r.read())
    except urllib.error.HTTPError as e:
        return e.code, 0
    except Exception:
        return None, 0


def packages(gh, owner):
    """Container packages: the first published image is a watch-list signal."""
    data, status = gh.get("/orgs/%s/packages" % owner, {"package_type": "container", "per_page": 100})
    if isinstance(data, list):
        return {"owner": owner, "names": [p.get("name") for p in data], "count": len(data)}
    return {"owner": owner, "count": None, "note": data.get("message", "unavailable")}


def ct_issuances(domain):
    req = urllib.request.Request(CT_URL % domain, headers={"User-Agent": "paxeer-dev-tracker"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            rows = json.loads(r.read().decode())
        return {"domain": domain, "issuances": len(rows),
                "names": sorted({n for row in rows for n in (row.get("dns_names") or [])})[:20]}
    except Exception as e:
        return {"domain": domain, "error": str(e)}
