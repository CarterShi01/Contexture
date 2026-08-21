"""Model-executed methods of the Goal role."""

from contexture import Skill


class ReviewAttention(Skill):
    def __init__(self) -> None:
        super().__init__(
            name="review-attention",
            description=(
                "Review horizons, unsupported goals, idle quota, and placeholder "
                "criteria without changing declarations."
            ),
            instructions="""\
Assemble evidence first, then make the judgement yourself.

1. Call `list-areas`; active budgets must total 100.
2. Call `list-goals` and group the goals by area.
3. Identify:
   - expired horizons that require a decision;
   - goals in areas with little or no budget;
   - active areas with budget but no goals;
   - success criteria that still contain TODO placeholders.
4. Report the evidence and the smallest decision the founder must make.

Do not change budget or status. Those are human judgements and no tool in this
role accepts them.
""",
            uses=("goal/list-areas", "goal/list-goals"),
        )


__all__ = ["ReviewAttention"]
