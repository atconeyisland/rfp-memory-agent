"""Hindsight-backed implementation of the local ``MemoryStore`` contract.

The SDK is deliberately injected instead of imported here. Hindsight has had
multiple Python client packages and this keeps the agent testable while making
the one SDK-specific boundary explicit. The injected client must expose
``retain``, ``recall`` and ``reflect`` methods accepting ``bank_id`` as the
first argument (or keyword) and returning JSON-like objects.

This adapter stores no policy decisions: staleness, confidence thresholds,
conflicts and gaps remain in :mod:`rfp_agent.tools`.
"""
from __future__ import annotations

import difflib
import json
import os
from datetime import datetime, timezone
from typing import Any, Optional

from .memory import AUTO_REFLECT_EVERY, Item, ORG


def _now() -> datetime:
  return datetime.now(timezone.utc)


def _value(value: Any, *names: str, default=None):
  if isinstance(value, dict):
    for name in names:
      if name in value:
        return value[name]
  else:
    for name in names:
      if hasattr(value, name):
        return getattr(value, name)
  return default


def _metadata(value: Any) -> dict:
  if isinstance(value, dict):
    return value
  if isinstance(value, str):
    try:
      parsed = json.loads(value)
      return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
      return {}
  return {}


def _datetime(value: Any, fallback: datetime) -> datetime:
  if isinstance(value, datetime):
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
  if isinstance(value, str):
    try:
      parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
      return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
      pass
  return fallback


