from __future__ import annotations
import argparse,json,math
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

H=(1,3,5,10,20)
VIEWS=("heat_top1","setup_top1","heat_top5","setup_top5")
MODES=("GLOBAL_MAX","AI_PCB_BREADTH25","AI_PCB_CURRENT_REFERENCE")

def loadj(p): return json.loads(Path(p).read_text(encoding="utf-8"))

def norm_price(p):
    d=pd.read_csv(p)
    cc="Close" if "Close" in d.columns else "close"
    d["Date"]=pd.to_datetime(d["Date"]); d[cc]=pd.to_numeric(d[cc],errors="coerce")
    return d.dropna(subset=["Date",cc]).drop_duplicates("Date").sort_values("Date").set_index("Date")[[cc]].rename(columns={cc:"Close"})

def members(db):
    amap=db["themeTaxonomy"]["alias_to_canonical"]; o=defaultdict(set)
    for code,s in db["stocks"].items():
        for raw,meta in s.get("themes",{}).items():
            can=amap.get(raw)
            if can and float(meta.get("confidence",0) or 0)>=60: o[can].add(str(code))
    return {k:sorted(v) for k,v in o.items()}

def extract(day,v):
    arr=day.get("themeTop5",[]) if v.startswith("heat") else day.get("setupTop5",[])
    if v.endswith("top1"): arr=arr[:1]
    return [x["theme"] for x in arr]

def theme_ret(theme,codes,date,prices,h):
    d0=pd.Timestamp(date); vals=[]
    for c in codes:
        x=prices.get(c)
        if x is None or d0 not in x.index: continue
        pos=x.index.get_indexer([d0])[0]
        if pos<0 or pos+h>=len(x): continue
        p0=float(x.iloc[pos]["Close"]); p1=float(x.iloc[pos+h]["Close"])
        if p0>0 and np.isfinite(p0) and np.isfinite(p1): vals.append((p1/p0-1)*100)
    return float(np.mean(vals)) if vals else None

