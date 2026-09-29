"""Tool layer. Everything the LLM must NOT do by itself (date math, threshold
checks, conflict detection, reflect cadence) is done here, in code."""
from __future__ import annotations
from .memory import MemoryStore, Item, STALE_DAYS, STALE_CATEGORIES, ORG

KEY_CATEGORIES = ("pricing", "personnel")   # things a proposal usually depends on


class ToolBox:
    def __init__(self, store: MemoryStore):
        self.store = store
        self.recall_log: list[dict] = []     # ground truth for the verifier

    # ---- annotation: staleness & confidence computed in code, not by the LLM ----
    def _age(self, it: Item) -> int:
        return (self.store.clock() - it.ts).days

    def _fact(self, it: Item) -> dict:
        age = self._age(it)
        stale = it.category in STALE_CATEGORIES and age > STALE_DAYS and it.source != "human_correction"
        return {"id": it.id, "content": it.content, "category": it.category, "age_days": age,
                "stale": stale,
                "stale_reason": f"{it.category} fact is {age}d old (> {STALE_DAYS}d)" if stale else None,
                "human_correction": it.source == "human_correction"}

    def _exp(self, it: Item) -> dict:
        return {"id": it.id, "content": it.content, "outcome": it.outcome, "tags": it.tags,
                "age_days": self._age(it), "proposal_id": it.proposal_id}

    def _op(self, it: Item) -> dict:
        low = it.n_supporting < 3 or it.confidence < 0.6
        return {"id": it.id, "statement": it.content, "confidence": it.confidence,
                "n_supporting": it.n_supporting, "scope": "org" if it.entity_id == ORG else "client",
                "low_confidence": low,
                "low_confidence_reason": ("n<3" if it.n_supporting < 3 else "confidence<0.6") if low else None}

    # ---- tools exposed to the LLM ----
    def resolve_entity(self, name: str):
        return {"candidates": self.store.resolve_entity(name)}

    def recall(self, entity_id: str, query: str, k: int = 8):
        if entity_id not in self.store.entities:
            return {"error": f"unknown entity_id {entity_id!r}. Call resolve_entity."}
        raw = self.store.recall(entity_id, query, k)
        facts = [self._fact(i) for i in raw["world_facts"]]
        out = {
            "entity_id": entity_id,
            "experiences": [self._exp(i) for i in raw["experiences"]],
            "world_facts": facts,
            "opinions": [self._op(i) for i in raw["opinions"]],
            "org_opinions": [self._op(i) for i in raw["org_opinions"]],
        }
        # conflicts: two live facts in the same category with different content
        by_cat: dict[str, list[dict]] = {}
        for f in facts:
            by_cat.setdefault(f["category"], []).append(f)
        out["conflicts"] = [{"category": c, "ids": [f["id"] for f in fs],
                             "contents": [f["content"] for f in fs]}
                            for c, fs in by_cat.items() if c != "other" and len(fs) > 1]
        # gaps: key categories with no fresh fact -> tell the human what to confirm
        fresh = {f["category"] for f in facts if not f["stale"]}
        out["memory_gaps"] = [c for c in KEY_CATEGORIES if c not in fresh]
        out["counts"] = {"experiences": len(out["experiences"]),
                         "opinions": len(out["opinions"]),
                         "org_opinions": len(out["org_opinions"])}
        out["empty"] = not (out["experiences"] or out["world_facts"] or out["opinions"])
        self.recall_log.append(out)
        return out

    def retain(self, entity_id, content, type, outcome="unknown", category="other",
               tags=None, proposal_id=None):
        return self.store.retain(entity_id, content, type, outcome, category, tags, proposal_id)

    def log_outcome(self, proposal_id, outcome, notes=None):
        return self.store.log_outcome(proposal_id, outcome, notes)

    def correction_ingest(self, entity_id, correction_text, corrected_item_id=None, category="other"):
        return self.store.correct(entity_id, correction_text, corrected_item_id, category)

    def dispatch(self, name, args):
        """Never raises: tool failures come back as data so the model can't fabricate around them."""
        try:
            return getattr(self, name)(**args)
        except Exception as e:  # noqa: BLE001
            return {"error": f"{type(e).__name__}: {e}", "memory_unavailable": True}


def _s(props, req):
    return {"type": "object", "properties": props, "required": req}

_S = {"type": "string"}
TOOL_SCHEMAS = [
    {"name": "resolve_entity", "description": "Map a client name as written by the human to an entity_id. If no candidate has unambiguous=true, ASK the human; never guess.",
     "input_schema": _s({"name": _S}, ["name"])},
    {"name": "recall", "description": "Retrieve memory for a client before drafting. Returns staleness, low-confidence flags, conflicts and memory gaps already computed. Empty result is valid, not an error.",
     "input_schema": _s({"entity_id": _S, "query": _S, "k": {"type": "integer"}}, ["entity_id", "query"])},
    {"name": "retain", "description": "Store a CONFIRMED fact or a logged experience. Never speculative content. Include tags (e.g. roi_first) so reflect can learn patterns, and proposal_id for experiences.",
     "input_schema": _s({"entity_id": _S, "content": _S, "type": {"type": "string", "enum": ["world_fact", "experience"]},
                         "outcome": {"type": "string", "enum": ["won", "lost", "unknown"]},
                         "category": {"type": "string", "enum": ["pricing", "personnel", "feature", "requirements", "other"]},
                         "tags": {"type": "array", "items": _S}, "proposal_id": _S}, ["entity_id", "content", "type"])},
    {"name": "log_outcome", "description": "Record the real-world result of a past proposal. Reflect runs automatically.",
     "input_schema": _s({"proposal_id": _S, "outcome": {"type": "string", "enum": ["won", "lost"]}, "notes": _S}, ["proposal_id", "outcome"])},
    {"name": "correction_ingest", "description": "Call IMMEDIATELY when a human says something is wrong/outdated. Supersedes the old item (kept for audit) and re-runs reflect.",
     "input_schema": _s({"entity_id": _S, "correction_text": _S, "corrected_item_id": _S,
                         "category": {"type": "string", "enum": ["pricing", "personnel", "feature", "requirements", "other"]}}, ["entity_id", "correction_text"])},
]
