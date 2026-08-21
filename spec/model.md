# Contexture public model

This is the language-neutral contract for a Contexture application. Python,
TypeScript, Go, and PHP bindings may use different declaration syntax; they
must preserve these meanings.

## Application

An Application has a non-empty name, at least one root, optionally one shared
Channels handle, and optional Prompt and Resource declarations. It is a lazy
specification: importing or constructing it creates no node, connection,
Index, Disclosure, or server.

Each build creates a fresh forest, registers roots, derives bindings, validates
the complete forest, and produces an immutable Index.

## Nodes

| Node | Required facts | Meaning |
| --- | --- | --- |
| Role | name, description, instructions | A responsibility boundary holding child Roles, Skills, and Tools. |
| Skill | name, description, instructions, optional uses refs | A procedure the model follows; the framework does not execute it. |
| Tool | name, description, read_only, typed input and invoke body | A deterministic capability the framework executes. |

Containment is a forest. Every node has one address. A Skill may reference an
existing address through `uses`; references do not create containment or depth.

## Integration declarations

Channels owns application-wide external dependencies and an optional open/close
lifecycle. Prompt and Resource are not nodes: each names an existing node by
ref and creates a second entry point on its respective MCP primitive.

## Required behavior

- Node identity is explicit; names and descriptions are never inferred from
  class names or docstrings.
- Tool input schemas and Tool invocation validation come from one binding.
- A read-only Tool and a writing Tool use distinct gateway doors.
- The served surface cannot change after Index compilation.
- A Skill is opened; a Tool is invoked.
- Disclosure is progressive: opening a Role exposes one containment level.
