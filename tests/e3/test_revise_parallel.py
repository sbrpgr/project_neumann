"""FIX-REVISE-504: bounded card concurrency, stable output and delayed mock timing."""

import copy
import threading
import time

import pytest

from neumann.analyze import revise
from neumann.analyze.mock_responders import default_responders
from neumann.llm import LLMResult, MockProvider
from tests.e3.revise_fixtures import make_store
from tests.fixtures.loader import load_fixtures


def seven_cards():
    result = load_fixtures().premortem_result.model_copy(deep=True)
    source = result.risk_cards[0]
    result.risk_cards = [source.model_copy(deep=True, update={
        "card_id": f"card-parallel-{i}", "title": f"{source.title} ({chr(65 + i)})",
    }) for i in range(7)]
    return result


class DelayedMock(MockProvider):
    def __init__(self, delay=0, *, fail_title=None, corrupt_title=None, stagger=False):
        super().__init__(default_responders())
        self.delay = delay
        self.fail_title = fail_title
        self.corrupt_title = corrupt_title
        self.stagger = stagger
        self.lock = threading.Lock()
        self.active = self.peak = 0
        self.completed = []

    def complete_json(self, call):
        title = call.payload["card"]["title"]
        number = ord(title[-2]) - ord("A") + 1
        with self.lock:
            self.active += 1
            self.peak = max(self.peak, self.active)
        try:
            time.sleep(self.delay * (8 - number if self.stagger else 1))
            if title == self.fail_title:
                self.calls.append(call)
                response = LLMResult(False, None, "mock", self.model, call.task, error="timeout")
            else:
                response = super().complete_json(call)
                if title == self.corrupt_title:
                    response.data["interpretation"][0]["excerpt_ids"] = ["FOREIGN"]
            # Distinct per-card usage catches shared adapter/last_result races.
            response.usage = {"input_tokens": number * 10, "output_tokens": number,
                              "total_tokens": number * 11}
            return response
        finally:
            with self.lock:
                self.active -= 1
                self.completed.append(title)


def stable_bundle(bundle):
    out = copy.deepcopy(bundle)
    out.pop("generated_at")
    out.pop("elapsed_s")
    for card in out["revisions"]:
        card.pop("elapsed_s")
    return out


@pytest.mark.parametrize("parallel", [2, 4, 99])
def test_parallel_preserves_order_gate_cost_and_failure_isolation(parallel):
    result = seven_cards()
    requested = [result.risk_cards[i].card_id for i in [0, 6, 1, 5, 2, 4, 3]]
    options = dict(delay=.015, stagger=True, fail_title=result.risk_cards[2].title,
                   corrupt_title=result.risk_cards[4].title)
    sequential = revise.revise_result(result, card_ids=requested, store=make_store(),
                                      llm=DelayedMock(**options), parallel=1)
    provider = DelayedMock(**options)
    concurrent = revise.revise_result(result, card_ids=requested, store=make_store(),
                                      llm=provider, parallel=parallel)
    assert stable_bundle(concurrent) == stable_bundle(sequential)
    assert [r["card_id"] for r in concurrent["revisions"]] == requested
    assert provider.peak == min(parallel, 4)
    titles = {c.card_id: c.title for c in result.risk_cards}
    assert provider.completed != [titles[cid] for cid in requested]
    assert provider.active == 0 and len(provider.calls) == 7
    assert concurrent["cost"]["llm_calls"] == 7
    assert concurrent["cost"]["llm_calls_failed"] == 1
    assert concurrent["cost"]["usage"] == {"input_tokens": 280, "output_tokens": 28, "total_tokens": 308}
    assert concurrent["status"] == "degraded"
    by_id = {r["card_id"]: r for r in concurrent["revisions"]}
    assert by_id[result.risk_cards[2].card_id]["generator"] == "rule"
    assert by_id[result.risk_cards[4].card_id]["audit"]["dropped"] > 0
    assert by_id[result.risk_cards[0].card_id]["status"] == "ok"
    assert revise.validate_revision(concurrent) == []


def test_seven_cards_ten_seconds_each_finish_in_two_parallel_waves():
    result = seven_cards()
    serial_provider = DelayedMock(10)
    started = time.perf_counter()
    serial = revise.revise_result(result, store=make_store(), llm=serial_provider, parallel=1)
    serial_s = time.perf_counter() - started
    parallel_provider = DelayedMock(10)
    started = time.perf_counter()
    # Exercise the production default, not an explicit parallel override.
    concurrent = revise.revise_result(result, store=make_store(), llm=parallel_provider)
    parallel_s = time.perf_counter() - started
    print(f"7 cards x 10s mock: serial={serial_s:.3f}s parallel={parallel_s:.3f}s "
          f"speedup={serial_s / parallel_s:.2f}x peak={parallel_provider.peak}")
    assert 70 <= serial_s < 85
    assert 20 <= parallel_s < 30
    assert parallel_s < serial_s / 3
    assert serial_provider.peak == 1 and parallel_provider.peak == 4
    assert stable_bundle(concurrent) == stable_bundle(serial)
    assert len(concurrent["revisions"]) == concurrent["cost"]["llm_calls"] == 7
