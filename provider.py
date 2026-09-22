"""The `paxeer-dev-tracker` tool provider — a daily engineering briefing for Paxeer.

Two tools over one GitHub-derived snapshot: ``paxeer_sweep`` pulls fresh state from the
public GitHub API, saves the snapshot, and answers with the human-readable briefing;
``paxeer_brief`` renders the briefing from the last saved snapshot with no network call.

How the pieces fit:

- **The engine lives in :mod:`tracker`.** Parsing (:mod:`tracker.ledger`), GitHub
  (:mod:`tracker.github_client`), sweeping (:mod:`tracker.sweep`), state
  (:mod:`tracker.state`) and prose (:mod:`tracker.brief`) are unit-tested on their own;
  this file is a thin adapter over :func:`tracker.sweep.collect` and
  :func:`tracker.brief.render_brief`.
- **One transport seam.** All egress goes through
  :meth:`tracker.github_client.GithubClient.get`, late-bound, so tests swap it and no
  HTTP leaves the test process.
- **Diff-against-previous is the product.** Each sweep saves its snapshot; the brief
  compares against the previous one ("The main repo moved…", "New repositories
  appeared…"), exactly like the daily tracker posts it.
- **Every failure stays legible.** A bad mode or an empty state becomes a failing
  :class:`~gideon.sdk.tool.ToolResult` with a recovery hint, never a traceback out of
  the tool layer.
"""

from __future__ import annotations

import logging
from typing import Any

from gideon.sdk.tool import RiskLevel, ToolDefinition, ToolProvider, ToolResult

from tracker import state
from tracker.accounts import ACCOUNTS
from tracker.brief import render_brief
from tracker.github_client import GithubClient
from tracker.sweep import collect

logger = logging.getLogger("paxeer-dev-tracker")

VERSION = "0.1.0"
MIN_TIMEOUT_SECS = 2.0
MAX_TIMEOUT_SECS = 120.0
DEFAULT_TIMEOUT_SECS = 20.0
MODES = ("quick", "full")


class TrackerError(Exception):
    """A legible provider failure, with hints the agent can act on."""

    def __init__(self, message: str, hints: list[str] | None = None) -> None:
        super().__init__(message)
        self.hints = hints or []


class PaxeerTrackerProvider(ToolProvider):
    """The Paxeer development pulse from GitHub's public API."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = dict(config or {})
        timeout = self._config.get("timeout_secs", DEFAULT_TIMEOUT_SECS)
        try:
            timeout_value = float(timeout if timeout not in (None, "") else DEFAULT_TIMEOUT_SECS)
        except (TypeError, ValueError):
            timeout_value = DEFAULT_TIMEOUT_SECS
        self._timeout = min(MAX_TIMEOUT_SECS, max(MIN_TIMEOUT_SECS, timeout_value))

    # ── Identity ────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "paxeer-dev-tracker"

    @property
    def display_name(self) -> str:
        return "Paxeer Dev Tracker"

    def info(self) -> dict[str, Any]:
        return {
            "accounts": [login for login, _kind in ACCOUNTS],
            "timeout_secs": self._timeout,
            "tools": ["paxeer_sweep", "paxeer_brief"],
        }

    # ── Tool surface ────────────────────────────────────────────────────────────

    async def list_tools(self) -> list[ToolDefinition]:
        return [
            ToolDefinition(
                name="paxeer_sweep",
                description=(
                    "Pull the current Paxeer development state from the public GitHub "
                    "API — the main network repository's HEAD and merged work lanes, "
                    "the task board and qualification ledger, the open-PR count, and "
                    "every repo across the tracked Sidiora/LayerX accounts — save the "
                    "snapshot, and answer with the human-readable engineering "
                    "briefing diffed against the previous sweep. mode 'quick' reads "
                    "the main repo and endpoints (~10s); mode 'full' also sweeps every "
                    "tracked account and repo (~50s). The first sweep ever reports a "
                    "baseline with no deltas."
                ),
                provider=self.name,
                parameters={
                    "type": "object",
                    "properties": {
                        "mode": {
                            "type": "string",
                            "enum": list(MODES),
                            "description": (
                                "'quick' (default) for the main-repo pulse in ~10s, "
                                "'full' (~50s) to sweep every tracked account and "
                                "repository too."
                            ),
                        },
                    },
                },
                requires_approval=False,
                risk_level=RiskLevel.SAFE,
            ),
            ToolDefinition(
                name="paxeer_brief",
                description=(
                    "Render the Paxeer engineering briefing from the saved snapshots — "
                    "no network call, instant. Compares the latest sweep against the "
                    "one before it: what changed in the main repo, new repositories, "
                    "lane and PR rollups, the board and the gates, plus the method "
                    "notes that mark suspect results. Use paxeer_sweep when a fresh "
                    "pull is wanted."
                ),
                provider=self.name,
                parameters={"type": "object", "properties": {}},
                requires_approval=False,
                risk_level=RiskLevel.SAFE,
            ),
        ]

    async def invoke(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        handlers = {
            "paxeer_sweep": self._sweep,
            "paxeer_brief": self._brief,
        }
        handler = handlers.get(tool_name)
        if handler is None:
            return ToolResult(
                success=False,
                error=f"Unknown tool: {tool_name!r}",
                recovery_hints=[f"This provider exposes: {', '.join(sorted(handlers))}."],
            )
        try:
            return await handler(arguments)
        except TrackerError as exc:
            return ToolResult(success=False, error=str(exc), recovery_hints=exc.hints)
        except OSError as exc:
            # A socket that died mid-read and friends: a legible failure, not a traceback.
            logger.warning("tracker I/O failed for %s: %s", tool_name, exc)
            return ToolResult(
                success=False,
                error=f"GitHub could not be reached: {exc}",
                recovery_hints=["Check the machine's internet connection and retry."],
            )

    # ── Handlers ────────────────────────────────────────────────────────────────

    async def _sweep(self, args: dict[str, Any]) -> ToolResult:
        mode = str(args.get("mode") or "quick").strip().lower()
        if mode not in MODES:
            raise TrackerError(
                f"mode must be one of {', '.join(MODES)} — got {mode!r}.",
                hints=["Pass mode='quick' (~10s) or mode='full' (~50s)."],
            )
        gh = GithubClient()
        prev = state.load_latest() or state.load_previous()
        snapshot = collect(gh, full=(mode == "full"), timeout=self._timeout)
        path = state.save(snapshot, label=mode)
        brief = render_brief(snapshot, prev)
        return ToolResult(
            success=True,
            output=brief,
            metadata={"mode": mode, "snapshot": path, "suspect": snapshot.get("suspect", [])},
        )

    async def _brief(self, _args: dict[str, Any]) -> ToolResult:
        curr = state.load_latest()
        if not curr:
            raise TrackerError(
                "No snapshot saved yet — nothing has been swept.",
                hints=["Run paxeer_sweep first; it saves the snapshot the brief reads."],
            )
        return ToolResult(
            success=True,
            output=render_brief(curr, state.load_previous()),
            metadata={"generated_by": curr.get("generated_by", "paxeer-dev-tracker")},
        )


def create_paxeer_provider(config: dict[str, Any] | None = None) -> PaxeerTrackerProvider:
    """Entry point the gateway calls per the manifest's ``provider`` block."""
    return PaxeerTrackerProvider(config)
