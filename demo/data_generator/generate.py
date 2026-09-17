"""Generate the demo dataset from spec.yaml.

Writes FOCUS landing files (one folder per provider, billing period, and delivery), reference files,
ground truth for the eval gate, and a manifest of expected totals. All rules come from the spec.
"""

import calendar
import csv
import hashlib
import json
import random
import shutil
from datetime import date, timedelta
from pathlib import Path

import yaml

SPEC_PATH = Path(__file__).parent / "spec.yaml"
OUT_DIR = Path(__file__).parent.parent / "data"

FOCUS_COLUMNS = [
    "BillingAccountId", "SubAccountId", "SubAccountName", "InvoiceId", "InvoiceIssuerName", "ProviderName",
    "BillingPeriodStart", "BillingPeriodEnd", "ChargePeriodStart", "ChargePeriodEnd",
    "ChargeCategory", "ChargeFrequency", "ChargeDescription", "PricingCategory",
    "CommitmentDiscountId", "CommitmentDiscountType", "CommitmentDiscountStatus",
    "ResourceId", "ResourceName", "RegionId", "ServiceName", "ServiceCategory", "SkuId",
    "PricingUnit", "PricingQuantity", "ConsumedQuantity", "ListUnitPrice", "ContractedUnitPrice",
    "ListCost", "ContractedCost", "BilledCost", "EffectiveCost", "BillingCurrency", "Tags",
]
COST_COLUMNS = ["BilledCost", "EffectiveCost", "ListCost", "ContractedCost"]


def load_spec():
    """Return the parsed spec and the SHA-256 of its bytes."""
    raw = SPEC_PATH.read_bytes()
    return yaml.safe_load(raw), hashlib.sha256(raw).hexdigest()


def period_days(period):
    """Return every date in a YYYY-MM billing period."""
    year, month = map(int, period.split("-"))
    return [date(year, month, d) for d in range(1, calendar.monthrange(year, month)[1] + 1)]


def period_bounds(period):
    """Return the FOCUS billing period start (inclusive) and end (exclusive)."""
    days = period_days(period)
    return days[0], days[-1] + timedelta(days=1)


def is_active(resource, day):
    start = date.fromisoformat(resource["start"]) if resource.get("start") else date.min
    end = date.fromisoformat(resource["end"]) if resource.get("end") else date.max
    return start <= day <= end


def anomaly_factor(anomalies, resource_id, day):
    """Multiplier on qty from every injected anomaly on this resource and day."""
    factor = 1.0
    for a in anomalies:
        if a["resource_id"] != resource_id:
            continue
        start = date.fromisoformat(a["start"])
        n = (day - start).days + 1
        if n < 1:
            continue
        if a["kind"] == "spike" and n <= a["duration_days"]:
            factor *= a["factor"]
        elif a["kind"] == "step":
            factor *= a["factor"]
        elif a["kind"] == "ramp":
            factor *= 1 + a["daily_increase"] * min(n, a["duration_days"])
    return factor


def daily_quantities(spec, days, rng):
    """Draw each resource's qty per active day once, so every delivery shares the same usage."""
    qty = {}
    for day in days:
        for r in spec["resources"]:
            if not is_active(r, day):
                continue
            noise = max(0.0, 1 + rng.gauss(0, r["noise"]))
            qty[(r["resource_id"], day)] = r["qty"] * noise * anomaly_factor(spec["anomalies"], r["resource_id"], day)
    return qty


def contracted_price(spec, resource, provider, period, delivery):
    """List price after the negotiated discount and any restatement that applies to this delivery."""
    price = resource["list_price"] * (1 - spec["providers"][provider]["negotiated_discount"])
    for s in spec["restatements"]:
        if (s["provider"], s["billing_period"], s["service"]) == (provider, period, resource["service"]) and delivery >= s["delivery"]:
            price *= s["contracted_price_factor"]
    return price


