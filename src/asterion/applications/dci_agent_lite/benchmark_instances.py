"""Immutable exact benchmark instance catalog for the DCI product."""

from __future__ import annotations

import re
from dataclasses import dataclass

from asterion.benchmarks.model import ApplicationRef
from asterion.capability_packages import BenchmarkSuiteRef


_SELECTOR = re.compile(
    r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*@"
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$"
)
_IMPLEMENTATION_STATES = frozenset({"implemented", "planned"})
_EXECUTOR_PROFILES = frozenset({"local-fixture", "real-agent-judge"})
_COST_CLASSES = frozenset({"provider-free", "agent-judge-bounded"})
_ALL_TASKS = (
    "bcplus.level3",
    "bcplus.main",
    "beir.arguana",
    "beir.scifact",
    "bright.biology",
    "bright.earth-science",
    "bright.economics",
    "bright.robotics",
    "qa.2wikimultihopqa",
    "qa.bamboogle.github-sample50",
    "qa.bamboogle.paper-full125",
    "qa.hotpotqa",
    "qa.musique",
    "qa.nq",
    "qa.triviaqa",
)


class DciBenchmarkInstanceError(ValueError):
    """Raised when an exact DCI benchmark instance cannot be selected."""


@dataclass(frozen=True, slots=True)
class DciBenchmarkInstance:
    """One public exact product selection over generic benchmark contracts."""

    instance_id: str
    version: str
    application_ref: ApplicationRef
    suite_ref: BenchmarkSuiteRef
    task_ids: tuple[str, ...]
    executor_profile: str
    default_case_limit: int
    all_case_count: int | None
    cost_class: str
    implementation_state: str

    def __post_init__(self) -> None:
        task_ids = tuple(self.task_ids)
        if (
            _SELECTOR.fullmatch(self.selector) is None
            or not isinstance(self.application_ref, ApplicationRef)
            or not isinstance(self.suite_ref, BenchmarkSuiteRef)
            or not task_ids
            or not all(type(task_id) is str and task_id for task_id in task_ids)
            or len(set(task_ids)) != len(task_ids)
            or self.executor_profile not in _EXECUTOR_PROFILES
            or type(self.default_case_limit) is not int
            or self.default_case_limit < 1
            or (
                self.all_case_count is not None
                and (
                    type(self.all_case_count) is not int
                    or self.all_case_count < self.default_case_limit
                )
            )
            or self.cost_class not in _COST_CLASSES
            or self.implementation_state not in _IMPLEMENTATION_STATES
        ):
            raise DciBenchmarkInstanceError("DCI benchmark instance is invalid")
        object.__setattr__(self, "task_ids", task_ids)

    @property
    def selector(self) -> str:
        return f"{self.instance_id}@{self.version}"


def _real_instance(
    task_id: str,
    *,
    implemented: bool = False,
    all_case_count: int | None = None,
) -> DciBenchmarkInstance:
    instance_id = f"dci.{task_id}"
    return DciBenchmarkInstance(
        instance_id=instance_id,
        version="1.0.0",
        application_ref=ApplicationRef("dci.complete-application", "1.0.0"),
        suite_ref=BenchmarkSuiteRef(instance_id, "1.0.0"),
        task_ids=(task_id,),
        executor_profile="real-agent-judge",
        default_case_limit=1,
        all_case_count=all_case_count,
        cost_class="agent-judge-bounded",
        implementation_state="implemented" if implemented else "planned",
    )


