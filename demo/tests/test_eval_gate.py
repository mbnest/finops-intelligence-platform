"""Unit tests for the eval gate: it has to fail when the detector gets worse."""

from datetime import date

from core_intelligence.anomaly import Episode
from core_intelligence.eval_gate import check_gate, score

CONFIG = {
    "gate": {"min_recall_by_kind": {"spike": 1.0, "step": 1.0}, "max_alerts_per_vertical_per_week": 2.0,
             "max_expected_change_false_positives": 0, "expected_change_window_days": 3},
}

LABELS = [
    {"label_id": "GT-1", "kind": "spike", "resource_id": "r1", "start_date": date(2026, 5, 12),
     "end_date": date(2026, 5, 12), "is_anomaly": True},
    {"label_id": "GT-2", "kind": "step", "resource_id": "r2", "start_date": date(2026, 6, 3),
     "end_date": date(2026, 6, 30), "is_anomaly": True},
    {"label_id": "EC-1", "kind": "new_resource", "resource_id": "r3", "start_date": date(2026, 6, 1),
     "end_date": date(2026, 6, 1), "is_anomaly": False},
]


def episode(resource_id, start, end=None, impact=100.0):
    end = end or start
    return Episode(resource_id=resource_id, start_date=start, end_date=end, days=(end - start).days + 1,
                   total_impact=impact, peak_impact=impact, peak_robust_z=8.0, baseline_cost=50.0,
                   account_id="a1", vertical_id="v1", service_name="svc")


def scored(episodes, weeks=13, verticals=5):
    return score(episodes, LABELS, CONFIG, weeks, verticals)


def test_finding_both_anomalies_passes():
    result = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20))])
    assert result["recall"] == {"spike": 1.0, "step": 1.0}
    assert check_gate(result, scored([]), CONFIG) == (True, [])


def test_missing_an_anomaly_fails_the_gate():
    result = scored([episode("r1", date(2026, 5, 12))])
    passed, failures = check_gate(result, scored([]), CONFIG)
    assert not passed
    assert any("recall on step" in f for f in failures)


def test_detection_lag_is_measured_from_the_label_start():
    result = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 6), date(2026, 6, 20))])
    assert result["median_lag_days"] == 3


def test_flagging_an_expected_change_fails_the_gate():
    """A new resource is a real cost change, not an anomaly. Flagging it is a false positive."""
    episodes = [episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20)),
                episode("r3", date(2026, 6, 2))]
    result = scored(episodes)
    assert result["expected_change_false_positives"] == 1
    passed, failures = check_gate(result, scored([]), CONFIG)
    assert not passed
    assert any("expected changes flagged" in f for f in failures)


def test_alert_flood_fails_the_gate_even_with_perfect_recall():
    noise = [episode(f"n{i}", date(2026, 6, 10)) for i in range(200)]
    result = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20)), *noise])
    passed, failures = check_gate(result, scored([]), CONFIG)
    assert not passed
    assert any("alert volume" in f for f in failures)


def test_losing_to_the_baseline_fails_the_gate():
    detector = scored([episode("r1", date(2026, 5, 12))])
    baseline = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20))])
    passed, failures = check_gate(detector, baseline, CONFIG)
    assert not passed
    assert any("baseline recall is higher" in f for f in failures)


def test_matching_the_baseline_with_more_alerts_fails_the_gate():
    detector = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20)),
                       episode("n1", date(2026, 6, 11))])
    baseline = scored([episode("r1", date(2026, 5, 12)), episode("r2", date(2026, 6, 4), date(2026, 6, 20))])
    passed, failures = check_gate(detector, baseline, CONFIG)
    assert not passed
    assert any("fewer alerts" in f for f in failures)
