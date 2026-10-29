from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_LARGE_VALUES = 150_000


@dataclass(slots=True)
class RatioColumn:
    key: tuple[str, str, str]
    xc: np.ndarray
    dc: np.ndarray
    xb: np.ndarray
    db: np.ndarray
    rel: bool


@dataclass(slots=True)
class PercentileColumn:
    key: tuple[str, str, str]
    q: float
    vc: np.ndarray
    sc: np.ndarray
    vb: np.ndarray
    sb: np.ndarray
    rel: bool


@dataclass(slots=True)
class BootstrapJob:
    seed: int
    resamples: int
    chunk: int
    n_sessions_c: int
    n_sessions_b: int
    ratio: list[RatioColumn]
    percentile: list[PercentileColumn]


@dataclass(slots=True)
class ColumnResult:
    key: tuple[str, str, str]
    point_c: float
    point_b: float
    diffs: np.ndarray


def weighted_quantile(sorted_values: np.ndarray, weights: np.ndarray, quantile: float) -> float:
    if sorted_values.size == 0 or weights.size == 0:
        return float("nan")
    cumulative = np.cumsum(weights)
    total = float(cumulative[-1])
    if total == 0:
        return float("nan")
    index = int(np.argmax(cumulative >= quantile * total))
    return float(sorted_values[index])


def _chunk_size(job: BootstrapJob) -> int:
    largest = 0
    for column in job.percentile:
        largest = max(largest, int(column.vc.size), int(column.vb.size))
    if largest > _LARGE_VALUES:
        return min(job.chunk, 64)
    return job.chunk


def _point_ratio(num: np.ndarray, den: np.ndarray) -> float:
    total = float(np.sum(den))
    if total == 0:
        return float("nan")
    return float(np.sum(num) / total)


def _point_quantile(values: np.ndarray, quantile: float) -> float:
    if values.size == 0:
        return float("nan")
    return float(np.quantile(values, quantile, method="inverted_cdf"))


def _ratio_diffs(
    weight_c: np.ndarray,
    weight_b: np.ndarray,
    num_c: np.ndarray,
    den_c: np.ndarray,
    num_b: np.ndarray,
    den_b: np.ndarray,
    rel: np.ndarray,
) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        est_c = (weight_c @ num_c) / (weight_c @ den_c)
        est_b = (weight_b @ num_b) / (weight_b @ den_b)
        signed = est_c - est_b
        relative = signed / est_b
        diff = np.where(rel, relative, signed)
    diff = np.asarray(diff, dtype=np.float64)
    diff[~np.isfinite(diff)] = np.nan
    return diff


def _percentile_diffs(candidate: np.ndarray, baseline: np.ndarray, rel: bool) -> np.ndarray:
    with np.errstate(divide="ignore", invalid="ignore"):
        diff = (candidate - baseline) / baseline if rel else candidate - baseline
    out = np.asarray(diff, dtype=np.float64)
    out[~np.isfinite(out)] = np.nan
    return out


def _distinct_sides(
    sides: list[tuple[float, np.ndarray, np.ndarray]],
) -> tuple[list[tuple[float, np.ndarray, np.ndarray]], list[int]]:
    # A slice that covers every session, such as the only model an agent uses,
    # repeats the agent-wide column exactly, so each distinct side runs once.
    distinct: list[tuple[float, np.ndarray, np.ndarray]] = []
    positions: list[int] = []
    for quantile, session_index, values in sides:
        for position, (seen_quantile, seen_index, seen_values) in enumerate(distinct):
            if (
                seen_quantile == quantile
                and np.array_equal(seen_index, session_index)
                and np.array_equal(seen_values, values)
            ):
                positions.append(position)
                break
        else:
            positions.append(len(distinct))
            distinct.append((quantile, session_index, values))
    return distinct, positions


def _rows_quantile(
    weights: np.ndarray,
    float_weights: np.ndarray,
    session_index: np.ndarray,
    sorted_values: np.ndarray,
    quantile: float,
) -> np.ndarray:
    count = int(sorted_values.size)
    rows = int(weights.shape[0])
    if count == 0:
        return np.full(rows, np.nan)
    if count <= 4096:
        gathered = weights[:, session_index]
        cumulative = np.cumsum(gathered, axis=1, dtype=weights.dtype)
        total = cumulative[:, -1]
        index = np.argmax(cumulative >= (quantile * total)[:, None], axis=1)
        chosen = sorted_values[index].astype(np.float64, copy=True)
        chosen[total == 0] = np.nan
        return chosen
    return _rows_quantile_prefix(float_weights, session_index, sorted_values, quantile)


