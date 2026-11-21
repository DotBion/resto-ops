"""Original, non-photographic café scene used for the offline demonstration."""

import math
from dataclasses import dataclass

WIDTH, HEIGHT, FPS, SECONDS = 960, 600, 12, 32
QUEUE_POSITIONS = [(727, 195), (723, 243), (724, 292), (724, 341), (729, 390)]
COLORS = ["#c27a49", "#748f85", "#a4a7cf", "#d5aa69", "#537d7a", "#946b63", "#6f7b9c"]


@dataclass(frozen=True)
class Actor:
    id: str
    x: float
    y: float
    color: str
    facing: float
    membership: str

    def box(self) -> dict:
        return dict(
            x1=round((self.x - 19) / WIDTH, 5), y1=round((self.y - 15) / HEIGHT, 5),
            x2=round((self.x + 19) / WIDTH, 5), y2=round((self.y + 16) / HEIGHT, 5),
        )


def drift(time: float, phase: float) -> float:
    return 1.6 * math.sin(time * 1.8 + phase)


def world(at_ms: int) -> tuple[list[Actor], list[dict]]:
    time = at_ms / 1000
    actors = [
        Actor("staff", 874, 201 + drift(time, 0), "#384e46", -math.pi / 2, "other"),
        Actor("table_a", 255, 188 + drift(time, 1), "#628376", math.pi, "other"),
        Actor("table_b", 255, 285 + drift(time, 2), "#b8866a", 0, "other"),
        Actor("laptop", 369, 445 + drift(time, 3), "#616984", 0, "other"),
    ]
    groups = [{"id": "table", "activity": "eating", "members": ["table_a", "table_b"]}]
    if 5 <= time < 12:
        movement = min(1, (time - 5) / 1.2)
        for i, (x, y) in enumerate([(613, 263), (618, 317)]):
            actors.append(Actor(f"friend_{i}", x - 50 * (1 - movement), y + drift(time, i),
                                COLORS[5 + i], math.pi * (1 - i), "other"))
        groups.append({"id": "friends", "activity": "unknown", "members": ["friend_0", "friend_1"]})

    count = next(n for at, n in [(27, 1), (23, 3), (17, 5), (14, 4), (12, 3), (4, 2), (0, 1)] if time >= at)
    for i, (x, y) in enumerate(QUEUE_POSITIONS[:count]):
        actors.append(Actor(f"queue_{i}", x + drift(time, i), y + drift(time, i + 1),
                            COLORS[i], math.pi / 2 if i == 0 else 0, "waiting"))
    if count >= 2:
        groups.append({"id": "line", "activity": "queueing", "members": [f"queue_{i}" for i in range(count)]})
    return actors, groups
