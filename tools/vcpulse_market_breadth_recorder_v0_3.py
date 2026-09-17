#!/usr/bin/env python3
"""VCPulse Market Breadth Beta v0.3 Recorder.

Research-only recorder. Reads the current TW official snapshot, computes frozen v0.1
and experimental v0.2 scores, and UPSERTS one row per official data_date.
Safe to run repeatedly: the same trading date is replaced, never duplicated.
"""
from __future__ import annotations
import argparse, csv, importlib.util, json
from pathlib import Path


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


def flat_row(v1: dict, v2: dict) -> dict:
    if not v1.get("data_date") or v1.get("data_date") != v2.get("data_date"):
        raise RuntimeError("Missing or mismatched TW official data_date; recorder aborted.")
    row = {
        "data_date": v2["data_date"],
        "twse_close": v2.get("twse_close"),
        "twse_change_pct": v2.get("twse_change_pct"),
        "candidate_count": v2.get("candidate_count"),
        "breakout_count": v2.get("breakout_count"),
        "postbreakout_count": v2.get("postbreakout_count"),
        "near_pivot_count": v2.get("near_pivot_count"),
        "forming_count": v2.get("forming_count"),
        "volume_breakout_count": v2.get("volume_breakout_count"),
        "active_industry_count": v2.get("active_industry_count"),
        "industry_count": v2.get("industry_count"),
        "extended_count": v2.get("extended_count"),
        "failed_count": v2.get("failed_count"),
        "v01_score": v1.get("score"), "v01_regime": v1.get("regime"),
        "v02_score": v2.get("score"), "v02_regime": v2.get("regime"),
    }
    for k, val in (v1.get("components") or {}).items(): row[f"v01_{k}"] = val
    for k, val in (v2.get("components") or {}).items(): row[f"v02_{k}"] = val
    return row


def upsert_csv(path: Path, row: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    old = []
    if path.exists():
        with path.open("r", newline="", encoding="utf-8-sig") as f:
            old = list(csv.DictReader(f))
    by_date = {r.get("data_date"): r for r in old if r.get("data_date")}
    by_date[row["data_date"]] = {k: str(v) if v is not None else "" for k, v in row.items()}
    rows = [by_date[d] for d in sorted(by_date)]
    fields = list(row.keys())
    # Preserve any legacy columns if a future/older recorder added them.
    for r in rows:
        for k in r:
            if k not in fields: fields.append(k)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="screening.json")
    ap.add_argument("--latest", default="data/market_breadth_latest.json")
    ap.add_argument("--history", default="data/market_breadth_history.csv")
    args = ap.parse_args()
    here = Path(__file__).resolve().parent
    v1m = load_module(here / "vcpulse_market_breadth_v0_1.py", "mb_v01")
    v2m = load_module(here / "vcpulse_market_breadth_v0_2.py", "mb_v02")
    snap = json.loads(Path(args.input).read_text(encoding="utf-8"))
    v1, v2 = v1m.compute(snap), v2m.compute(snap)
    row = flat_row(v1, v2)
    latest = {"data_date": row["data_date"], "v0.1": v1, "v0.2": v2,
              "note": "Research-only. Scores are not predictive probabilities or trading signals."}
    Path(args.latest).parent.mkdir(parents=True, exist_ok=True)
    Path(args.latest).write_text(json.dumps(latest, ensure_ascii=False, indent=2), encoding="utf-8")
    upsert_csv(Path(args.history), row)
    print(json.dumps({"status":"ok", "data_date":row["data_date"], "v0.1":v1["score"], "v0.2":v2["score"]}, ensure_ascii=False))

if __name__ == "__main__": main()
