---
name: korium-memory
description: How to save something to Korium so it is worth finding later, and how to find what is already there. Read this before starting substantial work on a feature, and again before finishing it. Triggers on the specific multi-word phrases "save this to korium", "search korium", "what do we know about", "korium memory", "capture this decision", and "write this down for next time". NOT triggered by bare "save" or bare "remember" - those words alone must never activate this skill.
---

# Korium memory

Korium holds what your team decided and why. Two tools do almost all the work: one
searches, one saves. Their full names depend on how the connection was added, so
they are named here by their endings, `agent_search` and `agent_capture`.

Reading and writing work together. Save what the next task needs, then search
before making the next decision. An empty result does not prove that nobody
wrote the memory: check the workspace, scope, query and processing state.

## Searching

Ask a focused question. Search combines words and meaning and returns ranked
source memories with retrieval information. The assistant explains the result
and cites those sources. Do not promise an automatic count, a resolved identity
or a complete answer merely because a list of memories came back.

Check `entities_partial` when present: true means the related-entity context
could not be fetched, and the memories themselves may still be useful. A search
either answers with a whole page or returns an error, so there is no
partial-result flag to read. Do not turn an empty list into "there is none".

A receipt proves a save, not that its ID stays current after processing. A new
duplicate can be folded into an existing record and marked inactive. Inspect
history and any replacement before retrying the capture; if the response hides
the invalidation reason or surviving record, report that limit rather than
guessing why it happened.

| Argument | What to pass |
|---|---|
| `query` | The question, in words. "why did we drop the second queue" works better than "queue". |
| `scope` | Optional. A pattern: `*` for everything, `billing` for that exact area, `billing.*` for everything under it. |
| `limit` | Optional. 10 by default, 50 at most. |

Two focused questions beat one broad one. Search for the feature, then for the
files or the area you are about to touch. A single lazy lookup that finds nothing
is how people conclude the memory is empty when it is not.

Reading does not consume the ordinary monthly capture allowance. Account access,
rate limits and service availability still apply; use focused queries rather
than an unbounded retry loop.

## Saving

Five fields are required.

| Field | Rule |
|---|---|
| `content` | Non-empty memory content. Respect the live service's payload limit and any size refusal. |
| `thought_type` | One of the eleven below. Nothing else is accepted. |
| `source_agent` | The agent recording it. Use its real working name, not the human who approved the decision. |
| `source_phase` | What kind of work this was: `research`, `build`, `review`. Same shape. |
| `importance` | 0 to 1. |

Worth sending when you have it: `scope`. Korium also stores `confidence` (0 to
1), `evidence` and `alternatives_rejected` (lists), `decided_by` and `metadata`
(objects), `trigger_event` (text) and `relations`, and `korium_reconstruct`
returns them under `capture`. A wrong shape, a NUL character or the same link
twice refuses the whole save. Search reads `content`, so put the source, the
evidence and how sure you are there too.

Each entry in `relations` is a `target_id`, a `relation_type` (`supersedes`,
`triggered_by`, `evolves_from`, `contradicts`, `supports` or
`synthesized_from`) and an optional `context`. The target must be a memory in
this account; one saved moments ago counts. If Korium finds a target is not
there, nothing is saved and the error names the ID. The link is usually written
a few seconds after the save, when the memory is filed, but it can still fail
then: `capture.relations` from `korium_reconstruct` says whether each one was
written. The `context` stays in that record, not on the link.

### Use your own name

`source_agent` answers which agent recorded this. It does not establish who
decided it. Name the decision-maker and source in the content, and use the
client's supported attribution fields when available. Never turn an inference
into a human approval. `source_phase` describes the work, not the author.

### The eleven types and the current expiry defaults

These are the repository's seeded defaults, not a guarantee of the settings on
every deployed service. Check the applicable release and workspace policy before
depending on a retention period. Expiry, replacement and ranking are different.

| Type | Use it for | Default importance | Default age-based expiry |
|---|---|---|---|
| decision | A choice made, and why | 0.80 | No TTL |
| reflection | A view formed over a whole piece of work | 0.75 | No TTL |
| preference | How someone wants things done | 0.70 | No TTL |
| handoff | What the next person needs to pick this up | 0.60 | No TTL |
| seed | Background that has to be there from the start | 0.50 | No TTL |
| lesson | Something learned the hard way | 0.70 | 365 days |
| pattern | A shape that keeps recurring | 0.70 | 365 days |
| insight | A realisation worth keeping | 0.70 | 180 days |
| rejection | What you decided against, and why | 0.60 | 180 days |
| correction | A fix to something previously believed | 0.60 | 90 days |
| drift | A gap between what is written and what happens | 0.40 | 90 days |

The scheduled expiry job can mark an old memory no longer current. That removes
it from ordinary current-memory results; it does not delete the stored record
or establish that the statement is false. A type with no TTL can still be
superseded explicitly. Account deletion and contractual retention are separate.

Use affects ranking, not this expiry clock. Do not change a memory's type just to
avoid expiry. For an audit, browse history and inspect invalidation/replacement
information rather than assuming ordinary search includes every old record.

`rejection` is the most useful and the least used. Writing down what you decided
against is what stops the same bad idea coming back wearing a new hat.

### scope

When saving, `scope` is a list of exact dotted paths: letters, digits, `_` or `-`,
joined by dots. `billing.ledger` works. `billing/ledger` does not, and neither
does anything with a space or an accent. A bad scope means nothing is saved and
you get told which rule you broke.

When searching, `scope` is a pattern, so `billing.*` reaches everything below it.

## What to write

Write what a future session could not work out on its own from the code, the
history, or the ticket:

- a decision, and why the other options lost
- something that cost real effort to find out
- a correction to something the team believed
- a preference somebody stated
- a limit discovered the hard way

Give each memory one useful subject, with enough detail to explain the reason,
source, alternatives and what remains uncertain. There is no 500-character
writing target. Stay within the live tool's content limit; do not cut away the
evidence just to make the entry short.

Write it in your own words, as a summary. Never paste in raw file contents, user
data, credentials, or anything a customer wrote.

If nothing durable happened, capture that and say why. The stop gates refuse a
finish with no capture.

## Changing your mind

When a new memory replaces an old one, link them with the `supersedes` relation
rather than writing the new one on its own. That is how the record shows what the
team used to think and when it changed, instead of two memories that disagree
with no way to tell which is current.

Either put `{"target_id": "<old ID>", "relation_type": "supersedes"}` in the
correction's `relations`, or capture the correction, check its ID, then call
`korium_relation` with the new ID as `source_id`, the old ID as `target_id` and
`supersedes` as the type. Then trace both IDs, or read `capture.relations`. A capture receipt alone does not
prove the replacement link exists or that extraction has learned from it.

## Refusals are not errors

When a save is refused because a plan limit is reached, it comes back as a
successful response carrying a `rejected` status and a reason, not as an error.

If you are counting saves, count only the responses that carry a memory id.
Treating "the tool ran" as success means a session that was refused on every save
finishes believing it saved everything.

Searching does not pass through that limit, so finding things keeps working when
saving is paused.

## What not to do

- Do not save at the end of a session only. The decision you can still explain is
  the one you made an hour ago, not the one from this morning.
- Do not paste a document in and call it a memory. Split it into the claims it
  makes and link those.
- Do not give everything importance 0.5. It is the same as giving nothing an
  importance.
- Do not write a memory that only makes sense if you were there. Name the thing,
  not "it".
