"""Short release gate for the binary stream transport."""

from _maintainer.testing.performance.stream_benchmark import run_benchmark


def test_waveform_10k_samples_per_second_for_ten_seconds():
    result = run_benchmark(
        stream="vofa",
        rate=10_000,
        duration=10,
        channels=8,
    )

    assert result.sequence_errors == 0
    assert result.unreported_drops == 0
    assert result.consumed_items >= 100_000
