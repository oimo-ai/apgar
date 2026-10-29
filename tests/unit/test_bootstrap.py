from __future__ import annotations

import numpy as np

from apgar.verdict.bootstrap import (
    BootstrapJob,
    PercentileColumn,
    RatioColumn,
    _rows_quantile_prefix,
    run_bootstrap,
    weighted_quantile,
)


def _ratio(seed: int, chunk: int, extra: bool) -> np.ndarray:
    rng = np.random.default_rng(0)
    job = BootstrapJob(
        seed=seed,
        resamples=64,
        chunk=chunk,
        n_sessions_c=5,
        n_sessions_b=4,
        ratio=[
            RatioColumn(
                ("tool_error_rate", "", ""),
                rng.random(5),
                np.ones(5),
                rng.random(4),
                np.ones(4),
                False,
            )
        ],
        percentile=[],
    )
    if extra:
        job.ratio.append(
            RatioColumn(
                ("llm_error_rate", "surface", "web"),
                rng.random(5),
                np.ones(5),
                rng.random(4),
                np.ones(4),
                True,
            )
        )
    found = next(item for item in run_bootstrap(job) if item.key[0] == "tool_error_rate")
    return found.diffs


def test_same_seed_same_result() -> None:
    left = _ratio(7, 16, False)
    right = _ratio(7, 16, False)
    assert np.array_equal(left, right, equal_nan=True)


def test_different_seed_differs() -> None:
    assert not np.array_equal(_ratio(1, 16, False), _ratio(2, 16, False), equal_nan=True)


def test_weights_independent_of_columns() -> None:
    left = _ratio(9, 16, False)
    right = _ratio(9, 16, True)
    assert np.allclose(left, right, equal_nan=True)


def test_chunk_size_does_not_change_results() -> None:
    # The resample draws are the same for every chunk size. The weighted sums are a
    # BLAS matmul whose blocking follows the row count, so the last bits can differ.
    left = _ratio(3, 7, False)
    right = _ratio(3, 256, False)
    assert np.allclose(left, right, rtol=1e-12, atol=1e-12, equal_nan=True)


def test_ratio_point_estimates() -> None:
    job = BootstrapJob(
        seed=1,
        resamples=8,
        chunk=4,
        n_sessions_c=2,
        n_sessions_b=2,
        ratio=[
            RatioColumn(
                ("tool_error_rate", "", ""),
                np.array([1.0, 3.0]),
                np.array([2.0, 2.0]),
                np.array([1.0, 1.0]),
                np.array([4.0, 4.0]),
                False,
            )
        ],
        percentile=[],
    )
    result = run_bootstrap(job)[0]
    assert result.point_c == 1.0
    assert result.point_b == 0.25


def test_relative_difference() -> None:
    job = BootstrapJob(
        seed=1,
        resamples=4,
        chunk=4,
        n_sessions_c=1,
        n_sessions_b=1,
        ratio=[
            RatioColumn(
                ("cost_per_turn", "", ""),
                np.array([2.0]),
                np.array([1.0]),
                np.array([1.0]),
                np.array([1.0]),
                True,
            )
        ],
        percentile=[],
    )
    result = run_bootstrap(job)[0]
    finite = result.diffs[np.isfinite(result.diffs)]
    assert finite.size > 0
    assert np.allclose(finite, 1.0)


def test_den_zero_gives_nan() -> None:
    job = BootstrapJob(
        seed=1,
        resamples=4,
        chunk=4,
        n_sessions_c=1,
        n_sessions_b=1,
        ratio=[
            RatioColumn(
                ("tool_error_rate", "", ""),
                np.array([1.0]),
                np.array([0.0]),
                np.array([1.0]),
                np.array([1.0]),
                False,
            )
        ],
        percentile=[],
    )
    assert np.isnan(run_bootstrap(job)[0].diffs).all()


def test_weighted_quantile_matches_definition() -> None:
    values = np.array([1.0, 2.0, 5.0, 9.0])
    sessions = np.array([0, 1, 0, 1])
    weights = np.array([1.0, 3.0])
    expanded = weights[sessions]
    total = float(expanded.sum())
    cumulative = 0.0
    expected = values[-1]
    for value, weight in zip(values, expanded, strict=True):
        cumulative += float(weight)
        if cumulative >= 0.5 * total:
            expected = float(value)
            break
    assert weighted_quantile(values, expanded, 0.5) == expected


