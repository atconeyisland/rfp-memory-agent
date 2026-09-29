"""In-memory reference implementation of the Hindsight-style memory contract.

Mirrors the memory types in the original spec (experiences, opinions, world facts)
and adds: supersession (corrections tombstone, never delete), org-level cross-client
patterns, and code-computed opinion confidence.

NOTE: In production, swap this for the real Hindsight service (see hindsight_adapter.py).
The confidence formula below is a MOCK of what the service's reflect step does.
"""
from __future__ import annotations
import difflib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

ORG = "__org__"          # aggregated, client-anonymous patterns live here
STALE_DAYS = 21
STALE_CATEGORIES = {"pricing", "personnel", "feature"}
AUTO_REFLECT_EVERY = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Item:
    id: str
    entity_id: str
    kind: str                      # experience | world_fact | opinion
    content: str
    ts: datetime = field(default_factory=_now)
    outcome: str = "unknown"       # won | lost | unknown (experiences)
    category: str = "other"        # pricing | personnel | feature | requirements | other
    tags: list = field(default_factory=list)
    proposal_id: Optional[str] = None
    source: str = "agent"          # agent | human_correction | reflect
    confidence: Optional[float] = None
    n_supporting: Optional[int] = None
    superseded_by: Optional[str] = None


class MemoryStore:
    def __init__(self, clock=_now):
        self.clock = clock
        self.items: dict[str, Item] = {}
        self.entities: dict[str, list[str]] = {}
        self._n = 0
        self._since_reflect: dict[str, int] = {}

    # ---------- entities ----------
    def register_entity(self, entity_id: str, *names: str):
        self.entities[entity_id] = [n.lower() for n in (entity_id, *names)]

    def resolve_entity(self, name: str) -> list[dict]:
        """Ranked candidates. Caller must ask the human unless top is unambiguous."""
        q = name.lower().strip()
        scored = []
        for eid, aliases in self.entities.items():
            s = max(1.0 if q == a else difflib.SequenceMatcher(None, q, a).ratio() for a in aliases)
            scored.append({"entity_id": eid, "score": round(s, 2)})
        scored.sort(key=lambda d: -d["score"])
        cands = [c for c in scored if c["score"] >= 0.6][:3]
        ok = bool(cands) and cands[0]["score"] >= 0.85 and (
            len(cands) == 1 or cands[0]["score"] - cands[1]["score"] >= 0.1)
        return [{**c, "unambiguous": ok and i == 0} for i, c in enumerate(cands)]

    # ---------- writes ----------
    def _new(self, **kw) -> Item:
        self._n += 1
        it = Item(id=f"m{self._n:04d}", **kw)
        self.items[it.id] = it
        return it

    def retain(self, entity_id, content, kind, outcome="unknown", category="other",
               tags=None, proposal_id=None, source="agent", ts=None) -> dict:
        if kind not in ("world_fact", "experience"):
            raise ValueError("kind must be world_fact or experience")
        if kind == "experience" and outcome not in ("won", "lost", "unknown"):
            raise ValueError("experience requires outcome won|lost|unknown")
        if entity_id not in self.entities:
            raise KeyError(f"unknown entity_id {entity_id!r}; resolve_entity first")
        it = self._new(entity_id=entity_id, kind=kind, content=content, outcome=outcome,
                       category=category, tags=list(tags or []), proposal_id=proposal_id,
                       source=source, ts=ts or self.clock())
        auto = False
        if kind == "experience" and outcome in ("won", "lost"):
            auto = self._tick(entity_id)
        return {"id": it.id, "auto_reflected": auto}

    def _tick(self, entity_id) -> bool:
        self._since_reflect[entity_id] = self._since_reflect.get(entity_id, 0) + 1
        if self._since_reflect[entity_id] >= AUTO_REFLECT_EVERY:
            self.reflect(entity_id)
            return True
        return False

    def log_outcome(self, proposal_id, outcome, notes=None) -> dict:
        if outcome not in ("won", "lost"):
            raise ValueError("outcome must be won|lost")
        hits = [i for i in self.items.values()
                if i.kind == "experience" and i.proposal_id == proposal_id and not i.superseded_by]
        if not hits:
            raise KeyError(f"no experience with proposal_id {proposal_id!r}")
        auto = False
        for i in hits:
            i.outcome = outcome
            if notes:
                i.content += f" [outcome note: {notes}]"
            auto = self._tick(i.entity_id) or auto
        return {"tagged": [i.id for i in hits], "auto_reflected": auto}

    def correct(self, entity_id, text, corrected_item_id=None, category="other") -> dict:
        old = None
        if corrected_item_id:
            old = self.items.get(corrected_item_id)
            if old is None or old.entity_id != entity_id:
                raise KeyError("corrected_item_id not found for this entity")
        it = self._new(entity_id=entity_id, kind="world_fact", content=text, category=category,
                       source="human_correction", ts=self.clock())
        if old:
            old.superseded_by = it.id           # tombstone, never delete (audit trail)
        self.reflect(entity_id)
        return {"id": it.id, "superseded": corrected_item_id, "reflected": True}

    # ---------- reflect (MOCK of the service's synthesis step) ----------
    @staticmethod
    def _conf(wins, n):           # Laplace-smoothed win rate; small n stays humble
        return round((wins + 1) / (n + 2), 2)

    def reflect(self, entity_id) -> list[str]:
        self._since_reflect[entity_id] = 0
        made = []
        for target, sources in [(entity_id, [entity_id]), (ORG, list(self.entities))]:
            tally: dict[str, list[int]] = {}
            for i in self.items.values():
                if (i.kind == "experience" and i.entity_id in sources and not i.superseded_by
                        and i.outcome in ("won", "lost")):
                    for t in i.tags:
                        wn = tally.setdefault(t, [0, 0])
                        wn[0] += i.outcome == "won"
                        wn[1] += 1
            for i in self.items.values():       # retire prior opinions for this scope
                if i.kind == "opinion" and i.entity_id == target and not i.superseded_by:
                    i.superseded_by = "reflect"
            for tag, (w, n) in tally.items():
                op = self._new(entity_id=target, kind="opinion", tags=[tag], source="reflect",
                               content=f"'{tag}' approach: {w} of {n} logged outcomes were wins",
                               confidence=self._conf(w, n), n_supporting=n, ts=self.clock())
                made.append(op.id)
        return made

    # ---------- reads ----------
    def recall(self, entity_id, query, k=8) -> dict:
        q = {t for t in query.lower().replace("?", " ").split() if len(t) > 2}

        def score(i: Item):
            bag = set((i.content + " " + i.category + " " + " ".join(i.tags)).lower().split())
            return (len(q & bag), i.ts)

        def pick(eid, kind):
            pool = [i for i in self.items.values()
                    if i.entity_id == eid and i.kind == kind and not i.superseded_by]
            return sorted(pool, key=score, reverse=True)[:k]

        return {"experiences": pick(entity_id, "experience"),
                "world_facts": pick(entity_id, "world_fact"),
                "opinions": pick(entity_id, "opinion"),
                "org_opinions": pick(ORG, "opinion")}
