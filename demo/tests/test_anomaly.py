"""Unit tests for the anomaly scorer, on fixtures rather than the generated warehouse."""

from datetime import date, timedelta

import pytest

from core_intelligence.anomaly import Flag, detect, robust_z, to_episodes

CONFIG = {"detector": {"window_days": 28, "min_history_days": 10, "min_robust_z": 4.0,
                       "min_dollar_impact": 5.0, "episode_gap_days": 2}}


def series(costs, resource_id="r1", start=date(2026, 4, 1)):
    return {resource_id: [{"date": start + timedelta(days=i), "cost": c, "account_id": "a1",
                           "vertical_id": "v1", "service_name": "svc"} for i, c in enumerate(costs)]}


def test_robust_z_is_zero_on_the_median():
    score, baseline = robust_z(100, [98, 99, 100, 101, 102])
    assert score == 0
    assert baseline == 100


def test_robust_z_uses_median_absolute_deviation_not_mean():
    """An earlier spike in the window must not hide the next one, which is why the scale is the MAD."""
    history = [100, 100, 100, 100, 1000]
    score, _ = robust_z(300, history)
    assert score > 4


def test_flat_history_never_divides_by_zero():
    assert robust_z(100, [100] * 20) == (0.0, 100)
    score, _ = robust_z(150, [100] * 20)
    assert score == float("inf")


def test_detects_a_spike():
    flags = detect(series([100] * 20 + [600]), CONFIG)
    assert [f.detected_date for f in flags] == [date(2026, 4, 21)]
    assert flags[0].dollar_impact == pytest.approx(500)
    assert flags[0].contributing_factors["baseline_cost"] == 100


def test_ignores_a_statistically_odd_but_cheap_day():
    """A resource costing cents can double without being worth anyone's time."""
    assert detect(series([0.10] * 20 + [1.0]), CONFIG) == []


def test_no_flags_without_enough_history():
    assert detect(series([100] * 5 + [900]), CONFIG) == []


def test_steady_spend_raises_nothing():
    assert detect(series([100, 102, 98, 101, 99] * 8), CONFIG) == []


def flag_on(day, resource_id="r1"):
    return Flag(resource_id=resource_id, detected_date=day, observed_cost=200, baseline_cost=100,
                robust_z=8.0, dollar_impact=100)


def test_consecutive_days_collapse_into_one_episode():
    days = [date(2026, 6, 1), date(2026, 6, 2), date(2026, 6, 4)]
    episodes = to_episodes([flag_on(d) for d in days], gap_days=2)
    assert len(episodes) == 1
    assert (episodes[0].start_date, episodes[0].end_date, episodes[0].days) == (days[0], days[-1], 3)
    assert episodes[0].total_impact == pytest.approx(300)


def test_a_long_quiet_gap_starts_a_new_episode():
    episodes = to_episodes([flag_on(date(2026, 6, 1)), flag_on(date(2026, 6, 20))], gap_days=2)
    assert len(episodes) == 2


def test_episodes_are_per_resource():
    episodes = to_episodes([flag_on(date(2026, 6, 1), "r1"), flag_on(date(2026, 6, 1), "r2")], gap_days=2)
    assert {e.resource_id for e in episodes} == {"r1", "r2"}
