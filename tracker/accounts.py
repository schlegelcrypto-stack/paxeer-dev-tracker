"""The eight tracked accounts. Org vs user matters: wrong endpoint silently returns empty."""

# (login, kind) -- kind is 'org' or 'user'. Only two are orgs.
ACCOUNTS = [
    ("Sidiora-Labs", "org"),
    ("Paxeer-Network", "org"),
    ("dev-paxeer", "user"),
    ("Sidiora-Technologies", "user"),
    ("paxlabs-inc", "user"),
    ("jg-sidioralabs", "user"),
    ("matrix-agent-neo", "user"),
    ("MachineCity", "user"),
]

# Schlegel's own org: ecosystem intel excludes it on purpose.
EXCLUDED_OWNERS = {"schlegelcrypto-stack"}

# The main development repository. It has been renamed twice
# (LayerX-Protocol -> LayerX-Network -> Paxeer-X-Network), so it is resolved
# by discovery, never by hard-coded name alone.
MAIN_REPO_OWNER = "Sidiora-Labs"
MAIN_REPO_ALIASES = ("Paxeer-X-Network", "LayerX-Network", "LayerX-Protocol")

# Files read from the main repo on every sweep.
BOARD_PATH = "spec/layerx-beta/tasks.md"
LEDGER_PATH = "spec/layerx-beta/qualification.kvx"

# Lane phase vocabulary observed so far; new prefixes are surfaced, not swallowed.
KNOWN_LANE_PHASES = ("tn", "unify", "fix", "docs", "hosts", "naming")

# Public endpoints whose liveness is the headline signal.
ENDPOINTS = [
    "https://api.layerxnet.ai",
    "https://faucet.layerxnet.ai",
    "https://gideon.centra.ag",
    "https://agentneo.app",
]