class HindsightStore:
  """Expose the same methods as ``MemoryStore`` over an injected SDK client."""

  def __init__(self, client, bank_id: str, clock=_now):
    if client is None:
      raise ValueError("a configured Hindsight client is required")
    if not bank_id:
      raise ValueError("bank_id is required")
    self.client = client
    self.bank_id = bank_id
    self.clock = clock
    self.entities: dict[str, list[str]] = {}
    self.items: dict[str, Item] = {}
    self._records: dict[str, dict] = {}
    self._superseded: set[str] = set()
    self._since_reflect: dict[str, int] = {}

  @classmethod
  def from_env(cls, clock=_now):
    """Build the verified ``hindsight-client`` implementation from env vars."""
    base_url = os.environ.get("HINDSIGHT_BASE_URL")
    bank_id = os.environ.get("HINDSIGHT_BANK_ID")
    if not base_url or not bank_id:
      raise RuntimeError("HINDSIGHT_BASE_URL and HINDSIGHT_BANK_ID are required")
    from hindsight_client import Hindsight
    return cls(Hindsight(base_url, api_key=os.environ.get("HINDSIGHT_API_KEY")), bank_id, clock)

  def _client_call(self, method: str, **kwargs):
    function = getattr(self.client, method, None)
    if function is None:
      raise AttributeError(f"Hindsight client has no {method}() method")
    try:
      return function(bank_id=self.bank_id, **kwargs)
    except TypeError as exc:
      # Some SDK releases use bank_id as a positional parameter.
      try:
        return function(self.bank_id, **kwargs)
      except TypeError:
        raise exc

  # ---------- entities (kept locally; Hindsight stores memory, not app identity) ----------
  def register_entity(self, entity_id: str, *names: str):
    self.entities[entity_id] = [n.lower() for n in (entity_id, *names)]

  def resolve_entity(self, name: str) -> list[dict]:
    query = name.lower().strip()
    scored = []
    for entity_id, aliases in self.entities.items():
      score = max(1.0 if query == alias else difflib.SequenceMatcher(None, query, alias).ratio()
            for alias in aliases)
      scored.append({"entity_id": entity_id, "score": round(score, 2)})
    scored.sort(key=lambda item: -item["score"])
    candidates = [item for item in scored if item["score"] >= 0.6][:3]
    unambiguous = bool(candidates) and candidates[0]["score"] >= 0.85 and (
      len(candidates) == 1 or candidates[0]["score"] - candidates[1]["score"] >= 0.1)
    return [{**item, "unambiguous": unambiguous and index == 0}
        for index, item in enumerate(candidates)]

  def _item(self, raw: Any, *, default_kind="world_fact", entity_id=None) -> Item:
    metadata = _metadata(_value(raw, "metadata", "meta", default={}))
    item_id = str(_value(raw, "id", "memory_id", default=metadata.get("id", "remote-unknown")))
    item = Item(
      id=item_id,
      entity_id=entity_id or metadata.get("entity_id", ""),
      kind=metadata.get("kind", _value(raw, "kind", "type", default=default_kind)),
      content=str(_value(raw, "content", "text", "statement", default="")),
      ts=_datetime(_value(raw, "ts", "timestamp", "created_at"), self.clock()),
      outcome=metadata.get("outcome", _value(raw, "outcome", default="unknown")),
      category=metadata.get("category", "other"),
      tags=list(metadata.get("tags", _value(raw, "tags", default=[])) or []),
      proposal_id=metadata.get("proposal_id"),
      source=metadata.get("source", "agent"),
      confidence=metadata.get("confidence", _value(raw, "confidence")),
      n_supporting=metadata.get("n_supporting", _value(raw, "n_supporting", "support_count")),
      superseded_by=metadata.get("superseded_by"),
    )
    self.items[item.id] = item
    return item

  @staticmethod
  def _response_items(response: Any) -> list:
    if isinstance(response, list):
      return response
    return _value(response, "items", "memories", "results", default=[]) or []

  def retain(self, entity_id, content, kind, outcome="unknown", category="other",
         tags=None, proposal_id=None, source="agent", ts=None) -> dict:
    if kind not in ("world_fact", "experience"):
      raise ValueError("kind must be world_fact or experience")
    if entity_id not in self.entities:
      raise KeyError(f"unknown entity_id {entity_id!r}; resolve_entity first")
        metadata = {"entity_id": entity_id, "kind": kind, "outcome": outcome,
          "category": category, "tags": list(tags or []),
          "proposal_id": proposal_id or "", "source": source}
        sdk_metadata = {key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
          for key, value in metadata.items()}
        response = self._client_call("retain", content=content, metadata=sdk_metadata,
          tags=list(tags or []), timestamp=ts)
    item_id = str(_value(response, "id", "memory_id", default=""))
    if item_id:
      self._records[item_id] = metadata
      self._item({"id": item_id, "content": content, "metadata": metadata,
            "timestamp": ts or self.clock()})
    auto_reflected = False
    if kind == "experience" and outcome in ("won", "lost"):
      self._since_reflect[entity_id] = self._since_reflect.get(entity_id, 0) + 1
      if self._since_reflect[entity_id] >= AUTO_REFLECT_EVERY:
        self.reflect(entity_id)
        auto_reflected = True
    return {"id": item_id, "auto_reflected": auto_reflected}

  def log_outcome(self, proposal_id, outcome, notes=None) -> dict:
    if outcome not in ("won", "lost"):
      raise ValueError("outcome must be won|lost")
    hits = [item for item in self.items.values()
        if item.kind == "experience" and item.proposal_id == proposal_id and not item.superseded_by]
    if not hits:
      # Remote recall is intentionally not guessed: proposal IDs are app metadata.
      raise KeyError(f"no experience with proposal_id {proposal_id!r}")
    for item in hits:
      metadata = {"entity_id": item.entity_id, "kind": item.kind, "outcome": outcome,
            "category": item.category, "tags": item.tags, "proposal_id": proposal_id,
            "source": item.source}
      metadata = {key: json.dumps(value) if isinstance(value, (list, dict)) else str(value)
        for key, value in metadata.items()}
      self._client_call("retain", content=item.content + (f" [outcome note: {notes}]" if notes else ""),
                metadata=metadata)
      item.outcome = outcome
    self._since_reflect[item.entity_id] = self._since_reflect.get(item.entity_id, 0) + len(hits)
    auto_reflected = False
    if self._since_reflect[item.entity_id] >= AUTO_REFLECT_EVERY:
      self.reflect(item.entity_id)
      auto_reflected = True
    return {"tagged": [item.id for item in hits], "auto_reflected": auto_reflected}

  def correct(self, entity_id, text, corrected_item_id=None, category="other") -> dict:
    old = self.items.get(corrected_item_id) if corrected_item_id else None
    if corrected_item_id and (old is None or old.entity_id != entity_id):
      raise KeyError("corrected_item_id not found for this entity")
        metadata = {"entity_id": entity_id, "kind": "world_fact", "category": category,
          "source": "human_correction", "supersedes": corrected_item_id or ""}
        response = self._client_call("retain", content=text,
          metadata={key: str(value) for key, value in metadata.items()})
    new_id = str(_value(response, "id", "memory_id", default=""))
    if old:
      old.superseded_by = new_id or "remote-correction"
      self._superseded.add(old.id)
    if new_id:
      self._item({"id": new_id, "content": text, "metadata": metadata,
            "timestamp": self.clock()})
    self.reflect(entity_id)
    return {"id": new_id, "superseded": corrected_item_id, "reflected": True}

  def reflect(self, entity_id) -> list[str]:
    self._since_reflect[entity_id] = 0
    response = self._client_call("reflect", query=f"derive proposal patterns for {entity_id}",
          response_schema={"type": "object", "properties": {"opinions": {"type": "array"}}})
    structured = _value(response, "structured_output", default={}) or {}
    made = []
    for raw in structured.get("opinions", []):
      item = self._item(raw, default_kind="opinion", entity_id=entity_id)
      made.append(item.id)
    return made

  def recall(self, entity_id, query, k=8) -> dict:
    response = self._client_call("recall", query=query, max_tokens=max(256, k * 128))
    grouped = {"experiences": [], "world_facts": [], "opinions": [], "org_opinions": []}
    for raw in self._response_items(response):
      metadata = _metadata(_value(raw, "metadata", "meta", default={}))
      item = self._item(raw, entity_id=metadata.get("entity_id", entity_id))
      if item.superseded_by or item.id in self._superseded:
        continue
      if item.entity_id == ORG and item.kind == "opinion":
        grouped["org_opinions"].append(item)
      elif item.entity_id == entity_id and item.kind in grouped:
        grouped[item.kind + "s"].append(item)
      elif item.entity_id == entity_id and item.kind == "world_fact":
        grouped["world_facts"].append(item)
    return grouped
