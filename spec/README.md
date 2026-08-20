# spec

What every implementation of Contexture has to reproduce, stated as files
rather than as prose.

Prose is not enough to keep three implementations saying the same sentence to
an agent: a port that quietly drops the recovery half of a failure message
still starts, still answers, and no test goes red. So the shared half is
captured as bytes.

```
golden/     the exact payload and the exact sentence the bundled demo produces
```

`golden/` is produced from `contexture.demo`, which is the reference
declaration — three roles, one of them a coordinator, six tools, two skills,
two documents and one command. It covers every branch an agent can reach:

| file | what it pins |
| --- | --- |
| `instructions.txt` | what a host reads before it calls anything |
| `tools.json` | the four entry points, their descriptions and their hints |
| `prompts.json` | the declared commands, plus `goto` |
| `resources.json` | the published addresses |
| `discover.json` | the roots, as cards |
| `open.json` | every node in the forest, opened |
| `refusals.json` | all five lookup failures and both wrong-door refusals |
| `commands.json` | what a person reads when they run a command |
| `reads.json` | what a host gets from a resource read |
| `completions.json` | what a person is offered while typing a ref |

Regenerate deliberately, and review the diff — these bytes are the contract:

```
.venv/bin/python tests/golden.py --update
```

Still to come, and named in the README: `fixtures/` (declarations stated
language-neutrally, so a Go or TypeScript port can build the same forest) and
`conformance.md` (the reference grammar, the cut rules, the door rules).
