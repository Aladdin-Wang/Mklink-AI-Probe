import time
from dataclasses import replace

import pytest

from _maintainer.testing.performance import stream_benchmark
from _maintainer.testing.performance.stream_benchmark import (
    BenchmarkResult,
    _loss_mismatch,
    run_benchmark,
)
from mklink.remote.stream_protocol import decode_frame


def test_repeated_decoded_batch_sequence_is_corruption():
    def fixed_sequence(wire):
        decoded = decode_frame(wire)
        return replace(decoded, sequence=1)

    result = run_benchmark(
        stream="vofa",
        rate=200,
        duration=0.02,
        channels=1,
        _frame_round_trip=fixed_sequence,
    )

    assert result.sequence_errors > 0
    assert result.exit_code != 0


def test_monotonic_but_wrong_decoded_batch_sequence_is_corruption():
    def offset_sequence(wire):
        decoded = decode_frame(wire)
        return replace(decoded, sequence=decoded.sequence - 1)

    result = run_benchmark(
        stream="vofa",
        rate=200,
        duration=0.02,
        channels=1,
        _frame_round_trip=offset_sequence,
    )

    assert result.sequence_errors > 0
    assert result.exit_code != 0


def test_fake_reported_drops_cannot_hide_a_loss_accounting_mismatch():
    def fake_report(stats):
        return replace(stats, dropped_batches=1, dropped_items=1)

    result = run_benchmark(
        stream="vofa",
        rate=200,
        duration=0.02,
        channels=1,
        _stats_transform=fake_report,
    )

    assert result.produced_items == result.consumed_items
    assert result.reported_drops == 1
    assert result.unreported_drops > 0
    assert result.exit_code != 0


@pytest.mark.parametrize(
    (
        "produced_batches",
        "consumed_batches",
        "produced_items",
        "consumed_items",
        "reported_batches",
        "reported_items",
    ),
    [
        (3, 2, 30, 20, 0, 0),   # under-report
        (3, 3, 30, 30, 1, 10),  # over-report
        (3, 2, 30, 20, 1, 9),   # item-count mismatch
        (3, 2, 30, 20, 0, 10),  # batch-count mismatch
    ],
)
def test_loss_accounting_rejects_under_over_and_cross_counter_mismatches(
    produced_batches,
    consumed_batches,
    produced_items,
    consumed_items,
    reported_batches,
    reported_items,
):
    assert _loss_mismatch(
        produced_batches=produced_batches,
        consumed_batches=consumed_batches,
        produced_items=produced_items,
        consumed_items=consumed_items,
        reported_batches=reported_batches,
        reported_items=reported_items,
    ) > 0


def test_loss_accounting_accepts_exact_batch_and_item_drop_counters():
    assert _loss_mismatch(
        produced_batches=3,
        consumed_batches=2,
        produced_items=30,
        consumed_items=20,
        reported_batches=1,
        reported_items=10,
    ) == 0


def test_short_low_rate_run_does_not_sleep_one_full_sample_period_after_publish():
    result = run_benchmark(
        stream="vofa",
        rate=1,
        duration=0.01,
        channels=1,
    )

    assert result.produced_items == result.consumed_items == 1
    assert result.elapsed >= 0.008
    assert result.elapsed < 0.2


def test_consumer_drains_paced_deliveries_before_producer_finishes():
    result = run_benchmark(
        stream="vofa",
        rate=10_000,
        duration=0.7,
        channels=8,
    )

    assert result.produced_items == result.consumed_items == 7_000
    assert result.reported_drops == 0


def test_producer_failure_releases_delivery_barrier_and_joins(monkeypatch):
    def fail_publish(*args, **kwargs):
        raise OSError("injected publish failure")

    monkeypatch.setattr(
        stream_benchmark.StreamHub,
        "publish_threadsafe",
        fail_publish,
    )
    started = time.perf_counter()

    with pytest.raises(RuntimeError, match="acquisition thread failed") as caught:
        run_benchmark(stream="vofa", rate=10_000, duration=10, channels=8)

    assert isinstance(caught.value.__cause__, OSError)
    assert time.perf_counter() - started < 1.0


def test_main_returns_nonzero_for_sequence_or_accounting_failure(
    monkeypatch,
    capsys,
):
    bad_result = BenchmarkResult(
        produced_items=1,
        consumed_items=1,
        reported_drops=0,
        sequence_errors=1,
        unreported_drops=0,
        bytes_per_sec=1.0,
        peak_queue_depth=1,
        elapsed=0.01,
    )
    monkeypatch.setattr(stream_benchmark, "run_benchmark", lambda **kwargs: bad_result)

    exit_code = stream_benchmark.main(
        ["--stream", "vofa", "--duration", "0.01", "--rate", "1"]
    )

    assert exit_code == 1
    assert '"sequence_errors":1' in capsys.readouterr().out
