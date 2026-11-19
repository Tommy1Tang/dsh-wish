# dsh-wish · Wish-Driven Development

### for [DeepSeek Harness](https://github.com/deepseek-ai)

[![tests](https://github.com/Tommy1Tang/dsh-wish/actions/workflows/tests.yml/badge.svg)](https://github.com/Tommy1Tang/dsh-wish/actions/workflows/tests.yml)
[![python](https://img.shields.io/badge/python-3.11%20%7C%203.12-blue)](#requirements)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> You say one sentence; in your head there is a picture.
> This chain does not "write your sentence down" — it forces that picture into a contract that has
> **exactly one reading** and **can be judged by a script**, *before* the first line of code.

One request in → decide how heavy the process should be → ask only what must be asked →
lock an acceptance contract → **if the contract does not pass, work does not start**.

> 中文版见 [README.md](README.md)

---

## What problem it solves

The most common AI coding failure is not "it cannot write code".
It is **"what got built is not what you meant — and you cannot prove it"**.

| Without it | With it |
| --- | --- |
| "I want an export feature" → you get a nightly job dropping CSVs on the server, but you wanted a button that downloads an Excel file | Contract says: click『Export』→ the browser downloads `todo_20260101.xlsx` → its row count equals the list length |
| "Everything is done" — you can only believe it or not | `wish_lint` must exit 0; every item can be recomputed |
| Work starts before thinking is done; by rework time 2000 lines exist | Both checkpoints land **before** any code is written |
| Every request is dragged through the same heavy process — even a typo fix needs 19 documents | Three tiers: a typo goes straight through, building a system takes the full chain |

---

## Quick start

### Requirements

- DeepSeek Harness `0.2.x`
- Node.js ≥ 18 (plugin host half)
- Python ≥ 3.10 (the decision core; **the Python 3.12 bundled with dsh works as-is**)
- No third-party Python packages

### Install as a dsh plugin (recommended)

```bash
git clone https://github.com/Tommy1Tang/dsh-wish.git
```

Add two things to your profile's `package.json`:

```jsonc
{
  "dependencies": { "dsh-wish": "link:/path/to/dsh-wish" },
  "dsh": { "profile": { "bundles": [ /* ... */, "dsh-wish" ] } }
}
```

```bash
cd ~/.dsh/profiles/<your-profile> && pnpm install
# restart dsh — new bundles are not hot-loaded
```

The model then gains four tools:

| Tool | What it does |
| --- | --- |
| `wish_route` | Tier (L0/L1/L2) + work type + review points + risks + what to ask |
| `wish_focus` | Generates the questions for that tier into `wish/<slug>/answers.md` |
| `wish_contract` | Fills the answers in → writes `contract.md` → runs the lint |
| `wish_lint` | Checks a single contract |

### Or use it as a plain skill

For other harnesses (Claude Code / Codex / Qoder), or if you do not want the plugin:

```bash
# Windows (junction — single source, no copy)
cmd /c mklink /J "%USERPROFILE%\.dsh\skills\dsh-wish" "D:\path\to\dsh-wish"
# macOS / Linux
ln -s /path/to/dsh-wish ~/.dsh/skills/dsh-wish
```

Both forms share the same Python core — **the plugin is only a shell; not one decision rule was copied**.

### Or pure command line

```bash
python router.py "a work order system with separate frontend and backend"   # decide the tier
python focus.py  "a work order system with separate frontend and backend"   # generate questions
python focus.py  --complete wish/<slug>                                     # build contract + lint
python contract_lint.py contract.md                                         # check one contract
```

---

## What one full run looks like

```text
$ python router.py "sync inventory with our supplier system every day"

Tier : L2 (enterprise)   Type: integration
Why  : two or more enterprise signals: INTEGRATION + EXTERNAL_BOUNDARY
Est. : 2–6 hours         Review points: 4

Questions to answer (each pre-filled with a recommendation):
  Q1. Does the counterparty have an interface spec?
  Q2. Who will run the joint debugging?
```

Then:

```bash
$ python focus.py --complete wish/sync-inventory-with-xxx
Contract check: FAIL
AC count: 1
  [E1] AC-01: missing `> counterexample:`. If you cannot name one, the AC is not pinned down
  [E4] AC-01: no observable object at all (number / file name / quoted name / UI element)
```

Fill it in and re-run until `PASS`. **No code before that.**

---

## Three tiers

| Tier | When | Flow | Review points | Time |
| --- | --- | --- | --- | --- |
| **L0** direct | typo, explaining code, reading logs, translation | skips the delivery chain | 0 | minutes |
| **L1** standard | add a feature, fix a bug, change a formula | focus → contract → fake deliverable → role chain → gates | 2 | 15–40 min |
| **L2** enterprise | build a system, cross-system integration, compliance, business modelling | modelling → review → models → review → everything in L1 | 4 | 2–6 h |

**Tiering looks at uncertainty and blast radius, not effort.** Effort only affects the time estimate.

A **work type** is decided at the same time (it decides who works and what gets verified):

| Type | Shape | Example trigger |
| --- | --- | --- |
| `fix` | reproduce → locate → fix → regress | bug / error / not working |
| `refactor` | **read the current state → impact list → baseline → compatibility → small steps → rollback** | legacy rewrite / stack migration / microservice split |
| `data` | dry-run → backup → execute → human confirm | migration / data correction |
| `integration` | counterparty spec → signed mapping list → adapter → joint debugging | third-party sync |
| `report` | definition → data source → build → reconcile | report / reconciliation |
| `frontend` | UI design → build → browser E2E | page / styling / component |
| `backend` | freeze contract → build → unit/integration | API / calculation / scheduled job |
| `fullstack` | freeze contract → parallel → E2E | front and back end together |
| `ops` | skips development, goes to deploy-only | deploy / restart |
| `generic` | generic chain | type not recognised |

> **"A bug on the frontend page" is `fix`, not `frontend`** — fixing a bug and writing a page are different procedures.
>
> **Changing an existing system is `refactor`, not `fullstack`** — its first step is not design, it is
> **reading what is already there**: run `detect_stack.py`, build a code index, write an impact list,
> and only then touch the first line. It also skips the business-modelling block — turning JSP into Vue
> does not need a BPMN diagram.

There is also an independent **urgency** flag: when it matches "line is down / ASAP / production is on fire",
it prepends `stop the bleeding → record it → complete the process within 48 hours`.
Fighting a fire skips the full process, but **never skips the record**.

---

## What a contract looks like

```markdown
## Acceptance items (each must have exactly one reading)

### AC-01
- **How to verify**: on the todo list page click『Export』, the browser downloads `todo.xlsx`,
  the first row is the header "ID/Title/Status", and the row count equals the current list length
> Counterexample: only qty × unit price is displayed, nothing is really recomputed —
  the numbers happen to match, the logic was never changed

### AC-02
- **How to verify**: While an order is in "pending payment", the system holds the stock and the cancel button is clickable
> Counterexample: the button is visible but clicking it errors — looks cancellable, is not

### Out of scope
- permission matrix / notifications / mobile

## State enumeration
| State | Meaning |
| --- | --- |
| pending payment | ordered, not paid |
| cancelled | cancelled by user or system |

## When a wish may be dropped
| Code | Meaning | Signer |
| --- | --- | --- |
| `not-reproducible` | cannot reproduce | requester |
| `obsolete` | requirement dropped | business owner |
| `already-exists` | already covered | requester |
| `out-of-scope` | not our scope | project owner |
```

### What gets checked (10 rules; the exit code is the verdict)

| Rule | Check |
| --- | --- |
| E1 | every AC must carry a `> counterexample:` |
| E2 | every AC must have a way to verify it |
| E3 | no vague words (friendly / reasonable / as much as possible / fast / appropriate …) |
| E4 | every AC needs at least one observable object (number / file name / quoted name / UI element) |
| E5 | a "when may this be dropped" section must exist |
| E6 | that section must use the fixed reason codes and name a signer |
| E7 | state/exception ACs must start with an EARS pattern (When / While / If / Where) |
| E8 | every state in the enumeration must be covered by some AC |
| S1 | "out of scope" must not be empty |
| S2 | AC numbering must be continuous |

Runnable examples: [`examples/contract-good.md`](examples/contract-good.md) (passes) and
[`examples/contract-bad.md`](examples/contract-bad.md) (fails 9 rules).
They are checked in CI, so they cannot drift away from the rules.

---

## FAQ

**Q: Does it write code for me?**

No. It makes the requirement precise and pins the acceptance down. The code is written by the
dsh model or whatever executor you point at it. Installing it does not mean "automatic development";
it means "no more developing in a fog".

**Q: Won't it be slow and annoying?**

Typo fixes, code explanations and log reading are classified **L0 — zero questions asked**.
Only L1 asks up to 3 questions, each with a recommended answer, so **answering "yes" is enough**.

**Q: What if it decides the wrong tier?**

1. The rules are deterministic (no model involved), so identical input always yields identical
   output and you can trace *which signal* decided it;
2. When an answer introduces new information it **re-tiers itself** and tells you why;
3. If you still disagree, edit the rule tables at the top of `router.py` and run
   `python tests/test_router.py` — the test that goes red is the behaviour you changed.

**Q: Can I use it without `agent-delivery-gate` / `research-to-project-input`?**

**Yes.** Both executors ship inside `vendor/`, so a clone is already the complete version.
If you have newer copies installed, `deps.py` can also be pointed at them via environment variables.

**Q: Does it send my requirements anywhere?**

No. Tiering and contract checking are pure local Python — **no network, no model calls**
(models only participate while asking the focus questions).

**Q: Does it support Claude Code / Codex / Qoder?**

Yes, but only in skill form (`SKILL.md`). The plugin form is dsh-specific.

**Q: Why "wish-driven" and not "wishful"?**

`wishful thinking` means self-deception — that is the disease this project treats, not its name.

---

## Verifying the plugin is actually live

Do not trust "the tool list looks new". **Read the session log** — that is what was really sent to the model:

```bash
node -e "
const fs=require('fs'), zlib=require('zlib');
const buf=fs.readFileSync(process.argv[1]);
const magic=Buffer.from([0x28,0xB5,0x2F,0xFD]);
let pos=0, cuts=[]; while(true){const i=buf.indexOf(magic,pos); if(i<0)break; cuts.push(i); pos=i+1;}
let out=''; for(let k=0;k<cuts.length;k++){const s=cuts[k],e=k+1<cuts.length?cuts[k+1]:buf.length;
  try{out+=zlib.zstdDecompressSync(buf.subarray(s,e)).toString('utf8')}catch{}}
console.log('prompt section present:', out.includes('【许愿式编程】'));
console.log('tool description present:', out.includes('下一步：L0 直接做'));
" ~/.dsh/sessions/<your-session-dir>/session.v4.jsonl.zstd
```

Both `true` = plugin, tool descriptions and the system-prompt section all reached the model context.

---

## Project layout

```text
dsh-wish/
├── lib/index.js          plugin host half: registers 4 tools, shells out to Python
├── router.py             tiering core (3 dimensions + 3 criteria)
├── focus.py              focus: questions → answers → contract
├── contract_lint.py      10 contract rules; the exit code is the verdict
├── deps.py               executor discovery and graceful degradation
├── refs.py               external reference checks
├── templates/            contract template
├── examples/             one passing and one failing contract (checked in CI)
├── vendor/               the two executors shipped with the package (see THIRD_PARTY_NOTICES.md)
├── tools/sync_vendor.py  vendor sync + provenance
└── tests/ + test/        185 tests
```

---

## Further reading

- [PLAN.md](PLAN.md) — why it is designed this way, where the criteria came from, **and what it does not solve**
  (read this first if you are evaluating reliability)
- [SKILL.md](SKILL.md) — operating instructions for the skill form
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) — licences and attribution for the two vendored executors
- [README.md](README.md) — 中文版

## License

[MIT](LICENSE). The two executors under `vendor/` keep their own licences — see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
