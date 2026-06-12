from __future__ import annotations

from alexa_custom import metrics


def setup_function():
    metrics.reset()


def test_counter_increments():
    metrics.inc("wake_detections")
    metrics.inc("wake_detections", 2)
    assert metrics.snapshot()["counters"]["wake_detections"] == 3


def test_gauge_set():
    metrics.set_gauge("audio_connected", 1.0)
    metrics.set_gauge("audio_connected", 0.0)
    assert metrics.snapshot()["gauges"]["audio_connected"] == 0.0


def test_observe_summary():
    for v in (0.1, 0.3, 0.2):
        metrics.observe("stt_latency_s", v)
    t = metrics.snapshot()["timings"]["stt_latency_s"]
    assert t["count"] == 3
    assert t["max"] == 0.3
    assert t["last"] == 0.2
    assert t["avg"] == round(0.6 / 3, 6)


def test_timer_records_duration():
    with metrics.timer("block_s"):
        pass
    t = metrics.snapshot()["timings"]["block_s"]
    assert t["count"] == 1
    assert t["last"] >= 0.0


def test_snapshot_is_serialisable():
    import json

    metrics.inc("x")
    metrics.set_gauge("y", 2)
    metrics.observe("z", 1.0)
    json.dumps(metrics.snapshot())  # must not raise
