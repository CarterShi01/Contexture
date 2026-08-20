"""Declare Goal-domain objects stored by an injected center repository.

The domain owns field semantics while the composition root supplies custody.
"""
from ..citizens import (
    Citizen,
    Document,
    InjectedDocumentStore,
    InjectedStore,
    context_config_field,
    default_context_config,
    derived,
    field,
    founder_only,
    invariant,
    item,
    nonempty,
    server_managed,
    truncate,
)

_SLUG_PATTERN = r"^[a-z0-9](?:[a-z0-9._-]{0,30}[a-z0-9])?$"


class Area(Citizen, store=InjectedStore("area", key="slug"),
            key="slug", key_field=field(pattern=_SLUG_PATTERN)):
    """An attention area that never ends: holds a quota (budget) and a maintenance
    standard, never an end date.

    An area is not a goal. Areas never end and hold budget and standard; goals have
    an end and hold horizon and success, each required to name the `area` it serves.
    One entry carrying both meant "entrepreneurship expires in 2026-Q4" — a
    distorted data model, which no presentation layer can fix.
    """

    # This is the only source of the constraints; the hand-written schema is gone,
    #   and `selftest_goal_reflect::_schema_coverage` holds coverage by construction.
    title: str = truncate(30, minlen=1)
    why: str = nonempty(minlen=10, maxlen=500)
    budget: int = founder_only(0, minimum=0, maximum=100)
    standard: str = field("TODO(创始人):这个域什么算健康", minlen=5, maxlen=300)
    status: str = founder_only("paused", choices=("active", "paused", "archived"))
    objects: list[str] = nonempty(["Note"], maxitems=12,
                                  item=item(pattern=r"^[A-Z][A-Za-z]{1,30}$"))
    owner_ref: str = server_managed("principal://founder", pattern=r"^principal://[a-z][a-z0-9-]*$")
    revision: int = server_managed(1, minimum=1)
    created_at: str = server_managed()
    updated_at: str = server_managed()

    @derived
    def goals(self):
        """Goals under this area: a back-reference, not stored, so it cannot drift."""
        return [g for g in Goal.all() if getattr(g.area, "key", None) == self.key]

    @invariant(scope="all")
    def active_budgets_sum_to_100(areas):
        """The budgets of active areas must sum to 100. A global invariant."""
        total = sum(a.budget or 0 for a in areas if a.status == "active")
        assert total == 100, "active 领域 budget 合计 %s ≠ 100" % total


class Goal(Citizen, store=InjectedStore("goal", key="slug"),
            key="slug", key_field=field(pattern=_SLUG_PATTERN)):
    """A goal with an end: holds a horizon (a forced review at expiry) and success
    criteria.

    Each requires a single-valued `area` naming the area it serves. A goal with no
    owner counts toward no area's share and is effectively invisible.
    """

    # As with Area, this is the only source of the constraints. `area` is stronger
    #   than a slug-shape check: it is a live reference to the active areas, whose
    #   closed set goes straight into the MCP schema's enum.
    area: Area = field(ref_where={"status": "active"})
    title: str = truncate(30, minlen=1)
    why: str = nonempty(minlen=10, maxlen=500)
    horizon: str = field("2099-Q4", pattern=r"^(\d{4}-Q[1-4]|\d{4}-\d{2}-\d{2})$")
    success: list[str] = nonempty(["TODO(创始人):这个目标怎样算成功"],
                                  item=item(minlen=5, maxlen=200))
    status: str = founder_only("active", choices=("active", "done", "dropped"))
    context: dict = context_config_field(
        factory=lambda: default_context_config(memory_scopes=("project",),
                                               inheritance=("project",)))
    owner_ref: str = server_managed("principal://founder", pattern=r"^principal://[a-z][a-z0-9-]*$")
    revision: int = server_managed(1, minimum=1)
    created_at: str = server_managed()
    updated_at: str = server_managed()

    @invariant
    def context_is_valid(self):
        """Reject configurations that pass shape checks but violate host policy."""
        from ..citizens import ContextConfig, ContextContractError
        try:
            ContextConfig.from_mapping(self.context, host_kind="goal")
        except ContextContractError as error:
            assert False, str(error)

class Focus(Document, store=InjectedDocumentStore("focus")):
    """The current main thread and not-doing list: the founder's attention declaration,
    founder-only.

    A `Document`, not a `Citizen`, on the criterion of whether "which Focus?" is a
    meaningful question. It is not: one instance, no primary key.

    `focus.yaml` is hand-written declaration data of the same family as
    `goals.yaml` / `areas.yaml`. The prose that used to head that file lives here
    instead, because `YamlDoc.patch` rewrites the whole file with `safe_dump` and
    eats comments — a singleton document has no entry boundary for text surgery to
    cut on, so those header comments disappear the first time `focus_update` runs.
    Moving the knowledge next to the class keeps it rather than losing it silently.
    """

    main_thread: str = nonempty(maxlen=200)
    week_top: list[str] = field(factory=list, item=item(minlen=1, maxlen=200))
    not_doing: list[str] = field(factory=list, item=item(minlen=1, maxlen=200))

    @classmethod
    def scheme(cls):
        # The class is Focus but the domain is goal; the default is the lowercased
        # class name, so it must be overridden here
        return "goal"
