"""The `paxeer-dev-tracker` tool provider — a daily engineering briefing for Paxeer.

Three tools over one GitHub-derived snapshot: ``paxeer_sweep`` pulls fresh state from the
public GitHub API, saves the snapshot, and answers with the human-readable briefing;
``paxeer_brief`` renders the briefing from the last saved snapshot with no network call;
``paxeer_sources`` reports the watchlist in effect and how to extend it.

How the pieces fit:

- **The engine lives in :mod:`tracker`.** Parsing (:mod:`tracker.ledger`), GitHub
  (:mod:`tracker.github_client`), sweeping (:mod:`tracker.sweep`), state
  (:mod:`tracker.state`) and prose (:mod:`tracker.brief`) are unit-tested on their own;
  this file is a thin adapter over :func:`tracker.sweep.collect` and
  :func:`tracker.brief.render_brief`.
- **One transport seam.** All egress goes through
  :meth:`tracker.github_client.GithubClient.get`, late-bound, so tests swap it and no
  HTTP leaves the test process.
- **The watchlist is data, not code.** ``sources.json`` is fetched from the canonical
  repo at run time (:mod:`tracker.config`), so adding a tracked account, website, or
  repo reaches every install on its next sweep — no re-install.
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

from tracker import config as watchlist
from tracker import state
from tracker.brief import render_brief
from tracker.github_client import GithubClient
from tracker.sweep import collect

logger = logging.getLogger("paxeer-dev-tracker")

VERSION = "0.2.0"
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
        self._sources_url = self._config.get("sources_url") or None
        self._sources_mode = str(self._config.get("sources_mode") or "remote").strip().lower()

    # ── Identity ────────────────────────────────────────────────────────────────

    @property
    def name(self) -> str:
        return "paxeer-dev-tracker"

    @property
    def display_name(self) -> str:
        return "Paxeer Dev Tracker"

    def info(self) -> dict[str, Any]:
        cfg = watchlist.load_bundled()
        return {
            "accounts": [login for login, _kind in watchlist.account_pairs(cfg)],
            "watchlist": {
                "version": cfg["version"],
                "mode": self._sources_mode,
                "url": self._sources_url or watchlist.CANONICAL_URL,
            },
            "timeout_secs": self._timeout,
            "tools": ["paxeer_sweep", "paxeer_brief", "paxeer_sources"],
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
            ToolDefinition(
                name="paxeer_sources",
                description=(
                    "Show the watchlist this tracker sweeps — tracked GitHub "
                    "accounts (org/user), watched websites, the main repo and its "
                    "aliases, and where the list came from (canonical sources.json "
                    "vs fallback). Also explains how to add a developer account, "
                    "website, or repo so every install picks the change up."
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
            "paxeer_sources": self._sources_info,
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
        sources = self._sources()
        gh = GithubClient()
        prev = state.load_latest() or state.load_previous()
        snapshot = collect(gh, full=(mode == "full"), timeout=self._timeout, sources=sources)
        path = state.save(snapshot, label=mode)
        brief = render_brief(snapshot, prev)
        return ToolResult(
            success=True,
            output=brief,
            metadata={"mode": mode, "snapshot": path,
                      "sources": snapshot.get("sources"),
                      "suspect": snapshot.get("suspect", [])},
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

    def _sources(self) -> dict[str, Any]:
        """Resolve the watchlist: canonical URL first, fallback stamped in provenance."""
        try:
            return watchlist.load(url=self._sources_url, mode=self._sources_mode)
        except watchlist.ConfigError as exc:
            raise TrackerError(
                f"Watchlist config is invalid: {exc}",
                hints=["Fix the app's sources_mode/sources_url settings, or the "
                       "sources.json on the canonical branch."],
            )

    async def _sources_info(self, _args: dict[str, Any]) -> ToolResult:
        """The watchlist in effect — and how a user extends it. The answer to
        'how do all users get the same info' lives in the last section."""
        cfg = self._sources()
        prov = cfg.get("_provenance", {})
        marker = "[verified]" if prov.get("source") == "remote" else "[reported]"
        out = [
            "# Watchlist in effect — v%s %s" % (cfg["version"], marker),
            "",
            "Source: %s" % {"remote": "canonical sources.json (fetched this run)",
                            "cache": "last-fetched copy (canonical unreachable)",
                            "bundled": "bundled fallback (canonical unreachable)",
                            "caller": "caller-supplied"}.get(prov.get("source"), prov.get("source")),
        ]
        if prov.get("error"):
            out.append("Fallback cause: %s" % prov["error"])
        out += ["", "## Tracked accounts"]
        out += ["- %s (%s)" % (login, kind) for login, kind in watchlist.account_pairs(cfg)]
        out += ["", "## Watched endpoints"]
        out += ["- %s" % u for u in cfg.get("endpoints", [])]
        main = cfg["main_repo"]
        out += ["", "## Main repo",
                "- %s — aliases: %s" % (main["owner"], ", ".join(main["aliases"])),
                "- board: `%s` · ledger: `%s`" % (main["board_path"], main["ledger_path"]),
                "", "## How to extend",
                "Add a developer account, website, or repo by editing `sources.json` in",
                "`github.com/schlegelcrypto-stack/paxeer-dev-tracker` and bumping `version`.",
                "Every install fetches that file on its next sweep — one change reaches all",
                "users, no re-install. The file is schema-validated data: it can widen what",
                "is watched, nothing more."]
        return ToolResult(success=True, output="\n".join(out), metadata=prov)


def create_paxeer_provider(config: dict[str, Any] | None = None) -> PaxeerTrackerProvider:
    """Entry point the gateway calls per the manifest's ``provider`` block."""
    return PaxeerTrackerProvider(config)
