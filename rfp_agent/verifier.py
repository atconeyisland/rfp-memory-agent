"""Deterministic guardrails. The system prompt *asks* the model to be honest;
this module *checks*. It compares the model's output with what recall actually returned."""
from __future__ import annotations
import re

_PCT = re.compile(r"\b\d{1,3}(?:\.\d+)?\s*%\s*(?:confidence|confident|likelihood|chance|win rate|success)", re.I)
_CONF_BODY = re.compile(r"confidence[^.\n]{0,25}\b\d\.\d+", re.I)
_OP = re.compile(r"confidence:\s*(\d\.\d+),\s*based on\s*(\d+)", re.I)
_HEAD = re.compile(r"Memory trace:\s*recalled\s*(\d+)\s*experiences?,\s*(\d+)\s*opinions?\s*for\s*([^\s.]+)", re.I)


def build_trace(recall: dict, used_opinion_ids=(), strategy_notes: str = "") -> str:
    """Trace is COMPUTED from the recall result, so numbers cannot be hallucinated."""
    c = recall["counts"]
    ops = {o["id"]: o for o in recall["opinions"] + recall["org_opinions"]}
    lines = ["---", "Internal (not for client)"]
    if strategy_notes:
        lines.append(f"Strategy notes: {strategy_notes}")
    lines.append(f"Memory trace: recalled {c['experiences']} experiences, {c['opinions']} opinions for {recall['entity_id']}.")
    used = [ops[i] for i in used_opinion_ids if i in ops]
    if used:
        lines.append("Opinions used: " + "; ".join(
            f"[{o['statement']} — confidence: {o['confidence']:.2f}, based on {o['n_supporting']} instances"
            f"{' (LOW CONFIDENCE)' if o['low_confidence'] else ''}{', org-wide' if o['scope']=='org' else ''}]" for o in used))
    flags = []
    if recall["empty"]:
        flags.append("no prior history on file — drafted from general best practice")
    flags += [f"STALE {f['category']} fact ({f['age_days']}d): \"{f['content']}\" — confirm before use"
              for f in recall["world_facts"] if f["stale"]]
    flags += [f"CONFLICT in {x['category']}: " + " vs ".join(f'"{c_}"' for c_ in x["contents"]) for x in recall["conflicts"]]
    if not recall["empty"] and recall["memory_gaps"]:
        flags.append("no fresh " + "/".join(recall["memory_gaps"]) + " fact on file — please confirm")
    if flags:
        lines.append("Flags: " + " | ".join(flags))
    return "\n".join(lines)


def verify(text: str, recall_log: list[dict], other_entity_names: list[str] = ()) -> list[str]:
    """Return a list of violations (empty == pass)."""
    v: list[str] = []
    parts = re.split(r"\n---\s*\n", text)
    body, trace = ("\n".join(parts[:-1]), parts[-1]) if len(parts) > 1 else (text, "")
    if not trace or "Memory trace" not in trace:
        return ["missing memory trace block"]
    m = _HEAD.search(trace)
    if not m:
        return ["malformed 'Memory trace:' line"]
    n_exp, n_op, eid = int(m[1]), int(m[2]), m[3]
    logs = [r for r in recall_log if r["entity_id"] == eid]
    if not logs:
        return [f"trace cites entity {eid!r} but no recall was performed for it"]
    last = logs[-1]
    if (n_exp, n_op) != (last["counts"]["experiences"], last["counts"]["opinions"]):
        v.append(f"trace counts ({n_exp},{n_op}) != recall counts "
                 f"({last['counts']['experiences']},{last['counts']['opinions']})")
    real = {(f"{o['confidence']:.2f}", str(o["n_supporting"])) for o in last["opinions"] + last["org_opinions"]}
    for conf, n in _OP.findall(trace):
        if (conf, n) not in real:
            v.append(f"FABRICATED/ALTERED opinion figure: confidence {conf} n={n} not in recall result")
    if _PCT.search(body) or _CONF_BODY.search(body):
        v.append("confidence figure leaked into client-facing draft")
    for name in other_entity_names:
        if re.search(rf"\b{re.escape(name)}\b", body, re.I):
            v.append(f"cross-client leakage: draft mentions other client {name!r}")
    if re.search(r"hindsight|memory trace|our records show|past clients? (?:have|responded)", body, re.I):
        v.append("internal memory language leaked into client-facing draft")
    needs_flag = last["empty"] or last["conflicts"] or any(f["stale"] for f in last["world_facts"])
    if needs_flag and "Flags:" not in trace:
        v.append("recall had stale/conflict/empty condition but no Flags line")
    stale_txt = [f["content"] for f in last["world_facts"] if f["stale"]]
    for s in stale_txt:
        names = re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", s)
        for n in names:
            if n in body:
                v.append(f"stale personnel/pricing detail {n!r} asserted in client-facing draft")
    return v
