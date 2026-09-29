from datetime import timedelta
from .memory import MemoryStore, _now


def seeded_store(clock=_now) -> MemoryStore:
    s = MemoryStore(clock)
    ago = lambda d: clock() - timedelta(days=d)
    s.register_entity("acme", "acme corp", "acme corporation")
    s.register_entity("initech", "initech inc")
    s.register_entity("globex", "globex corporation")          # zero memory on purpose
    R = dict(kind="experience")
    s.retain("acme", "FY24 platform RFP: led with 3-year ROI model; buyer cited it in award letter", outcome="won", tags=["roi_first"], proposal_id="acme-24", ts=ago(300), **R)
    s.retain("acme", "Security questionnaire: ROI-first exec summary, CFO engaged", outcome="won", tags=["roi_first"], proposal_id="acme-24b", ts=ago(200), **R)
    s.retain("acme", "Renewal bid: ROI-first with payback table", outcome="won", tags=["roi_first"], proposal_id="acme-25", ts=ago(90), **R)
    s.retain("acme", "Add-on bid: feature-list heavy, no ROI section", outcome="lost", tags=["feature_list"], proposal_id="acme-25b", ts=ago(60), **R)
    s.retain("initech", "Data platform bid: ROI-first, CFO sponsor", outcome="won", tags=["roi_first"], proposal_id="init-25", ts=ago(120), **R)
    s.retain("initech", "Pilot bid: ROI-first but weak references", outcome="lost", tags=["roi_first"], proposal_id="init-25b", ts=ago(80), **R)
    s.retain("acme", "Acme's technical lead is Jordan Chen", "world_fact", category="personnel", ts=ago(40))
    s.retain("acme", "Acme was quoted the Legacy tier", "world_fact", category="pricing", ts=ago(30))
    s.retain("acme", "Acme procurement checklist requires 99.95% uptime SLA with service credits", "world_fact", category="requirements", ts=ago(10))
    s.reflect("acme"); s.reflect("initech")
    return s
