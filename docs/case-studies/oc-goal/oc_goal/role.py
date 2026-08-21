"""The Goal responsibility boundary exposed through Contexture."""

from contexture import Role

from .skills import ReviewAttention
from .tools import (
    DescribeGoalObjects,
    GetArea,
    GetGoal,
    ListAreas,
    ListGoals,
    ReadCurrentFocus,
    UpdateFocus,
    UpdateGoalContext,
    UpsertArea,
    UpsertGoal,
)


class GoalDomain(Role):
    def __init__(self) -> None:
        super().__init__(
            name="goal",
            description=(
                "Declare attention through enduring areas, finite goals, and "
                "one current focus."
            ),
            instructions="""\
Treat stored declarations as the structured authority. Read before changing,
and pass the revision you read when updating an Area or Goal.

An Area never ends: it owns an attention budget and a maintenance standard. A
Goal ends: it owns a horizon and success criteria, and belongs to exactly one
active Area. Do not collapse the two shapes.

Budget and status are human-owned judgement fields. No tool here accepts them;
a new Area is always paused with budget 0. To evaluate the allocation, open
`review-attention`, gather its evidence, and make the judgement outside tools.
""",
            skills=[ReviewAttention()],
            tools=[
                ListAreas(),
                ListGoals(),
                GetArea(),
                GetGoal(),
                UpsertArea(),
                UpsertGoal(),
                UpdateGoalContext(),
                UpdateFocus(),
                ReadCurrentFocus(),
                DescribeGoalObjects(),
            ],
        )


__all__ = ["GoalDomain"]
