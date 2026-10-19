from __future__ import annotations

import math
from statistics import NormalDist

from apgar.domain.enums import Direction, MetricStatus


def orient(direction: Direction, lower: float, upper: float) -> tuple[float, float]:
    if direction is Direction.down:
        return (-upper, -lower)
    return (lower, upper)


def delta_oriented(direction: Direction, point_diff: float) -> float:
    if direction is Direction.down:
        return -point_diff
    return point_diff


def status(direction: Direction, lower: float, upper: float, tau: float) -> MetricStatus:
    if direction is Direction.both:
        if lower > tau or upper < -tau:
            return MetricStatus.FAIL
        if -tau <= lower and upper <= tau:
            return MetricStatus.PASS
        return MetricStatus.INCONCLUSIVE
    if lower > tau:
        return MetricStatus.FAIL
    if upper <= tau:
        return MetricStatus.PASS
    return MetricStatus.INCONCLUSIVE


def power(n_c: int, se: float, tau: float, alpha_adj: float) -> tuple[int, float]:
    z = NormalDist().inv_cdf(1 - alpha_adj / 2)
    z_beta = NormalDist().inv_cdf(0.8)
    n_pass = 0 if se == 0 or tau == 0 else math.ceil(n_c * (((z + z_beta) * se) / tau) ** 2)
    turns_needed = max(0, n_pass - n_c)
    detectable = tau + (z + z_beta) * se
    return turns_needed, detectable
