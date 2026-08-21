"""One-creator's Goal domain as a lazy Contexture application."""

from contexture import Contexture, Resource

from .role import GoalDomain


class CurrentFocusDocument(Resource):
    def __init__(self) -> None:
        super().__init__(
            opens="goal/current-focus",
            uri="goal://focus",
            mime_type="application/json",
            description="The current main thread and not-doing list.",
        )


class GoalObjectShapes(Resource):
    def __init__(self) -> None:
        super().__init__(
            opens="goal/object-shapes",
            uri="goal://objects",
            mime_type="application/json",
            description="Validated field shapes for Area, Goal, and Focus.",
        )


app = Contexture(
    name="oc-goal",
    roots=(GoalDomain,),
    resources=(CurrentFocusDocument, GoalObjectShapes),
)


__all__ = [
    "CurrentFocusDocument",
    "GoalDomain",
    "GoalObjectShapes",
    "app",
]
