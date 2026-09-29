"""Live agent loop (needs ANTHROPIC_API_KEY). Wraps the model with tools + verifier + one repair pass.
Usage: python -m rfp_agent.agent "Draft Acme Corp's answer on our uptime SLA"
"""
from __future__ import annotations
import os, sys, pathlib
from .seed import seeded_store
from .hindsight_adapter import HindsightStore
from .tools import ToolBox, TOOL_SCHEMAS
from .verifier import verify

MODEL = os.environ.get("RFP_MODEL", "claude-sonnet-5-5")
PROMPT = (pathlib.Path(__file__).parent.parent / "prompts" / "system_prompt_v2.md").read_text()


def runtime_store():
    if os.environ.get("HINDSIGHT_BASE_URL") and os.environ.get("HINDSIGHT_BANK_ID"):
        store = HindsightStore.from_env()
        store.register_entity("acme", "acme corp", "acme corporation")
        store.register_entity("initech", "initech inc")
        store.register_entity("globex", "globex corporation")
        return store
    return seeded_store()


def run(user_msg: str, box: ToolBox, history=None, max_steps=8):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError("ANTHROPIC_API_KEY is not set; live agent run is unavailable")
    import anthropic
    client = anthropic.Anthropic()
    msgs = list(history or []) + [{"role": "user", "content": user_msg}]
    others = [n for e in box.store.entities for n in box.store.entities[e][:1]]
    for repair in range(2):                       # at most one repair round
        for _ in range(max_steps):
            r = client.messages.create(model=MODEL, max_tokens=2000, system=PROMPT,
                                       tools=TOOL_SCHEMAS, messages=msgs)
            msgs.append({"role": "assistant", "content": r.content})
            calls = [b for b in r.content if b.type == "tool_use"]
            if not calls:
                break
            msgs.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": c.id,
                 "content": str(box.dispatch(c.name, c.input))} for c in calls]})
        text = "".join(b.text for b in r.content if b.type == "text")
        # only forbid *other* clients' names; the active client's name is fine
        active = box.recall_log[-1]["entity_id"] if box.recall_log else None
        violations = verify(text, box.recall_log, [n for n in others if n != active])
        if not violations:
            return text, [], msgs
        msgs.append({"role": "user", "content":
                     "Guardrail check failed:\n- " + "\n- ".join(violations) +
                     "\nFix these and return the full corrected response."})
    return text, violations, msgs


if __name__ == "__main__":
    try:
        box = ToolBox(runtime_store())
        out, viol, _ = run(" ".join(sys.argv[1:]) or "Draft Acme Corp's answer on our uptime SLA", box)
        print(out)
        if viol:
            print("\n[UNRESOLVED GUARDRAIL VIOLATIONS]", *viol, sep="\n- ")
    except RuntimeError as exc:
        raise SystemExit(f"BLOCKED: {exc}") from exc
