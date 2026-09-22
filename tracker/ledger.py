"""Parsers for the task board and the qualification ledger.

Method traps encoded:
- Board: 8 of the `[ ]` lines are wave rollup headers, not tasks. Both counts are
  reported so the arithmetic is auditable.
- Ledger: count `[gate.*]` per record by outcome and check the parts sum to the whole
  ("23 pass" was reported for a week and summed to 49).
- Ledger: gates ran on a dirty tree are void as release qualification. Detect the
  runner's own marker and say so.
- Ledger: append-only with no resolution field; observations only ever go up and
  measure activity, not remaining work.
"""

import re

CHECKBOX = re.compile(r"^\s*(?:[-*]\s+)?\[(.)\]\s*(.*)$")
RECORD_START = re.compile(r"^\s*\[([A-Za-z][\w.\-]*)\]\s*$")
OUTCOME = re.compile(r"\boutcome\b\s*[=:]\s*\"?([A-Za-z_]+)\"?", re.I)
VOID_MARKER = "tracked working-tree changes present at runner start"


def parse_board(text):
    raw = {"x": 0, "-": 0, " ": 0}
    adjusted = {"x": 0, "-": 0, " ": 0}
    headers = 0
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = CHECKBOX.match(line)
        if not m:
            continue
        mark = m.group(1)
        key = {"x": "x", "-": "-", " ": " "}.get(mark)
        if key is None:
            continue
        raw[key] += 1
        if _is_rollup_header(line):
            headers += 1
        else:
            adjusted[key] += 1
    return {"raw": raw, "tasks": adjusted, "rollup_headers": headers}


# '- [ ] 3. Make state durable'  -> wave rollup header
WAVE_HEADER = re.compile(r"^\s*-\s*\[[ x-]\]\s*\d+\.\s")
# '  - [x] 3.4 Make publication one commit unit' -> an actual task
TASK_ITEM = re.compile(r"^\s*-\s*\[[ x-]\]\s*\d+\.\d+")


def _is_rollup_header(line):
    """Structure, not wording: a top-level 'N.' item is a wave rollup, 'N.M' is a task."""
    return bool(WAVE_HEADER.match(line)) and not TASK_ITEM.match(line)


def parse_ledger(text):
    records, current = [], None
    for line in text.splitlines():
        m = RECORD_START.match(line)
        if m:
            current = {"name": m.group(1), "body": []}
            records.append(current)
        elif current is not None:
            current["body"].append(line)
    gates, observations = {}, {}
    void_gates = 0
    ceiling = None
    for rec in records:
        name = rec["name"]
        body = "\n".join(rec["body"])
        if name.startswith("gate"):
            om = OUTCOME.search(body)
            outcome = (om.group(1).lower() if om else "unknown")
            gates[outcome] = gates.get(outcome, 0) + 1
            if VOID_MARKER in body.lower():
                void_gates += 1
        elif name.startswith("observation"):
            observations[name] = observations.get(name, 0) + 1
            if "cannot reach their required beta rung" in body:
                ceiling = name
    gate_total = sum(gates.values())
    outcome_sum = sum(v for k, v in gates.items() if k in ("pass", "fail", "blocked"))
    return {
        "gates": gates,
        "gate_total": gate_total,
        "outcome_sum": outcome_sum,
        "arithmetic_ok": gate_total == outcome_sum,
        "void_gates": void_gates,
        "all_gates_void": gate_total > 0 and void_gates == gate_total,
        "observations": sum(observations.values()),
        "observation_ceiling": ceiling,
    }
