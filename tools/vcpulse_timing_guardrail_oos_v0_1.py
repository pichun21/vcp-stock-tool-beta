#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,statistics
from pathlib import Path

RULES={"A_extension_warning":3.23,"B_chase_caution":1.62}

def metrics(events,thr):
    usable=[e for e in events if e.get("r-3") is not None]
    flagged=[e for e in usable if e["r-3"]>=thr]
    lag=[e for e in usable if e.get("timingClass")=="lagging"]
    caught=[e for e in flagged if e.get("timingClass")=="lagging"]
    precision=len(caught)/len(flagged) if flagged else None
    recall=len(caught)/len(lag) if lag else None
    base=len(lag)/len(usable) if usable else None
    return {
        "thresholdPct":thr,"usableN":len(usable),"flaggedN":len(flagged),
        "laggingN":len(lag),"caughtLaggingN":len(caught),
        "baselineLaggingRatePct":round(base*100,1) if base is not None else None,
        "precisionPct":round(precision*100,1) if precision is not None else None,
        "recallPct":round(recall*100,1) if recall is not None else None,
        "liftVsBaseline":round(precision/base,2) if precision is not None and base else None
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--event-json",required=True)
    ap.add_argument("--oos-start",default="2026-09-12")
    ap.add_argument("--out-dir",default="alpha25_output")
    args=ap.parse_args()
    src=json.loads(Path(args.event_json).read_text(encoding="utf-8"))
    events=[e for e in src.get("events",[]) if e.get("date","")>=args.oos_start]
    results={k:metrics(events,v) for k,v in RULES.items()}
    # Conservative status: sample adequacy is separate from performance.
    usable=sum(e.get("r-3") is not None for e in events)
    lag=sum(e.get("r-3") is not None and e.get("timingClass")=="lagging" for e in events)
    if usable<40 or lag<5:
        decision="WAIT_MORE_OOS_DATA"
    else:
        a=results["A_extension_warning"]
        decision="OOS_SUPPORT" if (a["liftVsBaseline"] or 0)>=2 and (a["recallPct"] or 0)>=50 else "OOS_NOT_CONFIRMED"
    outdata={
        "version":"Alpha25-v0.1","oosStart":args.oos_start,
        "oosEvents":len(events),"usableEvents":usable,"laggingEvents":lag,
        "frozenRules":RULES,"results":results,"decision":decision,
        "guardrails":[
            "Thresholds are frozen from Alpha24 and are not optimized here.",
            "WAIT_MORE_OOS_DATA if fewer than 40 usable fresh-entry events or fewer than 5 lagging events.",
            "No production/UI deployment from an underpowered OOS sample."
        ],
        "formula_changed":False
    }
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"alpha25_oos_timing_validation.json").write_text(json.dumps(outdata,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Alpha25 Timing Guardrail OOS Validation","",
           f"- OOS start: {args.oos_start}",f"- OOS fresh-entry events: {len(events)}",
           f"- Usable events: {usable}",f"- Lagging events: {lag}",f"- Decision: **{decision}**","",
           "| Frozen rule | Threshold | Flagged | Caught lagging | Precision | Recall | Lift |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for k,x in results.items():
        fmt=lambda v:"-" if v is None else str(v)
        lines.append(f"| {k} | pre3 ≥ {x['thresholdPct']}% | {x['flaggedN']} | {x['caughtLaggingN']} | {fmt(x['precisionPct'])}% | {fmt(x['recallPct'])}% | {fmt(x['liftVsBaseline'])}x |")
    lines += ["","## Rule","- Do not retune 3.23% or 1.62% from these OOS results.",
              "- If sample is insufficient, keep collecting future observations rather than extending backward into the development period."]
    (out/"alpha25_oos_timing_validation.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps(outdata,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
