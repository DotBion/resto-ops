from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Provider = Literal["fixture", "gemini"]
Strategy = Literal["agent", "baseline"]
Activity = Literal["queueing", "ordering", "eating", "working", "fighting", "selfie", "unknown"]
Membership = Literal["waiting", "other", "uncertain"]
Count = Annotated[int, Field(ge=0, le=100)]
Coordinate = Annotated[float, Field(ge=0, le=1)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Box(Contract):
    x1: Coordinate
    y1: Coordinate
    x2: Coordinate
    y2: Coordinate

    @model_validator(mode="after")
    def positive_area(self) -> "Box":
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError("box must have positive area")
        return self


class Person(Contract):
    id: Annotated[str, Field(min_length=1, max_length=24)]
    box: Box
    membership: Membership


class Group(Contract):
    id: Annotated[str, Field(min_length=1, max_length=24)]
    activity: Activity
    members: Annotated[list[str], Field(min_length=2, max_length=30)]


class Inspection(Contract):
    tool: Literal["inspect_frames", "inspect_region", "compare_observations"]
    frame: Annotated[int, Field(ge=1, le=10)] | None
    region: Box | None

    @model_validator(mode="after")
    def region_reference(self) -> "Inspection":
        if self.tool == "inspect_region" and (self.frame is None or self.region is None):
            raise ValueError("a crop requires a supplied frame number and region")
        return self


class Scene(Contract):
    queue_min: Count | None
    queue_max: Count | None
    visibility: Literal["clear", "uncertain"]
    summary: Annotated[str, Field(min_length=1, max_length=360)]
    people: Annotated[list[Person], Field(max_length=30)]
    groups: Annotated[list[Group], Field(max_length=15)]
    evidence_frames: Annotated[list[Annotated[int, Field(ge=1, le=10)]], Field(max_length=6)]
    inspection: Inspection | None

    @model_validator(mode="after")
    def consistent(self) -> "Scene":
        if (self.queue_min is None) != (self.queue_max is None):
            raise ValueError("both queue bounds must be supplied together")
        if self.queue_min is not None and self.queue_min > self.queue_max:
            raise ValueError("queue bounds must be ordered")
        if self.visibility == "clear" and (
            self.queue_min is None or self.queue_min != self.queue_max
        ):
            raise ValueError("clear visibility requires an exact estimate")
        people = {p.id for p in self.people}
        members = [member for group in self.groups for member in group.members]
        if len(people) != len(self.people) or len({g.id for g in self.groups}) != len(self.groups):
            raise ValueError("duplicate person or group ID")
        if not set(members) <= people or len(set(members)) != len(members):
            raise ValueError("group members must reference distinct visible people")
        return self


class NewRun(Contract):
    source_id: str
    provider: Provider
    strategy: Strategy = "agent"
    threshold: Annotated[int, Field(ge=2, le=30)] | None = None


class Playhead(Contract):
    at_ms: Annotated[int, Field(ge=0, le=12 * 60 * 60 * 1000)]
    final: bool = False


class Source(Contract):
    id: str
    label: str
    kind: Literal["synthetic", "cafe", "upload", "camera"]
    duration_ms: int
    width: int
    height: int
    frame_count: int
