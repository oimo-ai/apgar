from __future__ import annotations

import math
from statistics import NormalDist

from apgar.domain.enums import Direction, MetricStatus
from apgar.verdict.power import delta_oriented, orient, power, status


def test_orientation() -> None:
    assert orient(Direction.up, 1.0, 2.0) == (1.0, 2.0)
    assert orient(Direction.down, 1.0, 2.0) == (-2.0, -1.0)
    assert orient(Direction.both, -1.0, 2.0) == (-1.0, 2.0)
    assert delta_oriented(Direction.down, 0.2) == -0.2


def test_status_table() -> None:
    assert status(Direction.up, 0.03, 0.05, 0.02) is MetricStatus.FAIL
    assert status(Direction.up, -0.01, 0.02, 0.02) is MetricStatus.PASS
    assert status(Direction.up, -0.01, 0.04, 0.02) is MetricStatus.INCONCLUSIVE
    assert status(Direction.down, 0.03, 0.05, 0.02) is MetricStatus.FAIL
    assert status(Direction.both, -0.01, 0.01, 0.02) is MetricStatus.PASS
    assert status(Direction.both, 0.03, 0.05, 0.02) is MetricStatus.FAIL
    assert status(Direction.both, -0.05, -0.03, 0.02) is MetricStatus.FAIL


def test_power_formulas() -> None:
    se = 0.01
    tau = 0.02
    alpha = 0.05
    n_c = 100
    turns_needed, detectable = power(n_c, se, tau, alpha)
    z = NormalDist().inv_cdf(1 - alpha / 2)
    z_beta = NormalDist().inv_cdf(0.8)
    expected_n = math.ceil(n_c * (((z + z_beta) * se) / tau) ** 2)
    assert turns_needed == max(0, expected_n - n_c)
    assert detectable == tau + (z + z_beta) * se
    assert power(n_c, 0.0, tau, alpha)[0] == 0
