# 英文发布帖（Reddit r/LocalLLaMA / Hacker News Show HN）

> 用法：整篇复制。Reddit 用「Title + 正文」；HN 只需把 Title 里的 `Show HN:` 留下、正文当第一条评论。

---

## Title（选一个）

1. `I gave a 4B local model a body — capability lives in the carrier, not the model`
2. `Show HN: XiaoJiao – carrier-first local AI assistant; swapping the model changes nothing`
3. `Static state injection failed 4 ways on a 4B. What worked was changing its situation in code`

---

## 正文

I've been building a local AI assistant around a 4B model for a few months. Recently I stopped trying to make the *model* better and made a different bet:

**Put capability in the framework, keep the model as a replaceable part.**

Memory, persona, tools, safety boundaries, state — all of it lives in the code *around* the model. Plug in a 4B, a 70B, a cloud endpoint or any OpenAI-compatible API, and it's still the same assistant. Swapping the model is a config change, not a rebuild.

The reason I went this way is a negative result that I think is the most useful thing I have to share.

---

### The negative result: state injection into a 4B doesn't work

The obvious move is to compute state (energy, mood, situation) and tell the model about it in the system prompt. I built that.

**It failed in all four attempts** — three different injection points, plus a prefill variant. The failure mode was identical every time:

> The 4B treats a *fixed* self-description as **background material**, not as **its own current state**. Ask it "what are you doing right now?" and it still answers "I am reading your memory."

This is not a prompt-engineering problem. I rewrote it several ways; same result. A static self-description is inherently ignorable.

### What worked: change its *situation*, not its prompt

Instead of telling it about state, the carrier **changes the world it has in hand** for that turn:

- **energy low → the tool table is literally shorter.** Exploration tools are removed from this turn's tool list. Not "sorted lower", not "the prompt suggests not using them" — removed.
- context budget is compressed instead of trimmed by the model
- proactive behaviour (browsing the web on its own) is cancelled in code, without asking the model

And the acceptance criterion is checkable, which is the part I care about:

> **One identical sentence. At energy 0.95 the tool table is long and keeps the exploration tools; at energy 0.10 the tool table is genuinely shorter — 6 → 0.**
> The test never reads a single word the model wrote. It only looks at the tool table, the policy level and the switches.

The state changes are then recorded as **causes** and fed into the *next* turn's policy:

```
[input trimmed] because energy is low / level=mid → exploration tools removed from this turn (6→0)
```

So being trimmed repeatedly raises the trimming level for subsequent turns. It decays, and it's resettable — it's not a permanent suppression.

### The half that's softer, and I keep it labelled as softer

There's a second mechanism: instead of a static self-description, the carrier **generates a fresh first-person present-tense self-narration every turn** from live state ("I'm out browsing right now, just saw X"). That one works — at the *wording* level. It stopped answering "I'm waiting for your instruction" and started saying specific things.

I do **not** claim that means it has subjective experience. The carrier can observe energy readings, tool-table lengths and suspend actions. It cannot observe experience, and I don't pretend otherwise. Those two things being conflated is exactly how a project like this turns into self-deception.

### Other things it does

- **Conversation memory outside the model** — retrieved on demand, so the context window doesn't grow with conversation length (4-layer defence: calibrated limit, zero-dependency token estimate, window + hard truncation keeping system and current turn, then summarisation of older turns)
- **70+ tools**, carrier decides the subset per turn
- **Its own sleep cycle** — it writes `sleep: yes/no` itself; the carrier only reads that one field and executes. (The previous version scanned its words for keywords, which was exactly backwards: "I'm tired but I can keep going" triggered sleep, "I want to rest a bit" didn't.)
- **A doctor for the model**: 18 symptom classes → 4-level diagnosis → 4-level treatment → records → prevention
- **Deleting files is hard-blocked at the carrier layer**, independent of permission settings
- Local video / podcast / music / diagram generation (ComfyUI etc., swapped in on demand)

### Numbers (default config, this machine)

- Feature gap suite: **60 / 60**
- Acceptance suite: **59 / 59**
- Stress suite: **248 / 249 · 100%** (0 failures, 1 data-side skip)
- Integration scenes: **19 / 19**
- Perception layer, 8 sentences: **7 / 8**, the two critical ones both judged "tense"
- State → tool table: same sentence, energy 0.95 vs 0.10 → **6 → 0**
- Docs gates: **150 Mermaid diagrams, 0 problems**

### What does NOT work yet (kept visible on purpose)

- **Metacognition is not solved.** Routing seven categories through a perception→heart→brain chain made it talk about sources, but it still confuses them: it can answer "how did you know that?" correctly once, then get "did you compute that yourself?" wrong, and it will still mis-transcribe `10000000000` as `100000000`.
- **The model window is fixed** (~19k tokens locally). The carrier only makes the *assembly* smart, it does not make the window infinite.
- **Its wording has a verifiable causal link to its state — that is not the same as having an experience.** I don't claim the latter.
- Memory deduplication isn't done: I found 196 duplicate groups (735 lines) and reported them rather than silently removing them.

### Links

- Repo: https://github.com/jiangchuangege/xiaojiao-harness
- Architecture diagram book (all Mermaid, renders on GitHub): `docs/architecture-diagrams.md`
- The failed-injection writeup and the whole road, including dead ends: `docs/一条没人走过的路.md` (Chinese; English README at the repo root)
- English README: `README.en.md`

Most docs are Chinese, but the diagrams, code and commit messages are readable without it.

**I'd especially like feedback on the negative result** — if you've tried to get a small model to internalise state, did you hit the same wall, and did you get past it? And if the "swap the model, keep the assistant" framing is wrong somewhere, I'd rather hear it now.
