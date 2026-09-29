# RFP Memory Agent — "an agent that remembers what actually won, and admits what it doesn't know"

Built on a Hindsight-style memory contract (experiences / opinions / world facts).

## The one idea that makes this different
Most "agent with memory" demos **ask the LLM nicely** to be honest about its memory. This one **doesn't trust the LLM with anything checkable**:

| Concern | Original spec | This project |
|---|---|---|
| Staleness (21-day rule) | LLM does date math | Computed in code, returned as `stale` flags |
| Confidence numbers | "never fabricate" (a request) | Trace is *built in code*; a verifier rejects any number not in the recall result |
| When to reflect | LLM counts to 3–5 | Automatic (every 3 outcomes + every correction) |
| Client-facing vs internal | Trace appended to the draft | Hard split; verifier blocks memory language, confidence figures and other clients' names in the client part |
| Cross-client learning | none (unsafe if added naively) | Anonymous org-level patterns, aggregated across clients, never client-identifying |
| Conflicting / missing facts | prompt says "surface both" | `conflicts` and `memory_gaps` computed in code; agent asks the one question that fills the biggest gap |
| Corrections | retain + reflect | Supersede with audit trail (nothing deleted), visible change on re-ask |
| Tool failure | prompt says don't fabricate | Failures return `{"memory_unavailable": true}` as data |
| Prompt injection via RFP text | not addressed | Explicit rule + retain-only-confirmed rule |

## Run it (no API key needed)
```bash
pip install -r requirements.txt
python -m pytest -q          # 12 tests
python demo.py               # 6-scene offline walkthrough
python evals/run_evals.py    # 10 guardrail cases
```

The offline path is the reproducible submission path. Anthropic is optional for live model generation:

```powershell
$env:ANTHROPIC_API_KEY="your-key"
python -m rfp_agent.agent "Draft Acme Corp's answer on uptime SLA"
```

## 90-second demo script
1. **Cold start** (Globex): "no prior history" is shown as an honest signal, not an error.
2. **Acme framing**: real 0.80 / n=3 client opinion and 0.71 / n=5 org-wide pattern, copied verbatim into the trace.
3. **Stale facts**: Jordan Chen (40d) and Legacy tier (30d) are flagged, and the draft is written *around* them.
4. **Correction live**: "Legacy tier was discontinued" → old fact superseded → same question now answers with the new fact, unprompted.
5. **Break it on purpose**: show a hallucinated "93% confidence" + a leaked client name being caught by the verifier.

## Layout
`prompts/system_prompt_v2.md` · `rfp_agent/{memory,tools,verifier,agent,seed}.py` · `demo.py` · `evals/` · `tests/` · `CRITIQUE.md` (read this)

## Honest status
See CRITIQUE.md. The offline contract tests pass, but live Hindsight and LLM-level evaluation require a real Hindsight SDK/API configuration and `ANTHROPIC_API_KEY`. Run `python evals/llm_eval.py` to generate measured V1/V2 rates; this README does not contain invented numbers.

## Live UI
```bash
uvicorn ui.server:app --reload
```
Open `http://127.0.0.1:8000`. The UI calls the FastAPI `ToolBox` endpoints; it does not own a second memory dataset.

## Submission

- [Submission kit](SUBMISSION.md): judge flow, claims boundary, and publishing checklist
- [Article draft](ARTICLE.md): hackathon article
- [Demo script](DEMO_SCRIPT.md): 90-second walkthrough
- [.env.example](.env.example): optional live-model configuration