def allocate_commitments(spec, provider, day, usage):
    """Return covered contracted cost per (commitment, resource) and unused contracted capacity per commitment."""
    covered, unused = {}, {}
    for c in spec["commitments"]:
        if c["provider"] != provider or not (date.fromisoformat(c["start_date"]) <= day <= date.fromisoformat(c["end_date"])):
            continue
        capacity = c["daily_commitment"] / (1 - c["discount"])
        for rid in c["covers"]:
            if rid not in usage:
                continue
            q, _, cp = usage[rid]
            cover = min(q * cp, capacity)
            covered[(c["commitment_discount_id"], rid)] = cover
            capacity -= cover
        unused[c["commitment_discount_id"]] = capacity
    return covered, unused


def base_row(spec, provider, period, account_id, day):
    p = spec["providers"][provider]
    start, end = period_bounds(period)
    account = next(a for a in spec["accounts"] if a["account_id"] == account_id)
    return {
        "BillingAccountId": p["billing_account"], "SubAccountId": account_id, "SubAccountName": account["account_name"],
        "InvoiceId": f"INV-{provider.upper()}-{period}", "InvoiceIssuerName": p["name"], "ProviderName": p["name"],
        "BillingPeriodStart": f"{start}T00:00:00Z", "BillingPeriodEnd": f"{end}T00:00:00Z",
        "ChargePeriodStart": f"{day}T00:00:00Z", "ChargePeriodEnd": f"{day + timedelta(days=1)}T00:00:00Z",
        "RegionId": p["region"], "BillingCurrency": spec["currency"],
        "CommitmentDiscountId": "", "CommitmentDiscountType": "", "CommitmentDiscountStatus": "",
        "ResourceId": "", "ResourceName": "", "Tags": "{}",
    }


def usage_row(spec, provider, period, resource, day, q, lp, cp, commitment=None, discount=0.0):
    """One usage row: Standard when commitment is None, otherwise the Committed (Used) share."""
    svc = spec["services"][provider][resource["service"]]
    row = base_row(spec, provider, period, resource["account_id"], day)
    tags = {k: resource[k] for k in ("apm_id", "environment") if resource.get(k)}
    contracted = q * cp
    effective = contracted * (1 - discount)
    row.update({
        "ChargeCategory": "Usage", "ChargeFrequency": "Usage-Based",
        "ChargeDescription": f"{svc['name']} {resource['sku']}",
        "PricingCategory": "Committed" if commitment else "Standard",
        "ResourceId": resource["resource_id"], "ResourceName": resource["resource_id"],
        "ServiceName": svc["name"], "ServiceCategory": svc["category"], "SkuId": resource["sku"],
        "PricingUnit": svc["unit"], "PricingQuantity": q, "ConsumedQuantity": q,
        "ListUnitPrice": lp, "ContractedUnitPrice": cp,
        "ListCost": q * lp, "ContractedCost": contracted,
        "BilledCost": 0.0 if commitment else contracted, "EffectiveCost": effective,
        "Tags": json.dumps(tags, sort_keys=True),
    })
    if commitment:
        row.update({"CommitmentDiscountId": commitment["commitment_discount_id"],
                    "CommitmentDiscountType": commitment["commitment_type"], "CommitmentDiscountStatus": "Used"})
    return row


def commitment_rows(spec, provider, period, commitment, day, unused_contracted):
    """The daily purchase row and, if coverage went unused, the Unused row."""
    first_resource = next(r for r in spec["resources"] if r["resource_id"] == commitment["covers"][0])
    svc = spec["services"][provider][first_resource["service"]]
    ids = {"CommitmentDiscountId": commitment["commitment_discount_id"],
           "CommitmentDiscountType": commitment["commitment_type"],
           "ServiceName": svc["name"], "ServiceCategory": svc["category"], "SkuId": commitment["commitment_discount_id"],
           "PricingUnit": "Days", "ListUnitPrice": 0.0, "ContractedUnitPrice": 0.0}
    purchase = base_row(spec, provider, period, first_resource["account_id"], day)
    purchase.update(ids)
    amount = commitment["daily_commitment"]
    purchase.update({
        "ChargeCategory": "Purchase", "ChargeFrequency": "Recurring", "PricingCategory": "Committed",
        "ChargeDescription": f"{commitment['commitment_type']} {commitment['payment_option']} fee",
        "PricingQuantity": 1, "ConsumedQuantity": 0, "ListUnitPrice": amount, "ContractedUnitPrice": amount,
        "ListCost": amount, "ContractedCost": amount, "BilledCost": amount, "EffectiveCost": 0.0,
    })
    rows = [purchase]
    if unused_contracted > 1e-9:
        unused = base_row(spec, provider, period, first_resource["account_id"], day)
        unused.update(ids)
        unused.update({
            "ChargeCategory": "Usage", "ChargeFrequency": "Usage-Based", "PricingCategory": "Committed",
            "CommitmentDiscountStatus": "Unused", "ChargeDescription": "Unused commitment",
            "PricingQuantity": 0, "ConsumedQuantity": 0, "ListCost": 0.0, "ContractedCost": 0.0,
            "BilledCost": 0.0, "EffectiveCost": unused_contracted * (1 - commitment["discount"]),
        })
        rows.append(unused)
    return rows