def st(xs):
    a=np.array([x for x in xs if x is not None and np.isfinite(x)],float)
    return {"n":int(len(a)),"mean":round(float(a.mean()),6) if len(a) else None,
            "median":round(float(np.median(a)),6) if len(a) else None,
            "positive_rate":round(float((a>0).mean()*100),4) if len(a) else None}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--theme-db",required=True)
    ap.add_argument("--max",required=True)
    ap.add_argument("--breadth25",required=True)
    ap.add_argument("--reference",required=True)
    ap.add_argument("--price-cache",required=True)
    ap.add_argument("--benchmark-file",required=True)
    ap.add_argument("--out-dir",default="alpha133_result")
    a=ap.parse_args()

    db=loadj(a.theme_db); mem=members(db)
    daily={
      "GLOBAL_MAX":loadj(a.max),
      "AI_PCB_BREADTH25":loadj(a.breadth25),
      "AI_PCB_CURRENT_REFERENCE":loadj(a.reference)
    }
    md={m:{x["date"]:x for x in arr} for m,arr in daily.items()}
    dates=sorted(set.intersection(*[set(x) for x in md.values()]))

    cache=Path(a.price_cache); prices={}
    for c in db["stocks"]:
        p=cache/f"{c}.csv"
        if p.exists():
            try: prices[str(c)]=norm_price(p)
            except Exception: pass
    bench=norm_price(a.benchmark_file)

    rows=[]
    for date in dates:
        d0=pd.Timestamp(date)
        # benchmark regime by each horizon (same convention as Alpha131)
        for view in VIEWS:
            selected={m:extract(md[m][date],view) for m in MODES}
            for rank in range(1,6 if view.endswith("top5") else 2):
                themes={m:(selected[m][rank-1] if len(selected[m])>=rank else None) for m in MODES}
                for h in H:
                    br=None
                    if d0 in bench.index:
                        pos=bench.index.get_indexer([d0])[0]
                        if pos>=0 and pos+h<len(bench):
                            p0=float(bench.iloc[pos]["Close"]); p1=float(bench.iloc[pos+h]["Close"])
                            br=(p1/p0-1)*100 if p0 else None
                    rr={m:(theme_ret(themes[m],mem.get(themes[m],[]),date,prices,h) if themes[m] else None) for m in MODES}
                    if rr["GLOBAL_MAX"] is None: continue
                    for mode in MODES:
                        if rr[mode] is None: continue
                        rows.append({
                          "date":date,"view":view,"rank":rank,"horizon":h,"mode":mode,
                          "theme":themes[mode],"return":rr[mode],"benchmark_return":br,
                          "regime":"TAIEX_UP" if br is not None and br>0 else ("TAIEX_DOWN" if br is not None and br<0 else "TAIEX_FLAT")
                        })

    r=pd.DataFrame(rows)
    idxcols=["date","view","rank","horizon"]
    mx=r[r["mode"]=="GLOBAL_MAX"].rename(columns={"theme":"theme_max","return":"return_max","regime":"regime_max"})
    summary={}
    comparisons={}
    for mode in ("AI_PCB_BREADTH25","AI_PCB_CURRENT_REFERENCE"):
        z=mx[idxcols+["theme_max","return_max","regime_max"]].merge(
            r[r["mode"]==mode][idxcols+["theme","return"]],on=idxcols,how="inner")
        z["delta"]=z["return"]-z["return_max"]
        z["changed"]=z["theme"]!=z["theme_max"]
        comparisons[mode]=z

        sm={}
        for view in VIEWS:
            sm[view]={}
            for h in H:
                q=z[(z["view"]==view)&(z["horizon"]==h)]
                sm[view][str(h)]={
                    "all":st(q["delta"]),
                    "changed_only":st(q.loc[q["changed"],"delta"]),
                    "TAIEX_UP":st(q.loc[q["regime_max"]=="TAIEX_UP","delta"]),
                    "TAIEX_UP_changed":st(q.loc[(q["regime_max"]=="TAIEX_UP")&q["changed"],"delta"])
                }
        summary[mode]=sm

    # Pre-declared promotion gate for BREADTH25 only:
    # Must improve MAX on Heat Top1 bull 10D and 20D, while not degrading overall Setup Top1 10D/20D.
    checks=[]
    s=summary["AI_PCB_BREADTH25"]
    for h in ("10","20"):
        x=s["heat_top1"][h]["TAIEX_UP"]
        checks.append({"check":f"heat_top1_{h}D_TAIEX_UP_positive_vs_MAX","pass":x["mean"] is not None and x["mean"]>0,"value":x})
        y=s["setup_top1"][h]["all"]
        checks.append({"check":f"setup_top1_{h}D_overall_nonnegative_vs_MAX","pass":y["mean"] is not None and y["mean"]>=0,"value":y})
    gate="PASS" if all(x["pass"] for x in checks) else "HOLD"

    report={
      "schema":"vcpulse-alpha133-ai-pcb-breadth-validation",
      "days":len(dates),"first_date":dates[0] if dates else None,"last_date":dates[-1] if dates else None,
      "price_files_loaded":len(prices),"benchmark_loaded":not bench.empty,
      "candidate":"AI_PCB_BREADTH25","reference_only":"AI_PCB_CURRENT_REFERENCE",
      "gate":gate,"checks":checks,"summary_vs_global_max":summary,
      "production":"UNCHANGED"
    }
    out=Path(a.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"alpha133_ai_pcb_breadth_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    for mode,z in comparisons.items():
        z.to_csv(out/f"alpha133_{mode.lower()}_vs_max.csv",index=False,encoding="utf-8-sig")
    lines=["# VCPulse Alpha133 — AI PCB Breadth Validation","",
           f"- Candidate: **AI_PCB_BREADTH25**",
           f"- Diagnostic upper reference: **AI_PCB_CURRENT_REFERENCE**",
           f"- Gate: **{gate}**",
           f"- Days: **{report['days']}**",
           f"- Price files: **{report['price_files_loaded']}**",
           f"- Benchmark loaded: **{report['benchmark_loaded']}**",
           "- Production: **UNCHANGED**","",
           "## Promotion checks",""]
    for c in checks:
        lines.append(f"- {'PASS' if c['pass'] else 'HOLD'} — {c['check']}: n={c['value']['n']}, mean delta={c['value']['mean']}%")
    (out/"alpha133_ai_pcb_breadth_validation.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"gate":gate,"checks":checks,"days":len(dates)},ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
