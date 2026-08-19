"""Methods the model performs, using the tools this role holds.

One skill, and it is here because of what it was in one-creator: a `@compile`
operation whose body raised `NotImplementedError` and whose status was
`"planned"`. Its own docstring said

    Material only, never a conclusion: the join is deterministic and happens on
    the server, the judgement is the model's job.

A capability whose judgement is the model's job is not a Tool — Tool is the
node the framework executes. Declaring it as a Skill is not a workaround for it
being unimplemented; it is what it always was. It stops being a permanently
planned tool and becomes a procedure that works today, because the tools it
needs already exist.
"""
from __future__ import annotations

from contexture import Skill


class ReviewTheAttentionChain(Skill):
    """Review how attention is allocated: expired horizons, unsupported goals, misallocated quota."""

    instructions = """\
Assemble the material first, then judge it. Nothing below is computed for you.

1. Call `list-areas`. Note `active_budget_sum`: the budgets of active areas are
   required to total 100, so anything else means the allocation is mid-edit and
   every share below is provisional.
2. Call `list-goals`. Group them by `area`.
3. Look for four things, and say which of them you found:
   - **Expired horizons.** A goal's `horizon` is a forced review date, not a
     deadline. One in the past means the goal is owed a decision, not that it
     failed.
   - **Unsupported goals.** An area carrying goals but little or no budget is
     claiming work it has not funded.
   - **Idle quota.** An active area with budget and no goals is funded
     attention nobody is spending.
   - **Placeholder criteria.** A `success` entry still reading TODO means the
     goal cannot be judged done, whatever happens.
4. Report what you found and what you would ask the founder to decide. Do not
   change anything: `budget` and `status` are founder judgements, and no tool
   here can set them.
"""


__all__ = ["ReviewTheAttentionChain"]
