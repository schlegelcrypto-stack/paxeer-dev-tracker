import json
import os
from datetime import datetime, timezone

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "state")


def _state_dir():
    """Where snapshots live: the Gideon app data dir when provided (a store
    bundle's state must land in its own data dir, not inside the bundle), else
    an explicit override, else the bundle-local state/ directory."""
    app_data = os.environ.get("APP_DATA_DIR")
    if app_data:
        return os.path.join(app_data, "state")
    return os.environ.get("PAXEER_STATE_DIR", STATE_DIR)


def save(snapshot, label=None):
    state_dir = _state_dir()
    os.makedirs(state_dir, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = "snapshot-%s%s.json" % (ts, ("-" + label) if label else "")
    path = os.path.join(state_dir, name)
    with open(path, "w") as f:
        json.dump(snapshot, f, indent=1, sort_keys=True)
    latest = os.path.join(state_dir, "latest.json")
    with open(latest, "w") as f:
        json.dump(snapshot, f, indent=1, sort_keys=True)
    return path


def load_latest():
    return _load(os.path.join(_state_dir(), "latest.json"))


def load_previous():
    """Second-newest snapshot: the diff base for the brief."""
    state_dir = _state_dir()
    if not os.path.isdir(state_dir):
        return {}
    names = sorted(n for n in os.listdir(state_dir) if n.startswith("snapshot-"))
    if len(names) < 2:
        return {}
    return _load(os.path.join(state_dir, names[-2]))


def _load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}
