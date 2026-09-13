from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS=[1,3,5,10,20]
VIEWS=["heat_top1","setup_top1","heat_top5","setup_top5"]

def stats(x):
    x=pd.Series(x).dropna().astype(float)
    if len(x)==0: return {"n":0,"mean_delta":None,"median_delta":None,"positive_rate":None}
    return {
        "n":int(len(x)),
        "mean_delta":round(float(x.mean()),6),
        "median_delta":round(float(x.median()),6),
        "positive_rate":round(float((x>0).mean()*100),4),
    }

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--observations",required=True)
    ap.add_argument("--out-dir",default="alpha131_max_gate")
    args=ap.parse_args()

    d=pd.read_csv(args.observations)
    d["date"]=pd.to_datetime(d["date"])
    d["month"]=d["date"].dt.strftime("%Y-%m")

    c=d[d["mode"]=="CONTROL_current"].copy()
    m=d[d["mode"]=="DEDUP_max"].copy()
    keys=["date","view","rank","horizon"]
    z=c.merge(m,on=keys,suffixes=("_control","_max"))
    z=z[z["return_control"].notna() & z["return_max"].notna()].copy()
    z["delta"]=z["return_max"]-z["return_control"]
    z["excess_delta"]=z["excess_return_max"]-z["excess_return_control"]
    z["changed_theme"]=z["theme_control"]!=z["theme_max"]
    z["month"]=z["date"].dt.strftime("%Y-%m")

    # Regime is defined only from contemporaneous benchmark forward return already in Alpha130.
    # This is descriptive, not used to tune the signal.
    z["regime"]=np.where(z["benchmark_return_control"]>0,"TAIEX_UP",
                  np.where(z["benchmark_return_control"]<0,"TAIEX_DOWN","TAIEX_FLAT"))

    overall={}
    monthly={}
    regimes={}
    changed_only={}
    for view in VIEWS:
        overall[view]={}
        monthly[view]={}
        regimes[view]={}
        changed_only[view]={}
        for h in HORIZONS:
            q=z[(z["view"]==view)&(z["horizon"]==h)]
            overall[view][str(h)]=stats(q["delta"])
            monthly[view][str(h)]={mo:stats(g["delta"]) for mo,g in q.groupby("month")}
            regimes[view][str(h)]={rg:stats(g["delta"]) for rg,g in q.groupby("regime")}
            changed_only[view][str(h)]=stats(q.loc[q["changed_theme"],"delta"])

    # Promotion evidence gate: no arbitrary return threshold.
    # Require direction consistency on the decision-relevant 10D/20D Top1 slices:
    # (a) overall MAX delta non-negative; (b) no TAIEX_UP/DOWN regime has negative mean
    # with >=10 matched observations; (c) changed-theme subset is not negative overall.
    checks=[]
    for view in ["heat_top1","setup_top1"]:
        for h in [10,20]:
            q=z[(z["view"]==view)&(z["horizon"]==h)]
            ov=stats(q["delta"])
            checks.append({"check":f"{view}_{h}D_overall_nonnegative","pass":ov["mean_delta"] is not None and ov["mean_delta"]>=0,"value":ov})
            for rg,g in q.groupby("regime"):
                st=stats(g["delta"])
                if st["n"]>=10:
                    checks.append({"check":f"{view}_{h}D_{rg}_nonnegative_n10","pass":st["mean_delta"]>=0,"value":st})
            ch=stats(q.loc[q["changed_theme"],"delta"])
            if ch["n"]>=5:
                checks.append({"check":f"{view}_{h}D_changed_theme_nonnegative_n5","pass":ch["mean_delta"]>=0,"value":ch})

    passed=sum(bool(x["pass"]) for x in checks)
    gate="PASS" if checks and passed==len(checks) else "HOLD"
    report={
        "schema":"vcpulse-alpha131-max-promotion-gate",
        "source":"Alpha130 matched return observations",
        "production":"UNCHANGED",
        "candidate":"DEDUP_max",
        "matched_rows":int(len(z)),
        "theme_changed_rows":int(z["changed_theme"].sum()),
        "gate":gate,
        "checks_passed":passed,
        "checks_total":len(checks),
        "checks":checks,
        "overall":overall,
        "monthly":monthly,
        "benchmark_regimes":regimes,
        "changed_theme_only":changed_only,
    }

    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"alpha131_max_promotion_gate.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    z.to_csv(out/"alpha131_control_vs_max_matched.csv",index=False)

    lines=[
        "# VCPulse Alpha131 — MAX Promotion Gate","",
        f"- Candidate: **DEDUP_max**",
        f"- Matched rows: **{len(z)}**",
        f"- Rows where CONTROL/MAX theme differs: **{int(z['changed_theme'].sum())}**",
        f"- Gate: **{gate}** ({passed}/{len(checks)} checks passed)",
        "- Production: **UNCHANGED**","",
        "## Decision checks",""
    ]
    for x in checks:
        st=x["value"]
        lines.append(f"- {'PASS' if x['pass'] else 'HOLD'} — {x['check']}: n={st['n']}, mean delta={st['mean_delta']}%")
    lines += ["","## Interpretation","",
              "This gate does not optimize a new parameter. It tests whether MAX remains directionally stable versus CONTROL in the decision-relevant 10D/20D Top1 slices, across TAIEX up/down regimes and on dates where de-duplication actually changes the selected theme.",
              "",
              "A HOLD result means keep MAX as research candidate and do not promote Production."]
    (out/"alpha131_max_promotion_gate.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"gate":gate,"checks":f"{passed}/{len(checks)}","matched_rows":len(z)},ensure_ascii=False))

if __name__=="__main__":
    main()