def account_charge_rows(spec, provider, period):
    rows = []
    for ch in spec["account_charges"]:
        if ch["provider"] != provider:
            continue
        svc = spec["services"][provider][ch["service"]]
        row = base_row(spec, provider, period, ch["account_id"], period_days(period)[0])
        row.update({
            "ChargeCategory": "Usage", "ChargeFrequency": "Recurring", "ChargeDescription": svc["name"],
            "PricingCategory": "Standard", "ServiceName": svc["name"], "ServiceCategory": svc["category"],
            "SkuId": ch["sku"], "PricingUnit": svc["unit"], "PricingQuantity": 1, "ConsumedQuantity": 1,
            "ListUnitPrice": ch["amount"], "ContractedUnitPrice": ch["amount"],
            "ListCost": ch["amount"], "ContractedCost": ch["amount"], "BilledCost": ch["amount"], "EffectiveCost": ch["amount"],
        })
        rows.append(row)
    return rows


def delivery_rows(spec, provider, period, delivery, qty):
    """Every FOCUS row one provider delivers for one billing period."""
    resources = [r for r in spec["resources"] if next(a for a in spec["accounts"] if a["account_id"] == r["account_id"])["provider"] == provider]
    commitments = {c["commitment_discount_id"]: c for c in spec["commitments"]}
    rows = account_charge_rows(spec, provider, period)
    for day in period_days(period):
        usage = {}
        for r in resources:
            if (r["resource_id"], day) in qty:
                usage[r["resource_id"]] = (qty[(r["resource_id"], day)], r["list_price"], contracted_price(spec, r, provider, period, delivery))
        covered, unused = allocate_commitments(spec, provider, day, usage)
        for r in resources:
            if r["resource_id"] not in usage:
                continue
            q, lp, cp = usage[r["resource_id"]]
            covered_cost = sum(v for (cid, rid), v in covered.items() if rid == r["resource_id"])
            share = covered_cost / (q * cp) if q * cp else 0.0
            for (cid, rid), cover in covered.items():
                if rid == r["resource_id"] and cover > 0:
                    rows.append(usage_row(spec, provider, period, r, day, q * cover / (q * cp), lp, cp, commitments[cid], commitments[cid]["discount"]))
            if share < 1 - 1e-12:
                rows.append(usage_row(spec, provider, period, r, day, q * (1 - share), lp, cp))
        for cid, capacity in unused.items():
            rows.extend(commitment_rows(spec, provider, period, commitments[cid], day, capacity))
    return rows


def deliveries(spec):
    """Every (provider, billing period, delivery number) to write; restated periods get extra deliveries."""
    out = []
    for provider in spec["providers"]:
        for period in spec["billing_periods"]:
            extra = [s["delivery"] for s in spec["restatements"] if (s["provider"], s["billing_period"]) == (provider, period)]
            out.extend((provider, period, d) for d in [1, *extra])
    return out


def round_costs(rows):
    for row in rows:
        for col in [*COST_COLUMNS, "PricingQuantity", "ConsumedQuantity", "ListUnitPrice", "ContractedUnitPrice"]:
            row[col] = round(float(row[col]), 6)
    return rows


