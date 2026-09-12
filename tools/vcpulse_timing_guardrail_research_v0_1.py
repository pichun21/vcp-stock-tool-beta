#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, math, statistics
from pathlib import Path

FEATURES = ["pre3_return","pre5_return","heat","setup","heat_minus_setup","entry_rank","constituent_count"]

def med(v):
    v=[x for x in v if x is not None]
    return statistics.median(v) if v else None

def mean(v):
    v=[x for x in v if x is not None]
    return statistics.mean(v) if v else None

def qtile(v,q):
    v=sorted(x for x in v if x is not None)
    if not v:return None
    i=(len(v)-1)*q; lo=int(math.floor(i)); hi=int(math.ceil(i))
    return v[lo] if lo==hi else v[lo]+(v[hi]-v[lo])*(i-lo)

def lagrate(rows):
    return 100*sum(r["lag"] for r in rows)/len(rows) if rows else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--event-json", required=True)
    ap.add_argument("--out-dir", default="alpha24_output")
    args=ap.parse_args()

    src=json.loads(Path(args.event_json).read_text(encoding="utf-8"))
    rows=[]
    for e in src.get("events",[]):
        r={
            "date":e.get("date"), "theme":e.get("theme"),
            "lag":1 if e.get("timingClass")=="lagging" else 0,
            "timingClass":e.get("timingClass"),
            "pre3_return":e.get("r-3"), "pre5_return":e.get("r-5"),
            "heat":e.get("heat"), "setup":e.get("setup"),
            "entry_rank":e.get("entryRank"), "constituent_count":e.get("constituents")
        }
        if r["heat"] is not None and r["setup"] is not None:
            r["heat_minus_setup"]=r["heat"]-r["setup"]
        else:r["heat_minus_setup"]=None
        rows.append(r)

    total=len(rows); lag=sum(r["lag"] for r in rows)
    baseline=100*lag/total if total else None
    diagnostics={}
    for f in FEATURES:
        valid=[r for r in rows if r.get(f) is not None]
        vals=[r[f] for r in valid]
        if not vals: continue
        p25,p50,p75=qtile(vals,.25),qtile(vals,.5),qtile(vals,.75)
        buckets=[
            ("low", [r for r in valid if r[f] <= p25]),
            ("mid_low", [r for r in valid if p25 < r[f] <= p50]),
            ("mid_high", [r for r in valid if p50 < r[f] <= p75]),
            ("high", [r for r in valid if r[f] > p75]),
        ]
        diagnostics[f]={
            "n":len(valid),"p25":p25,"median":p50,"p75":p75,
            "lag_mean":mean([r[f] for r in valid if r["lag"]]),
            "nonlag_mean":mean([r[f] for r in valid if not r["lag"]]),
            "buckets":[{"bucket":n,"n":len(b),"lagRatePct":round(lagrate(b),1) if b else None} for n,b in buckets]
        }

    # Transparent one-feature threshold search. Research only.
    candidates=[]
    for f in FEATURES:
        valid=[r for r in rows if r.get(f) is not None]
        vals=sorted(set(r[f] for r in valid))
        if len(vals)<4: continue
        cuts=sorted(set(qtile(vals,q) for q in (.2,.3,.4,.5,.6,.7,.8)))
        for cut in cuts:
            for direction in ("ge","le"):
                flagged=[r for r in valid if (r[f]>=cut if direction=="ge" else r[f]<=cut)]
                if len(flagged)<max(8,int(.08*len(valid))): continue
                caught=sum(r["lag"] for r in flagged)
                precision=caught/len(flagged) if flagged else 0
                recall=caught/lag if lag else 0
                # favor catching lagging events without flagging everything
                score=(2*precision*recall/(precision+recall)) if precision+recall else 0
                candidates.append({
                    "feature":f,"direction":direction,"threshold":round(cut,4),
                    "flaggedN":len(flagged),"caughtLagging":caught,
                    "precisionPct":round(precision*100,1),"recallPct":round(recall*100,1),
                    "f1":round(score,3)
                })
    candidates=sorted(candidates,key=lambda x:(x["f1"],x["recallPct"],x["precisionPct"]),reverse=True)[:15]

    result={
        "version":"Alpha24-v0.1",
        "events":total,"laggingEvents":lag,
        "baselineLaggingRatePct":round(baseline,1) if baseline is not None else None,
        "featureDiagnostics":diagnostics,
        "researchThresholdCandidates":candidates,
        "decisionGuardrail":[
            "Do not deploy a timing label from this sample alone.",
            "Prefer a rule that improves lagging precision materially above baseline while retaining useful recall.",
            "Validate any candidate rule on a later out-of-sample period before changing UI or ranking."
        ],
        "formula_changed":False
    }
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"alpha24_timing_guardrail.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=[
        "# Alpha24 Timing Guardrail Research","",
        f"- Events: {total}",
        f"- Lagging events: {lag}",
        f"- Baseline lagging rate: {baseline:.1f}%" if baseline is not None else "- Baseline lagging rate: -",
        "",
        "## Best transparent threshold candidates",
        "",
        "| Feature | Rule | Flagged | Lagging caught | Precision | Recall | F1 |",
        "|---|---|---:|---:|---:|---:|---:|"
    ]
    for c in candidates[:10]:
        op="≥" if c["direction"]=="ge" else "≤"
        lines.append(f"| {c['feature']} | {op} {c['threshold']} | {c['flaggedN']} | {c['caughtLagging']} | {c['precisionPct']}% | {c['recallPct']}% | {c['f1']:.3f} |")
    lines += ["","## Guardrail",
              "- Research only. No Heat/Setup/Purity/Confidence changes.",
              "- Any timing label must pass a later out-of-sample validation first."]
    (out/"alpha24_timing_guardrail.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"events":total,"lagging":lag,"baselineLaggingRatePct":baseline,
                      "topCandidates":candidates[:5]},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