def _rows_quantile_prefix(
    weights: np.ndarray, session_index: np.ndarray, sorted_values: np.ndarray, quantile: float
) -> np.ndarray:
    sessions = int(weights.shape[1])
    count = int(sorted_values.size)
    stride = 256
    counts = np.bincount(session_index, minlength=sessions).astype(np.float64)
    blocks = (count + stride - 1) // stride
    prefix = np.zeros((blocks, sessions), dtype=np.float64)
    running = np.zeros(sessions, dtype=np.float64)
    for block in range(blocks):
        sl = session_index[block * stride : (block + 1) * stride]
        running += np.bincount(sl, minlength=sessions)
        prefix[block] = running
    total = weights @ counts
    target = quantile * total
    coarse = weights @ prefix.T
    block_index = np.argmax(coarse >= target[:, None], axis=1)
    index = np.full(weights.shape[0], count - 1, dtype=np.int64)
    for row in range(weights.shape[0]):
        if total[row] <= 0 or coarse[row, -1] < target[row]:
            continue
        block = int(block_index[row])
        start = block * stride
        acc = 0.0 if block == 0 else float(coarse[row, block - 1])
        end = min(count, start + stride)
        row_weights = weights[row]
        goal = float(target[row])
        for offset, session in enumerate(session_index[start:end]):
            acc += float(row_weights[session])
            if acc >= goal:
                index[row] = start + offset
                break
    chosen = sorted_values[index].astype(np.float64, copy=True)
    chosen[total <= 0] = np.nan
    return chosen


def run_bootstrap(job: BootstrapJob) -> list[ColumnResult]:
    rng = np.random.default_rng(job.seed)
    chunk = max(1, _chunk_size(job))
    sessions_c = job.n_sessions_c
    sessions_b = job.n_sessions_b
    resamples = job.resamples
    ratio = job.ratio
    percentile = job.percentile
    ratio_count = len(ratio)
    out_ratio = np.empty((resamples, ratio_count), dtype=np.float64)
    out_pct = np.empty((resamples, len(percentile)), dtype=np.float64)
    num_c = np.column_stack([column.xc for column in ratio]) if ratio else np.zeros((sessions_c, 0))
    den_c = np.column_stack([column.dc for column in ratio]) if ratio else np.zeros((sessions_c, 0))
    num_b = np.column_stack([column.xb for column in ratio]) if ratio else np.zeros((sessions_b, 0))
    den_b = np.column_stack([column.db for column in ratio]) if ratio else np.zeros((sessions_b, 0))
    rel = (
        np.array([column.rel for column in ratio], dtype=bool) if ratio else np.zeros(0, dtype=bool)
    )
    distinct_c, position_c = _distinct_sides([(c.q, c.sc, c.vc) for c in percentile])
    distinct_b, position_b = _distinct_sides([(c.q, c.sb, c.vb) for c in percentile])
    # Poisson weights are small integers. Integer cumulative sums reach the same
    # quantiles as float ones while moving half the memory.
    buffer_c = np.empty((chunk, sessions_c), dtype=np.int32)
    buffer_b = np.empty((chunk, sessions_b), dtype=np.int32)
    filled = 0
    start = 0

    def _flush(count: int, offset: int) -> None:
        if count == 0:
            return
        weight_c = buffer_c[:count]
        weight_b = buffer_b[:count]
        float_c = weight_c.astype(np.float64)
        float_b = weight_b.astype(np.float64)
        if ratio_count:
            out_ratio[offset : offset + count] = _ratio_diffs(
                float_c, float_b, num_c, den_c, num_b, den_b, rel
            )
        candidate = [_rows_quantile(weight_c, float_c, s, v, q) for q, s, v in distinct_c]
        baseline = [_rows_quantile(weight_b, float_b, s, v, q) for q, s, v in distinct_b]
        for index, column in enumerate(percentile):
            out_pct[offset : offset + count, index] = _percentile_diffs(
                candidate[position_c[index]], baseline[position_b[index]], column.rel
            )

    for _resample in range(resamples):
        if sessions_c:
            buffer_c[filled] = rng.poisson(1.0, size=sessions_c)
        if sessions_b:
            buffer_b[filled] = rng.poisson(1.0, size=sessions_b)
        filled += 1
        if filled == chunk:
            _flush(filled, start)
            start += filled
            filled = 0
    _flush(filled, start)
    results: list[ColumnResult] = []
    for index, column in enumerate(ratio):
        results.append(
            ColumnResult(
                column.key,
                _point_ratio(column.xc, column.dc),
                _point_ratio(column.xb, column.db),
                out_ratio[:, index].copy(),
            )
        )
    for index, pct in enumerate(percentile):
        results.append(
            ColumnResult(
                pct.key,
                _point_quantile(pct.vc, pct.q),
                _point_quantile(pct.vb, pct.q),
                out_pct[:, index].copy(),
            )
        )
    return results


def interval(diffs: np.ndarray, alpha_adj: float) -> tuple[float, float, float, float]:
    valid = diffs[np.isfinite(diffs)]
    share = float(valid.size / diffs.shape[0]) if diffs.shape[0] else 0.0
    if valid.size == 0:
        return math.nan, math.nan, math.nan, share
    lower, upper = np.quantile(valid, [alpha_adj / 2, 1 - alpha_adj / 2], method="linear")
    se = float(np.std(valid, ddof=1)) if valid.size > 1 else 0.0
    return float(lower), float(upper), se, share
