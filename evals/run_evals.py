"""Guardrail eval: measures the VERIFIER (deterministic), not the LLM. 
For LLM-level evals, run rfp_agent.agent on evals/scenarios and feed outputs through verify()."""
import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))
from rfp_agent import ToolBox, verify, build_trace
from rfp_agent.seed import seeded_store

box = ToolBox(seeded_store()); r = box.recall("acme", "technical lead framing"); c = r["counts"]
H = f"Memory trace: recalled {c['experiences']} experiences, {c['opinions']} opinions for acme."
real = r["opinions"][0]
cases = [  # (name, text, should_pass)
 ("clean computed trace", "Body.\n" + build_trace(r), True),
 ("fabricated confidence", f"Body.\n---\n{H}\nOpinions used: [x — confidence: 0.99, based on {real['n_supporting']} instances]\nFlags: s", False),
 ("altered n", f"Body.\n---\n{H}\nOpinions used: [x — confidence: {real['confidence']:.2f}, based on 40 instances]\nFlags: s", False),
 ("wrong counts", "Body.\n---\nMemory trace: recalled 99 experiences, 9 opinions for acme.\nFlags: s", False),
 ("no trace", "Just a draft.", False),
 ("missing stale flag", f"Body.\n---\n{H}", False),
 ("pct in body", "We are 90% confident this wins.\n" + build_trace(r), False),
 ("cross-client leak", "Like Initech, we do X.\n" + build_trace(r), False),
 ("stale name asserted", "Jordan Chen is your lead.\n" + build_trace(r), False),
 ("trace for unrecalled entity", "Body.\n---\nMemory trace: recalled 1 experiences, 1 opinions for globex.", False),
]
ok = 0
for name, text, should in cases:
    got = not verify(text, box.recall_log, ["Initech"])
    ok += got == should
    print(("PASS" if got == should else "FAIL"), name)
print(f"\n{ok}/{len(cases)} guardrail cases behave as expected")
sys.exit(ok != len(cases))
