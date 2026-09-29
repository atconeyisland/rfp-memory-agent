"""Offline, deterministic demo (no API key). The DRAFTS are canned templates -- this shows the
memory / staleness / correction / guardrail machinery, not LLM writing quality.
Run: python demo.py"""
from rfp_agent import ToolBox, verify, build_trace
from rfp_agent.seed import seeded_store

B = "\033[1m"; R = "\033[91m"; G = "\033[92m"; X = "\033[0m"
def h(t): print(f"\n{B}=== {t} ==={X}")

box = ToolBox(seeded_store()); OTHERS = ["Initech"]

h("1. Cold start: Globex has no memory")
r = box.recall("globex", "uptime SLA")
txt = "We commit to 99.9% monthly availability with service credits.\n" + build_trace(r)
print(txt); print(G + "verifier:" + X, verify(txt, box.recall_log, OTHERS) or "PASS")

h("2. Recall with real, code-computed confidence (Acme)")
r = box.recall("acme", "executive summary framing")
used = [o["id"] for o in r["opinions"] + r["org_opinions"] if "roi_first" in o["statement"]]
txt = "Executive summary: a 3-year ROI model with payback timeline leads this response.\n" + build_trace(r, used, "lead with ROI; keep feature detail in appendix")
print(txt); print(G + "verifier:" + X, verify(txt, box.recall_log, OTHERS) or "PASS")

h("3. Staleness + stale personnel/pricing not asserted")
r = box.recall("acme", "technical lead pricing tier")
txt = "We will confirm the named technical contact and commercial tier with your team.\n" + build_trace(r)
print(txt); print(G + "verifier:" + X, verify(txt, box.recall_log, OTHERS) or "PASS")

h("4. Human correction -> supersede -> visible change on re-ask")
old = next(f for f in r["world_facts"] if f["category"] == "pricing")
print(B + "human:" + X, '"Legacy tier was discontinued last month."')
print(box.correction_ingest("acme", "Legacy tier discontinued last month; Acme is on Enterprise", old["id"], "pricing"))
r2 = box.recall("acme", "pricing tier")
txt = "Pricing is presented on the Enterprise tier.\n" + build_trace(r2)
print(txt); print(G + "verifier:" + X, verify(txt, box.recall_log, OTHERS) or "PASS")

h("5. Guardrail catches a hallucinated confidence + cross-client leak")
c = r2["counts"]
bad = (f"As we did for Initech, we lead with ROI (93% confidence it works).\n---\nMemory trace: recalled {c['experiences']} experiences, "
       f"{c['opinions']} opinions for acme.\nOpinions used: [roi — confidence: 0.93, based on 12 instances]")
for v in verify(bad, box.recall_log, OTHERS): print(R + " x " + X + v)

h("6. Tool failure is data, not a fabricated success")
print(box.dispatch("log_outcome", {"proposal_id": "does-not-exist", "outcome": "won"}))
