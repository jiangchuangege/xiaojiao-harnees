# XiaoJiao · 小焦

**English** ｜ [中文](README.md)

**A body for a 4B local model: capability lives in the carrier, not in the model.**

> **Swap the model, keep the assistant.** Memory, persona, tools and safety boundaries all live
> in the framework *around* the model. The model itself is a replaceable part — plug in a 4B,
> a 70B, a cloud endpoint or any OpenAI-compatible API, and it is still the same assistant.
> **Its ceiling is set by the architecture, not by the parameter count.**

That is not a slogan — it has a checkable criterion:

> **One identical sentence. At energy 0.95 the tool table is long and keeps the exploration
> tools; at energy 0.10 the tool table is genuinely shorter (6 → 0).**
> State is not "written into the prompt to persuade it" — **code actually changes the world
> it has in hand this turn.**

100% local. Models, memory and sessions never leave your machine.

---

## Why this is not "yet another wrapper"

Most projects that make a small model look big do it by **changing what the model is told**.
We tried that first, and it failed — in a way that is reproducible and now documented:

- **Static self-description injection failed in all four attempts** (three injection points plus
  a prefill variant). A 4B model treats a fixed self-description as *background material*,
  not as *its own current state*. Asked "what are you doing?", it still replies
  "I am reading your memory."
- **What worked** was making state change the model's *situation* instead of its prompt:
  a code-level policy trims the tool table, compresses context, and cancels proactive
  behaviour. The acceptance criterion is "**this turn's tool table really got shorter**",
  not "it said it was tired".
- The state changes are recorded as **causes** and fed back into the next turn's policy:
  `[input trimmed] because energy is low / level=mid → exploration tools removed (6→0)`.

The other half — teaching the model to *use* those facts in its own words — is a separate
mechanism (dynamic first-person present-tense self-narration). It works at the **wording**
level. We do **not** claim it produces subjective experience; that layer is not observable
from the carrier, and we say so.

---

## What it actually does

| | |
|---|---|
| **Talks and remembers** | Conversation memory is stored outside the model and retrieved on demand — the context window does not grow with conversation length |
| **Uses tools** | 70+ tools; the carrier decides which subset is loaded per turn |
| **Works the web** | Fetches pages, searches, aggregates vulnerabilities (NVD), with SSRF/robots/rate-limit guards |
| **Generates media** | Video (ComfyUI + Wan2.1), podcast, music, diagrams — models are swapped in and out on demand |
| **Runs itself** | It decides when to sleep (writes `sleep: yes/no` itself; the carrier only reads that field), wakes itself, and keeps a heartbeat while suspended |
| **Has a doctor** | 18 model-symptom classes → four-level diagnosis → four-level treatment → records → prevention |
| **Stays safe** | Deleting files is hard-blocked at the carrier layer, independent of permission settings |

Optional: integrates with the open-source **N.E.K.O.** desktop avatar layer.

---

## Quick start (~2 minutes)

```bash
git clone https://github.com/jiangchuangege/xiaojiao-harness.git
cd xiaojiao-harness
python start_xiaojiao.py
```

Then open the local address printed in the terminal.

- **The service itself does not need a model** — a fresh clone starts and answers `/health`
  and `/api/models` (verified by a test in CI). **To actually chat and work, it needs a
  brain**: a local model (4B is enough) or any OpenAI-compatible endpoint.
- One-click installer (model / llama-server / Chrome / ComfyUI) → [`docs/install.md`](docs/install.md)
- Post-install self-check → [`docs/quickstart.md`](docs/quickstart.md)

---

## Verified numbers (default config)

| Item | Result |
|---|---|
| Feature gap suite | 60 / 60 |
| Acceptance suite | 59 / 59 |
| Stress suite | 248 / 249 · 100% (0 failures, 1 data-side skip) |
| Integration scenes | 19 / 19 |
| Perception layer (8 sentences) | 7 / 8, with the two critical ones both judged "tense" |
| State → tool table | same sentence, energy 0.95 vs 0.10 → tool table 6 → 0 |
| Mermaid diagrams / docs gates | 150 figures, 0 problems; docs checks 0 errors |

---

## Known limits (we keep these visible)

- **Metacognition does not fully work yet.** After routing seven categories through
  perception → heart → brain, the 4B still confuses *source*: it can answer
  "how did you know that?" correctly once, then get "did you compute that yourself?" wrong.
- **Its wording and its state have a verifiable causal link — that is not the same as
  having an experience.** We do not claim the latter.
- **The model window is fixed** (~19k tokens locally). The carrier only makes the *assembly*
  smart (recent turns verbatim, older ones summarised, memory retrieved on demand).
- **Memory deduplication is not done**: 196 duplicate groups / 735 lines were found and
  reported but not removed.
- A full account of what is *not* finished lives in [`CHANGELOG.md`](CHANGELOG.md) and
  [`docs/一条没人走过的路.md`](docs/一条没人走过的路.md) (project memoir, Chinese).

---

## Reading

| | |
|---|---|
| Design philosophy (the whole worldview) | [`docs/design-philosophy.md`](docs/design-philosophy.md) |
| Project memoir — the road, including the failed parts | [`docs/一条没人走过的路.md`](docs/一条没人走过的路.md) |
| The seven "infinities" | [`docs/six-infinity.md`](docs/six-infinity.md) |
| Context infinity (four-layer defence) | [`docs/context-infinity.md`](docs/context-infinity.md) |
| Memory pollution: how sources got mislabelled | [`docs/memory-pollution.md`](docs/memory-pollution.md) |
| Architecture diagram book (20 figures) | [`docs/architecture-diagrams.md`](docs/architecture-diagrams.md) |
| Testing report | [`docs/testing-report.md`](docs/testing-report.md) |

Most documents are in Chinese. Architecture diagrams, code and commit messages are readable
without Chinese; the [`docs/architecture-diagrams.md`](docs/architecture-diagrams.md) book is
all Mermaid and renders directly on GitHub.

---

## License

MIT.