_INSTANCES = tuple(
    sorted(
        (
            DciBenchmarkInstance(
                instance_id="dci.local-fixture",
                version="1.0.0",
                application_ref=ApplicationRef(
                    "dci.local-benchmark-application",
                    "1.0.0",
                ),
                suite_ref=BenchmarkSuiteRef("dci.all", "1.0.0"),
                task_ids=_ALL_TASKS,
                executor_profile="local-fixture",
                default_case_limit=1,
                all_case_count=None,
                cost_class="provider-free",
                implementation_state="implemented",
            ),
            DciBenchmarkInstance(
                instance_id="dci.qa.bamboogle",
                version="1.0.0",
                application_ref=ApplicationRef("dci.complete-application", "1.0.0"),
                suite_ref=BenchmarkSuiteRef(
                    "dci.qa.bamboogle.paper-full125", "1.0.0"
                ),
                task_ids=("qa.bamboogle.paper-full125",),
                executor_profile="real-agent-judge",
                default_case_limit=1,
                all_case_count=125,
                cost_class="agent-judge-bounded",
                implementation_state="implemented",
            ),
            DciBenchmarkInstance(
                instance_id="dci.bcplus.level3",
                version="1.0.0",
                application_ref=ApplicationRef("dci.complete-application", "1.0.0"),
                suite_ref=BenchmarkSuiteRef("dci.bcplus.level3", "1.0.0"),
                task_ids=("bcplus.level3",),
                executor_profile="real-agent-judge",
                default_case_limit=1,
                all_case_count=830,
                cost_class="agent-judge-bounded",
                implementation_state="implemented",
            ),
            *(
                _real_instance(
                    task_id,
                    implemented=False,
                    all_case_count=None,
                )
                for task_id in _ALL_TASKS
                if task_id
                not in {
                    "bcplus.level3",
                    "qa.bamboogle.github-sample50",
                    "qa.bamboogle.paper-full125",
                }
            ),
        ),
        key=lambda instance: instance.selector,
    )
)
_BY_SELECTOR = {instance.selector: instance for instance in _INSTANCES}
if len(_BY_SELECTOR) != len(_INSTANCES):
    raise DciBenchmarkInstanceError("DCI benchmark instance catalog is invalid")


def benchmark_instances() -> tuple[DciBenchmarkInstance, ...]:
    """Return the complete canonical public DCI instance catalog."""

    return _INSTANCES


def select_benchmark_instance(selector: str) -> DciBenchmarkInstance:
    """Select one exact catalog entry without fallback or version ranges."""

    if type(selector) is not str or _SELECTOR.fullmatch(selector) is None:
        raise DciBenchmarkInstanceError("DCI benchmark instance is invalid")
    try:
        return _BY_SELECTOR[selector]
    except KeyError:
        raise DciBenchmarkInstanceError(
            "DCI benchmark instance is unavailable"
        ) from None


def resolve_case_limit(
    instance: DciBenchmarkInstance,
    *,
    case_limit: int | None,
    all_cases: bool,
) -> int:
    """Resolve one exact finite range before generic planning."""

    if (
        not isinstance(instance, DciBenchmarkInstance)
        or type(all_cases) is not bool
        or case_limit is not None
        and (type(case_limit) is not int or case_limit < 1)
        or all_cases
        and case_limit is not None
    ):
        raise DciBenchmarkInstanceError("DCI benchmark case range is invalid")
    if all_cases:
        if instance.all_case_count is None:
            raise DciBenchmarkInstanceError(
                "DCI benchmark all-case range is unavailable"
            )
        return instance.all_case_count
    return instance.default_case_limit if case_limit is None else case_limit


def public_instance_dict(instance: DciBenchmarkInstance) -> dict[str, object]:
    """Return one complete body-free instance summary."""

    if not isinstance(instance, DciBenchmarkInstance):
        raise DciBenchmarkInstanceError("DCI benchmark instance is invalid")
    return {
        "all_case_count": instance.all_case_count,
        "application": instance.application_ref.selector,
        "cost_class": instance.cost_class,
        "default_case_limit": instance.default_case_limit,
        "implementation_state": instance.implementation_state,
        "instance": instance.selector,
        "suite": (
            f"{instance.suite_ref.suite_id}@{instance.suite_ref.version}"
        ),
        "tasks": list(instance.task_ids),
    }


__all__ = (
    "DciBenchmarkInstance",
    "DciBenchmarkInstanceError",
    "benchmark_instances",
    "public_instance_dict",
    "resolve_case_limit",
    "select_benchmark_instance",
)