def test_coverage_equal_arms() -> None:
    covered = 0
    pairs = 40
    for seed in range(pairs):
        rng = np.random.default_rng(seed)
        sessions = 30
        xc = rng.binomial(1, 0.2, size=sessions).astype(float)
        xb = rng.binomial(1, 0.2, size=sessions).astype(float)
        job = BootstrapJob(
            seed=1000 + seed,
            resamples=400,
            chunk=100,
            n_sessions_c=sessions,
            n_sessions_b=sessions,
            ratio=[
                RatioColumn(
                    ("tool_error_rate", "", ""),
                    xc,
                    np.ones(sessions),
                    xb,
                    np.ones(sessions),
                    False,
                )
            ],
            percentile=[],
        )
        diffs = run_bootstrap(job)[0].diffs
        lower, upper = np.quantile(diffs[np.isfinite(diffs)], [0.025, 0.975])
        if lower <= 0 <= upper:
            covered += 1
    assert covered >= int(0.9 * pairs)


def test_detects_injected_regression() -> None:
    rng = np.random.default_rng(4)
    sessions = 200
    calls = np.full(sessions, 10.0)
    xc = rng.binomial(10, 0.09, size=sessions).astype(float)
    xb = rng.binomial(10, 0.02, size=sessions).astype(float)
    job = BootstrapJob(
        seed=11,
        resamples=1000,
        chunk=256,
        n_sessions_c=sessions,
        n_sessions_b=sessions,
        ratio=[RatioColumn(("tool_error_rate", "", ""), xc, calls, xb, calls.copy(), False)],
        percentile=[
            PercentileColumn(
                ("latency_p95", "", ""),
                0.95,
                np.arange(4, dtype=float),
                np.zeros(4, dtype=int),
                np.arange(4, dtype=float),
                np.zeros(4, dtype=int),
                False,
            )
        ],
    )
    result = next(item for item in run_bootstrap(job) if item.key[0] == "tool_error_rate")
    lower = float(np.quantile(result.diffs, 0.025))
    assert lower > 0.02


def test_prefix_quantile_matches_definition() -> None:
    rng = np.random.default_rng(5)
    values = np.sort(rng.random(5000))
    sessions = rng.integers(0, 12, size=5000)
    weights = rng.poisson(1.0, size=(4, 12)).astype(np.float64)
    got = _rows_quantile_prefix(weights, sessions, values, 0.95)
    for row in range(weights.shape[0]):
        expected = weighted_quantile(values, weights[row, sessions], 0.95)
        if np.isnan(expected):
            assert np.isnan(got[row])
        else:
            assert got[row] == expected


def _percentile_job(columns: list[PercentileColumn], sessions: int) -> BootstrapJob:
    return BootstrapJob(
        seed=5,
        resamples=200,
        chunk=64,
        n_sessions_c=sessions,
        n_sessions_b=sessions,
        ratio=[],
        percentile=columns,
    )


def _sides(sessions: int) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    return (
        np.sort(rng.random(120)),
        rng.integers(0, sessions, size=120),
        np.sort(rng.random(90)),
        rng.integers(0, sessions, size=90),
    )


def test_percentile_diffs_match_definition() -> None:
    sessions = 40
    vc, sc, vb, sb = _sides(sessions)
    job = _percentile_job(
        [PercentileColumn(("latency_p95", "", ""), 0.95, vc, sc, vb, sb, False)], sessions
    )
    diffs = run_bootstrap(job)[0].diffs
    rng = np.random.default_rng(job.seed)
    for row in range(job.resamples):
        weight_c = rng.poisson(1.0, size=sessions)
        weight_b = rng.poisson(1.0, size=sessions)
        candidate = weighted_quantile(vc, weight_c[sc], 0.95)
        baseline = weighted_quantile(vb, weight_b[sb], 0.95)
        assert diffs[row] == candidate - baseline


def test_repeated_percentile_columns_match_a_single_column() -> None:
    sessions = 40
    vc, sc, vb, sb = _sides(sessions)
    whole = PercentileColumn(("latency_p95", "", ""), 0.95, vc, sc, vb, sb, False)
    alone = run_bootstrap(_percentile_job([whole], sessions))[0].diffs
    relative = PercentileColumn(("latency_p95", "", ""), 0.95, vc, sc, vb, sb, True)
    relative_alone = run_bootstrap(_percentile_job([relative], sessions))[0].diffs
    only_model = PercentileColumn(
        ("latency_p95", "model", "m1"), 0.95, vc.copy(), sc.copy(), vb.copy(), sb.copy(), False
    )
    median = PercentileColumn(("latency_p95", "surface", "web"), 0.5, vc, sc, vb, sb, False)
    results = run_bootstrap(_percentile_job([whole, only_model, relative, median], sessions))
    assert np.array_equal(results[0].diffs, alone, equal_nan=True)
    assert np.array_equal(results[1].diffs, alone, equal_nan=True)
    assert np.array_equal(results[2].diffs, relative_alone, equal_nan=True)
    assert not np.array_equal(results[3].diffs, alone, equal_nan=True)
