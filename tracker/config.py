"""The watchlist as data: one canonical ``sources.json``, read at run time.

Why this exists: the tracked accounts, endpoints and repo aliases are METRICS
CONFIG, not code. A user adding a developer account or a website must not require
a code change and a re-install on every machine. Instead the canonical file lives
in the public repo and every sweep fetches it first, so all installs see the same
watchlist regardless of bundle version.

Resolution order (first hit wins), and the brief stamps which one was used:

1. **remote**  -- ``raw.githubusercontent.com/.../main/sources.json`` [verified]
2. **cache**   -- the last remote copy this install fetched [reported]
3. **bundled** -- the copy shipped inside the app bundle [reported]

Security contract: remote config is DATA, never code. It is schema-validated and
unknown keys are rejected -- it can widen what is watched, nothing more.
"""

import json
import os
import urllib.request

CANONICAL_URL = os.environ.get(
    "PAXEER_SOURCES_URL",
    "https://raw.githubusercontent.com/schlegelcrypto-stack/"
    "paxeer-dev-tracker/main/sources.json",
)
BUNDLED_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sources.json"
)

MODES = ("remote", "local")


class ConfigError(ValueError):
    """The sources file failed schema validation."""


def load_bundled():
    """The watchlist shipped inside the bundle. Always available, never fetched."""
    with open(BUNDLED_PATH) as f:
        return validate(json.load(f))


def load(url=None, mode=None, fetcher=None):
    """Return the resolved ``sources`` dict, stamped with ``_provenance``.

    ``fetcher`` is the single egress seam (``url -> bytes``) so tests never touch
    the network. ``mode='local'`` (or env ``PAXEER_SOURCES=local``) skips the
    remote fetch entirely for air-gapped runs.
    """
    url = url or CANONICAL_URL
    mode = mode or os.environ.get("PAXEER_SOURCES", "remote")
    if mode not in MODES:
        raise ConfigError("sources mode must be one of %s — got %r" % (MODES, mode))
    fetch = fetcher or _fetch
    errors = []

    if mode == "remote":
        try:
            cfg = validate(json.loads(fetch(url).decode("utf-8")))
            _cache_write(cfg)
            return _stamped(cfg, "remote", url, None)
        except Exception as exc:  # noqa: BLE001 — every failure falls through
            errors.append("remote: %s" % exc)
            cfg = _cache_read()
            if cfg is not None:
                return _stamped(cfg, "cache", url, "; ".join(errors))

    return _stamped(load_bundled(), "bundled", url,
                    "; ".join(errors) if errors else "mode=local")


def validate(cfg):
    """Strict schema check. Data may widen the watchlist; it can never smuggle code."""
    if not isinstance(cfg, dict):
        raise ConfigError("sources must be a JSON object")
    unknown = set(cfg) - _KNOWN_KEYS
    if unknown:
        raise ConfigError("unknown keys: %s" % ", ".join(sorted(unknown)))
    for key in _REQUIRED_KEYS:
        if key not in cfg:
            raise ConfigError("missing required key: %s" % key)
    if cfg["schema_version"] != 1:
        raise ConfigError("unsupported schema_version: %r" % cfg["schema_version"])
    if not isinstance(cfg["version"], int) or cfg["version"] < 1:
        raise ConfigError("version must be a positive integer")
    if not isinstance(cfg["accounts"], list) or not cfg["accounts"]:
        raise ConfigError("accounts must be a non-empty list")
    for row in cfg["accounts"]:
        if not isinstance(row, dict) or set(row) - {"login", "kind"}:
            raise ConfigError("account rows carry only login and kind: %r" % (row,))
        if not isinstance(row.get("login"), str) or not row["login"]:
            raise ConfigError("account login must be a non-empty string: %r" % (row,))
        if row.get("kind") not in ("org", "user"):
            raise ConfigError("account kind must be 'org' or 'user': %r" % (row,))
    for key in ("endpoints", "excluded_owners", "packages_watch", "lane_phases", "watch"):
        if key in cfg and not _str_list(cfg[key]):
            raise ConfigError("%s must be a list of strings" % key)
    for url in cfg.get("endpoints", []):
        if not url.startswith(("http://", "https://")):
            raise ConfigError("endpoint must be an http(s) URL: %r" % url)
    mr = cfg["main_repo"]
    if not isinstance(mr, dict) or set(mr) - {"owner", "aliases", "board_path", "ledger_path"}:
        raise ConfigError("main_repo carries owner, aliases, board_path, ledger_path")
    if not isinstance(mr.get("owner"), str) or not mr["owner"]:
        raise ConfigError("main_repo.owner must be a non-empty string")
    if not _str_list(mr.get("aliases")):
        raise ConfigError("main_repo.aliases must be a list of strings")
    for key in ("board_path", "ledger_path"):
        if not isinstance(mr.get(key), str) or not mr[key]:
            raise ConfigError("main_repo.%s must be a non-empty string" % key)
    return cfg


_REQUIRED_KEYS = ("schema_version", "version", "accounts", "main_repo", "endpoints")
_KNOWN_KEYS = set(_REQUIRED_KEYS) | {
    "note", "updated", "excluded_owners", "packages_watch", "lane_phases", "watch",
}


def account_pairs(cfg):
    """[(login, kind)] — kind picks the /orgs vs /users endpoint. Never guess."""
    return [(row["login"], row["kind"]) for row in cfg["accounts"]]


def _str_list(value):
    return isinstance(value, list) and all(isinstance(v, str) and v for v in value)


def _stamped(cfg, source, url, error):
    cfg = dict(cfg)
    cfg["_provenance"] = {
        "source": source,
        "version": cfg["version"],
        "url": url,
        "error": error,
    }
    return cfg


def _fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "paxeer-dev-tracker"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def _cache_path():
    from . import state  # late import: state resolves APP_DATA_DIR at call time

    return os.path.join(state._state_dir(), "sources-cache.json")


def _cache_write(cfg):
    try:
        path = _cache_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump({k: v for k, v in cfg.items() if not k.startswith("_")}, f, indent=1)
    except OSError:
        pass  # a read-only state dir must not break a sweep


def _cache_read():
    try:
        with open(_cache_path()) as f:
            return validate(json.load(f))
    except Exception:  # noqa: BLE001 — a corrupt cache falls through to bundled
        return None
