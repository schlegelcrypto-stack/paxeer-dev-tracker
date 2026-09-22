"""Back-compat shim: the watchlist now lives in ``sources.json`` (see
:mod:`tracker.config`). These names are derived from the BUNDLED copy and exist so
older imports keep working; sweep-time code passes the resolved config explicitly,
because that is the copy fetched from the canonical URL."""

from .config import account_pairs, load_bundled

_DEFAULTS = load_bundled()
_MAIN = _DEFAULTS["main_repo"]

# (login, kind) -- kind is 'org' or 'user'. Wrong endpoint silently returns empty.
ACCOUNTS = account_pairs(_DEFAULTS)

# Schlegel's own org: ecosystem intel excludes it on purpose.
EXCLUDED_OWNERS = set(_DEFAULTS.get("excluded_owners", []))

# The main development repository, renamed twice already, resolved by discovery.
MAIN_REPO_OWNER = _MAIN["owner"]
MAIN_REPO_ALIASES = tuple(_MAIN["aliases"])

# Files read from the main repo on every sweep.
BOARD_PATH = _MAIN["board_path"]
LEDGER_PATH = _MAIN["ledger_path"]

# Lane phase vocabulary observed so far; new prefixes are surfaced, not swallowed.
KNOWN_LANE_PHASES = tuple(_DEFAULTS.get("lane_phases", []))

# Public endpoints whose liveness is the headline signal.
ENDPOINTS = list(_DEFAULTS.get("endpoints", []))
