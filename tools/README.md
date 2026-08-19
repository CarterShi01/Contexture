# Tools

Development tools for working on this repository. Nothing here is imported by
the package, nothing here ships in the wheel, and nothing here is part of the
public API.

Each tool answers one question a developer has and the test suite does not:
*what does this actually say?* The tests assert the disclosure text. They cannot
show it to you.

| Tool | Question it answers |
|---|---|
| [`inspect_disclosure.py`](inspect_disclosure.py) | What does an agent receive at each step, and what does it cost? |
| [`../run_tests.py`](../run_tests.py) | Does the suite pass from a source checkout? |
| [`../scripts/verify_claude_code.md`](../scripts/verify_claude_code.md), [`../scripts/verify_codex.md`](../scripts/verify_codex.md) | Does a real host, driving a real model, reach the right answer? |

The three form a ladder. The suite says the text is what it was meant to be;
the inspector shows you the text and its cost; the host playbooks say a model
actually acted on it. Each step up costs more and proves more.

---

## `inspect_disclosure.py` — read what an agent receives

The inspector itself lives in the package, at `contexture.inspection`, and is
reachable as **`contexture inspect`** wherever the package is installed. This
file is only the checkout-local door to it, the way `run_tests.py` is for the
suite — because the person who most needs to read their own disclosure text is
whoever just wrote a Role against this framework, not a contributor to it.

```bash
# from a checkout — defaults to the bundled reference application
python tools/inspect_disclosure.py [refs...] [options]

# from anywhere the package is installed, inside your own project
contexture inspect [refs...] [options]
```

### What it does

It replays a session the way a host walks one, with no agent in the room:

```text
session start   the instructions field a host loads before calling anything
                ↓
discover        the roots contexture_discover answers with
                ↓
open <ref>      one contexture_open per ref you named, in order
                ↓
read <ref>      a resource's content, when you ask for it
```

For each step it prints **exactly what arrives** — the instructions verbatim,
the payload as JSON, or the refusal sentence a wrong ref produces — with what
it cost, and a running total.

### What it proves, and what it does not

It calls the same functions the server calls: `instructions.build`,
`ContextTree.skeleton`, `ContextTree.open`, `contract.unresolved`. The five
gateway functions in `contexture/server/projection.py` do nothing but forward
to those, so a payload printed here is the payload sent there, character for
character. `tests/test_inspection.py::HonestyTests` holds that claim by
comparing every step against what the real gateway answers through the SDK.

Two things it cannot see, both only visible from outside the process:

- whether the server starts at all under a host's launch command;
- whether anything but MCP messages reaches stdout.

Those are what `tests/test_stdio_server.py` pays a subprocess for.

Two things it will not do: `contexture_invoke` is never replayed, because
running a business tool is not disclosure and a debugging command should not
change anything; and `contexture_read` runs only under `--read`, because
reading a resource runs business code that may want credentials nobody
supplied.

### Options

| Option | Effect |
|---|---|
| *(refs)* | Open each ref, in the order given. A wrong one prints the sentence the agent would read, and does not stop the run. |
| `--all` | Open every node in the tree, breadth-first — how you read all of your own text at once. |
| `--read` | Also run each named resource's `read()`, and cost the document. |
| `--summary` | Costs and host limits only, without the payloads. Pairs with `--all`. |
| `--json` | Emit the whole trace as JSON. Diff one revision against the next. |
| `--no-discover` | Skip the `contexture_discover` step. |
| `--roster-budget CHARS` | Render the bootstrap roster against a different budget, to see where it gets cut. |
| `--target pkg.mod:RoleClass` | Which root to inspect. Defaults to the enclosing `[tool.contexture]` project, or to the bundled demo when run through `tools/`. |

Exit status is **1** if any ref was refused or any host limit was not met, so it
can gate a commit. The text is printed either way.

### The three checks at `session start`

The bootstrap instructions field fails in three ways, and every one of them
fails silently — nothing raises, the server starts, and the text is simply
wrong:

```text
ok  927 of 2048 bytes — Claude Code truncates what is over, mid-sentence
ok  contexture_open named in the first 512 characters — that is how far Codex
    reads while deciding whether to use this server
ok  roster lists 3 of 3 role(s)
```

The limits are `INSTRUCTIONS_LIMIT` and `SELF_CONTAINED_PREFIX` in
`contexture/server/instructions.py`, and each is measured in the unit the host
actually enforces: bytes for the truncation, characters for the prefix.

The third check is the one that needed a hand-built tree to see before this
existed — see the second run in
[`../docs/verification/hosts.md`](../docs/verification/hosts.md). Use
`--roster-budget` to reproduce a cut on purpose.

### The cost model

Every step reports characters, UTF-8 bytes, and an **estimated** token count.
The estimate is one token per wide character plus a quarter token per
everything else. It is not a tokenizer; it is enough to tell 300 tokens from
3,000. `chars / 4` is not used because it reports a declaration written in
Chinese at a quarter of its real cost.

Where a real limit exists, it is checked in bytes or characters — never in the
estimate.

### Worked example

```bash
python tools/inspect_disclosure.py --all --read --summary
```

On the bundled reference application, every node and every document:

```text
 #  call                 ref                                          ~tok
 0  session start        -                                             232
 1  contexture_discover  -                                              56
 2  contexture_open      kubernetes-platform                           225
 3  contexture_open      kubernetes-platform/incident-response         700
 4  contexture_open      …/incident-response/diagnose-crash-loop        302
 …
total  14466 characters, ~3618 tokens over 16 step(s)
```

The path an agent actually takes to a diagnosis — connect, open the platform,
open the specialism, open the skill, read the runbook — is about 1,860 of those
tokens. Nothing pays for `deployment-ops` unless the task goes there.

To see what a single node says, name it:

```bash
python tools/inspect_disclosure.py --no-discover \
  kubernetes-platform/incident-response/diagnose-crash-loop-backoff
```

To see what an agent reads when it guesses a ref:

```bash
python tools/inspect_disclosure.py kubernetes-platform/nope
```

```text
step 2  contexture_open  kubernetes-platform/nope  [refused]
  note: this sentence is all the agent gets; it recovers from it

  | Role 'kubernetes-platform' holds no member named 'nope'. It holds:
  | deployment-ops, incident-response. Call contexture_open on
  | 'kubernetes-platform' to see each member with the ref that opens it.
```
