from __future__ import annotations

from datetime import datetime

import pytest

from apgar.assembly.cost import turn_cost
from tests.support import make_span


def test_cost_is_the_sum_of_span_costs(fixed_now: datetime) -> None:
    spans = [
        make_span(fixed_now, cost_usd=0.003, input_tokens=900, output_tokens=150),
        make_span(fixed_now, span_id="bb" * 8, cost_usd=0.001, input_tokens=10, output_tokens=10),
    ]
    assert turn_cost(spans) == pytest.approx(0.004)


def test_span_with_tokens_and_no_cost_leaves_the_turn_unset(fixed_now: datetime) -> None:
    spans = [
        make_span(fixed_now, cost_usd=0.003, input_tokens=900, output_tokens=150),
        make_span(fixed_now, span_id="bb" * 8, cost_usd=None, input_tokens=10, output_tokens=10),
    ]
    assert turn_cost(spans) is None


def test_span_without_tokens_or_cost_is_skipped(fixed_now: datetime) -> None:
    spans = [
        make_span(fixed_now, cost_usd=0.003, input_tokens=900, output_tokens=150),
        make_span(fixed_now, span_id="bb" * 8),
    ]
    assert turn_cost(spans) == 0.003


def test_no_cost_anywhere_is_unset(fixed_now: datetime) -> None:
    assert turn_cost([make_span(fixed_now)]) is None
    assert turn_cost([]) is None
