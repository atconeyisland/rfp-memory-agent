# Critique

## A. Problems in the original prompt (fixed in v2 unless noted)
1. **LLM asked to do arithmetic and bookkeeping.** Age > 21 days, "n < 3", "every 3–5 experiences" are code jobs. Models drift on these. → moved to `tools.py`/`memory.py`.
2. **Honesty enforced only by instruction.** "NEVER report a fabricated confidence" has no check. → `verifier.py` compares the trace with the recall result; `build_trace()` computes it.
3. **Client-facing draft and internal trace shared one output.** Worse, step 5c says to write "one past client responded well to..." *in the draft* — that leaks internal history to the client. → hard split, verifier blocks it.
4. **ID mismatch:** `outcome_logger` takes a `proposal_id`, but recall returns experience `id`s, and nothing registers proposals. → `retain` now takes `proposal_id`; `log_outcome` resolves by it.
5. **Six tools, strict sequence, high latency.** staleness_check per item = N extra calls. → annotation is inside `recall`; reflect is automatic (6 tools → 5, and none require sequencing judgment).
6. **Entity resolution = "ask the human" every time** → friction. → `resolve_entity` with fuzzy match; ask only when ambiguous.
7. **No cross-client learning** even though "what wins for enterprise clients" is the most valuable signal — but naïvely adding it risks leaking client data. → org-level anonymous patterns.
8. **Opinions read as causal.** "ROI-first outperforms" from 5 outcomes is correlation with heavy confounding (deal size, buyer, price). → prompt says "associated with wins".
9. **No prompt-injection defense** for a system that ingests RFP documents and writes to long-term memory (memory poisoning). → rule added. *Partially fixed: it's a prompt rule, not enforcement.*
10. **Corrections could be lost or overwrite history.** → supersede with audit trail.
11. **Unknown-outcome experiences** are in the spec but their weight in opinions is undefined. → mock ignores them; real service behavior unknown.

## B. Problems in MY work (be skeptical of these)
1. **The memory store and reflect are mocks.** Confidence = Laplace-smoothed win rate over tags. The real Hindsight synthesizes opinions differently. `hindsight_adapter.py` is an unimplemented stub and I have not verified the SDK's API. **Biggest risk for a hackathon: judges ask "is this actually using Hindsight?"** Wire the adapter before the demo, or say plainly that it's a reference implementation.
2. **No LLM-level eval was run.** I had no API key here. `evals/run_evals.py` tests the verifier on hand-written outputs; it says nothing about how often the real model violates the rules. `agent.py` is untested end-to-end. Treat it as unproven.
3. **Demo drafts are canned strings.** The demo proves the machinery, not proposal quality.
4. **The verifier is regex-based and shallow.** Easy false negatives: paraphrased leaks ("a similar customer of ours"), a stale fact stated without a name (`_` only checks capitalized two-word names), confidence expressed in words. False positives: a legitimate "past clients" phrase in a genuine client-facing testimonial. It catches the *common* failures, not adversarial ones.
5. **Only substring cross-client check** uses each client's first alias; aliases/subsidiaries are missed.
6. **Retrieval is keyword overlap** — no embeddings/semantic search. Fine for the toy set, weak at scale (the real service should replace it).
7. **Staleness is one global 21-day rule** on three categories; real staleness varies (a CTO changes less often than pricing). Per-category TTLs would be better.
8. **Conflict detection is crude:** any two live facts in one category count as a conflict, even if compatible (two different contacts can both be true).
9. **`memory_gaps` prompts a question every time** for clients without fresh pricing/personnel facts — could become annoying; needs a rate limit.
10. **No auth/multi-tenancy, persistence, or concurrency.** State lives in process memory. Two users correcting simultaneously is undefined.
11. **Small seed data (9 items)** makes every number look tidy. Real data will be noisier; low-n opinions will dominate at first.
12. **I did not use a UI.** For a competitive hackathon, a 2-pane view (draft | live memory trace with diff on correction) would demo far better than a terminal. Cheapest high-impact next step.

## C. If I had one more day
(1) Real Hindsight adapter + a real run, (2) LLM-level eval: 30 scenarios × model → verifier pass rate, before/after v1 vs v2 prompt (the headline metric), (3) UI with correction diff, (4) per-category TTLs, (5) semantic retrieval.

## D. Work completed in this pass
1. **Adapter:** `HindsightStore` now exposes the `MemoryStore` methods over an injected client, normalizes JSON-like SDK responses, keeps entity resolution local, and sends supersession metadata before reflecting. This is still **not live-certified**: the requested Hindsight documentation URL is a placeholder, no Hindsight package is installed, and SDK response shapes may differ.
2. **Runtime:** the project's 12 tests and offline demo pass, and the Anthropic/FastAPI dependencies are installed. The live agent remains blocked only by the missing `ANTHROPIC_API_KEY`; the CLI now reports that cleanly. The original root-level pytest command also collects an unrelated workspace test; use `cd rfp-memory-agent && python -m pytest -q`.
3. **UI:** the active browser controller calls `/api/state` and `/api/correction`; the old in-browser mock is inert but still present as rollback reference and should be deleted before a polished submission.
4. **Evaluation:** no honest LLM pass-rate numbers exist until a key, model, and Hindsight endpoint are supplied. Any table with invented numbers would undermine the project's central claim.

## E. Productization pass
The UI now presents a real operator workspace rather than a canned-demo headline: pasted RFP text is sent to FastAPI, instruction-like markers are surfaced as a security finding, memory counts and verifier status are visible, and corrections are entered by the operator and persisted for the running process. The remaining prototype boundaries are deliberate and visible: seeded in-process storage, no authentication or multi-tenant isolation, no live LLM draft generation, and no SDK-certified Hindsight integration until the missing endpoint/docs are provided.
