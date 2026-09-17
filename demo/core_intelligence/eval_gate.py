"""Eval gate for the anomaly detector.

There are no real anomaly labels in a FinOps practice that has never scored its own alerts, so the
demo does what MLOps Pipeline §2.4 designs for: inject anomalies of known kind and size, and score
the detector against them. The detector never reads the ground truth file.

Measures, for the detector and for a naive baseline it has to beat:
  1. recall by anomaly kind (spike, step, ramp)
  2. detection lag in days
  3. alert volume per vertical per week, the main adoption risk
  4. false positives on expected changes (a new resource, a removed resource)

Exits non-zero if any gate threshold is missed, so CI can block a change.
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

import duckdb

from core_intelligence.anomaly import DB_PATH, baseline_detect, daily_series, detect, load_config, to_episodes

GROUND_TRUTH_PATH = Path("data/ground_truth/anomalies.csv")


def load_labels(path=GROUND_TRUTH_PATH):
    with Path(path).open() as fh:
        return [{**row,
                 "start_date": date.fromisoformat(row["start_date"]),
                 "end_date": date.fromisoformat(row["end_date"]),
                 "is_anomaly": row["is_anomaly"] == "True"}
                for row in csv.DictReader(fh)]


def overlapping(episode, label):
    return episode.resource_id == label["resource_id"] and episode.start_date <= label["end_date"] and episode.end_date >= label["start_date"]


def score(episodes, labels, config, weeks, vertical_count):
    """Recall by kind, detection lag, alert volume, and false positives on expected changes."""
    anomalies = [l for l in labels if l["is_anomaly"]]
    matched, lags = {}, []
    for label in anomalies:
        hits = [e for e in episodes if overlapping(e, label)]
        matched[label["label_id"]] = bool(hits)
        if hits:
            lags.append((min(h.start_date for h in hits) - label["start_date"]).days)

    kinds = sorted({l["kind"] for l in anomalies})
    recall = {k: sum(matched[l["label_id"]] for l in anomalies if l["kind"] == k) / sum(1 for l in anomalies if l["kind"] == k)
              for k in kinds}

    window = timedelta(days=config["gate"]["expected_change_window_days"])
    expected_changes = [l for l in labels if not l["is_anomaly"]]
    expected_fps = [e for e in episodes for l in expected_changes
                    if e.resource_id == l["resource_id"] and l["start_date"] <= e.start_date <= l["start_date"] + window]
    unexplained = [e for e in episodes if not any(overlapping(e, l) for l in anomalies) and e not in expected_fps]

    return {
        "alerts": len(episodes),
        "recall": recall,
        "matched": matched,
        "median_lag_days": sorted(lags)[len(lags) // 2] if lags else None,
        "alerts_per_vertical_per_week": len(episodes) / (weeks * vertical_count),
        "expected_change_false_positives": len(expected_fps),
        "unexplained_alerts": len(unexplained),
    }


def check_gate(result, baseline, config):
    """Return (passed, failures). The detector must clear every threshold and beat the baseline."""
    gate, failures = config["gate"], []
    for kind, minimum in gate["min_recall_by_kind"].items():
        actual = result["recall"].get(kind)
        if actual is None:
            failures.append(f"no labels of kind {kind}")
        elif actual < minimum:
            failures.append(f"recall on {kind} is {actual:.2f}, below {minimum:.2f}")
    if result["alerts_per_vertical_per_week"] > gate["max_alerts_per_vertical_per_week"]:
        failures.append(f"alert volume is {result['alerts_per_vertical_per_week']:.2f} per vertical per week, "
                        f"above {gate['max_alerts_per_vertical_per_week']}")
    if result["expected_change_false_positives"] > gate["max_expected_change_false_positives"]:
        failures.append(f"{result['expected_change_false_positives']} expected changes flagged as anomalies, "
                        f"above {gate['max_expected_change_false_positives']}")
    if sum(result["recall"].values()) < sum(baseline["recall"].values()):
        failures.append("baseline recall is higher than the detector's")
    if sum(result["recall"].values()) == sum(baseline["recall"].values()) and result["alerts"] > baseline["alerts"]:
        failures.append("baseline matches the detector's recall with fewer alerts")
    return not failures, failures


def report(result, baseline, labels, config):
    print(f"Eval gate: {config['model_version']}\n")
    print(f"{'metric':<42}{'detector':>12}{'naive baseline':>18}")
    for kind in sorted(result["recall"]):
        print(f"{'recall: ' + kind:<42}{result['recall'][kind]:>12.2f}{baseline['recall'].get(kind, 0):>18.2f}")
    print(f"{'alerts raised':<42}{result['alerts']:>12}{baseline['alerts']:>18}")
    print(f"{'alerts per vertical per week':<42}{result['alerts_per_vertical_per_week']:>12.2f}"
          f"{baseline['alerts_per_vertical_per_week']:>18.2f}")
    print(f"{'median detection lag (days)':<42}{str(result['median_lag_days']):>12}{str(baseline['median_lag_days']):>18}")
    print(f"{'expected changes wrongly flagged':<42}{result['expected_change_false_positives']:>12}"
          f"{baseline['expected_change_false_positives']:>18}")
    print(f"{'alerts matching no injected anomaly':<42}{result['unexplained_alerts']:>12}{baseline['unexplained_alerts']:>18}")
    print("\ninjected anomalies")
    for label in [l for l in labels if l["is_anomaly"]]:
        print(f"  {'found  ' if result['matched'][label['label_id']] else 'MISSED '}"
              f"{label['label_id']}  {label['kind']:<6} {label['resource_id']}")


def main():
    config = load_config()
    con = duckdb.connect(DB_PATH, read_only=True)
    con.sql("set TimeZone = 'UTC'")
    series = daily_series(con)
    days = [p["date"] for points in series.values() for p in points]
    weeks = (max(days) - min(days)).days / 7
    vertical_count = con.sql("select count(distinct vertical_id) from gold.fact_cost_daily").fetchone()[0]
    labels = load_labels()

    gap = config["detector"]["episode_gap_days"]
    result = score(to_episodes(detect(series, config), gap), labels, config, weeks, vertical_count)
    baseline = score(to_episodes(baseline_detect(series, config), gap), labels, config, weeks, vertical_count)

    report(result, baseline, labels, config)
    passed, failures = check_gate(result, baseline, config)
    print("\nGATE PASSED" if passed else "\nGATE FAILED")
    for failure in failures:
        print(f"  {failure}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
