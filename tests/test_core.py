from datetime import timedelta
from rfp_agent import ToolBox, verify, build_trace
from rfp_agent.seed import seeded_store


def box():
    return ToolBox(seeded_store())


def test_cold_start_is_valid_not_error():
    b = box(); r = b.recall("globex", "uptime SLA")
    assert r["empty"] and "error" not in r
    assert "no prior history" in build_trace(r)


def test_staleness_computed_in_code():
    r = box().recall("acme", "technical lead")
    f = {x["category"]: x for x in r["world_facts"]}
    assert f["personnel"]["stale"] and f["pricing"]["stale"]
    assert not f["requirements"]["stale"]


def test_low_confidence_flagging():
    r = box().recall("acme", "framing")
    ops = {o["statement"].split("'")[1]: o for o in r["opinions"]}
    assert ops["feature_list"]["low_confidence"]          # n=1
    assert not ops["roi_first"]["low_confidence"] or ops["roi_first"]["n_supporting"] >= 3


def test_org_pattern_aggregates_across_clients():
    r = box().recall("acme", "framing")
    org = {o["statement"]: o for o in r["org_opinions"]}
    assert any("roi_first" in k and o["n_supporting"] == 5 for k, o in org.items())


def test_correction_supersedes_and_changes_recall():
    b = box(); r0 = b.recall("acme", "pricing")
    old = next(f for f in r0["world_facts"] if f["category"] == "pricing")
    b.correction_ingest("acme", "Legacy tier was discontinued last month; Acme is on Enterprise", old["id"], "pricing")
    r1 = b.recall("acme", "pricing")
    pf = [f for f in r1["world_facts"] if f["category"] == "pricing"]
    assert len(pf) == 1 and pf[0]["human_correction"] and not pf[0]["stale"]
    assert old["id"] not in [f["id"] for f in r1["world_facts"]]
    assert b.store.items[old["id"]].superseded_by            # audit trail kept


def test_conflict_detected():
    b = box(); b.retain("acme", "Acme is on Enterprise tier", "world_fact", category="pricing")
    r = b.recall("acme", "pricing")
    assert r["conflicts"] and r["conflicts"][0]["category"] == "pricing"


def test_auto_reflect_after_three_outcomes():
    b = box(); s = b.store
    for i in range(3):
        res = s.retain("globex", f"bid {i}", "experience", outcome="won", tags=["roi_first"], proposal_id=f"g{i}")
    assert res["auto_reflected"]
    assert any(o["scope"] == "client" for o in b.recall("globex", "x")["opinions"])


def test_log_outcome_unknown_proposal_is_error_not_fabrication():
    out = box().dispatch("log_outcome", {"proposal_id": "nope", "outcome": "won"})
    assert out["memory_unavailable"]


def test_entity_resolution_ambiguity():
    s = seeded_store()
    assert s.resolve_entity("Acme Corp")[0]["unambiguous"]
    assert not s.resolve_entity("Zzz Holdings")


def test_verifier_passes_computed_trace():
    b = box(); r = b.recall("acme", "framing")
    used = [o["id"] for o in r["opinions"] if "roi_first" in o["statement"]]
    txt = "We lead with measurable ROI.\n" + build_trace(r, used)
    assert verify(txt, b.recall_log, ["Initech"]) == []


def test_verifier_catches_fabricated_confidence():
    b = box(); r = b.recall("acme", "framing")
    c = r["counts"]
    txt = f"Draft.\n---\nMemory trace: recalled {c['experiences']} experiences, {c['opinions']} opinions for acme.\nOpinions used: [roi — confidence: 0.93, based on 12 instances]\nFlags: x"
    assert any("FABRICATED" in x for x in verify(txt, b.recall_log))


def test_verifier_catches_leaks_and_missing_flags():
    b = box(); r = b.recall("acme", "technical lead")
    c = r["counts"]
    txt = ("Jordan Chen will lead. As Initech learned, our records show 88% confidence.\n---\n"
           f"Memory trace: recalled {c['experiences']} experiences, {c['opinions']} opinions for acme.")
    v = " ".join(verify(txt, b.recall_log, ["Initech"]))
    assert "cross-client" in v and "confidence figure" in v and "no Flags" in v and "Jordan Chen" in v
