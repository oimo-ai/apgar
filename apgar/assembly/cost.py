from __future__ import annotations

from apgar.domain.models import SpanRow


def turn_cost(chat_spans: list[SpanRow]) -> float | None:
    # A chat span with token counts and no cost makes the turn total unknown, not lower.
    total: float | None = None
    for span in chat_spans:
        if span.cost_usd is None:
            if span.input_tokens is None and span.output_tokens is None:
                continue
            return None
        total = (total or 0.0) + span.cost_usd
    return total