def write_csv(path, rows, columns):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def write_landing(spec, qty):
    """Write every delivery and return expected totals for the latest delivery of each provider and period."""
    latest = {}
    for provider, period, delivery in deliveries(spec):
        rows = round_costs(delivery_rows(spec, provider, period, delivery, qty))
        path = OUT_DIR / "landing" / "focus" / f"provider={provider}" / f"billing_period={period}" / f"delivery={delivery}" / "focus.csv"
        write_csv(path, rows, FOCUS_COLUMNS)
        totals = {"provider": provider, "billing_account": spec["providers"][provider]["billing_account"],
                  "billing_period": period, "delivery_id": delivery, "row_count": len(rows)}
        totals.update({col: round(sum(r[col] for r in rows), 6) for col in COST_COLUMNS})
        if delivery >= latest.get((provider, period), {}).get("delivery_id", 0):
            latest[(provider, period)] = totals
    return list(latest.values())


def write_reference(spec, days, rng):
    ref = OUT_DIR / "reference"
    write_csv(ref / "verticals.csv", spec["verticals"], ["vertical_id", "vertical_name", "cost_center"])
    accounts = [{**a, "billing_account": spec["providers"][a["provider"]]["billing_account"]} for a in spec["accounts"]]
    write_csv(ref / "accounts.csv", accounts, ["account_id", "provider", "billing_account", "account_name", "vertical_id"])
    write_csv(ref / "apm_applications.csv", spec["applications"], ["apm_id", "name", "vertical_id", "owner", "secondary_approver"])
    commitment_cols = ["commitment_discount_id", "provider", "billing_account", "commitment_type", "scope", "term_months",
                       "payment_option", "discount", "daily_commitment", "start_date", "end_date"]
    commitments = [{**{k: c[k] for k in commitment_cols if k in c}, "billing_account": spec["providers"][c["provider"]]["billing_account"]}
                   for c in spec["commitments"]]
    write_csv(ref / "commitments.csv", commitments, commitment_cols)
    utilization = []
    for day in days:
        for r in spec["resources"]:
            if r.get("cpu") is not None and is_active(r, day):
                cpu = min(100.0, max(0.0, r["cpu"] + rng.gauss(0, spec["utilization"]["cpu_noise"])))
                utilization.append({"date": day, "resource_id": r["resource_id"], "cpu_avg_pct": round(cpu, 2)})
    write_csv(ref / "utilization_daily.csv", utilization, ["date", "resource_id", "cpu_avg_pct"])
    write_csv(ref / "contracts.csv", spec["contracts"], ["apm_id", "allowed_max_tier", "execution_mode", "status"])


def write_ground_truth(spec, last_day):
    rows = []
    for a in spec["anomalies"]:
        start = date.fromisoformat(a["start"])
        end = start + timedelta(days=a["duration_days"] - 1) if a["kind"] == "spike" else last_day
        rows.append({"label_id": a["anomaly_id"], "kind": a["kind"], "resource_id": a["resource_id"],
                     "start_date": start, "end_date": end, "is_anomaly": True})
    for e in spec["expected_changes"]:
        rows.append({"label_id": e["change_id"], "kind": e["kind"], "resource_id": e["resource_id"],
                     "start_date": e["start"], "end_date": e["start"], "is_anomaly": False})
    write_csv(OUT_DIR / "ground_truth" / "anomalies.csv", rows, ["label_id", "kind", "resource_id", "start_date", "end_date", "is_anomaly"])


def main():
    spec, spec_sha = load_spec()
    rng = random.Random(spec["seed"])
    days = [d for p in spec["billing_periods"] for d in period_days(p)]
    shutil.rmtree(OUT_DIR, ignore_errors=True)
    qty = daily_quantities(spec, days, rng)
    expected = write_landing(spec, qty)
    write_reference(spec, days, rng)
    write_ground_truth(spec, days[-1])
    manifest = {"seed": spec["seed"], "spec_sha256": spec_sha, "expected_totals": expected}
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {len(expected)} billing periods ({sum(t['row_count'] for t in expected)} rows in latest deliveries) to {OUT_DIR}")


if __name__ == "__main__":
    main()
