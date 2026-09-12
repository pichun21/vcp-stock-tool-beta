#!/usr/bin/env python3
from __future__ import annotations
import argparse,json,statistics
from pathlib import Path
from collections import defaultdict
import pandas as pd

GRADE_W={"A":1.0,"B":.75,"C":.45,"D":.20}

def mw(m):
    if (m.get("confidence") or 0)<60:return 0
    return GRADE_W.get(m.get("grade"),0)*(.4+.6*m.get("purity",0)/100)*(.5+.5*m.get("confidence",0)/100)

def static(db):
    aliases=db["themeTaxonomy"].get("alias_to_canonical",{})
    rank=set(db["themeTaxonomy"]["rankable_index"])
    vals=defaultdict(list)
    for code,s in db["stocks"].items():
        for raw,m in s.get("themes",{}).items():
            c=aliases.get(raw,raw)
            if c in rank: vals[c].append(mw(m))
    av={c:(statistics.mean(v) if v else 0) for c,v in vals.items()}
    med=statistics.median(av.values())
    flag={c:("high-scale" if v-med>=.14 else "low-scale" if v-med<=-.14 else "balanced") for c,v in av.items()}
    return av,flag

def mean(v): return statistics.mean(v) if v else None
def med(v): return statistics.median(v) if v else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--theme-db",required=True)
    ap.add_argument("--daily",required=True)
    ap.add_argument("--cache-dir",required=True)
    ap.add_argument("--out-dir",default="alpha22_output")
    args=ap.parse_args()
    db=json.loads(Path(args.theme_db).read_text(encoding="utf-8"))
    daily=json.loads(Path(args.daily).read_text(encoding="utf-8"))
    sw,flags=static(db)
    prices={}
    for p in Path(args.cache_dir).glob("*.csv"):
        try: prices[p.stem]=pd.read_csv(p,parse_dates=["Date"]).set_index("Date").sort_index()
        except: pass
    horizons=(1,3,5,10)

    def stock_ret(code,date,h):
        df=prices.get(code); ts=pd.Timestamp(date)
        if df is None or ts not in df.index:return None
        loc=df.index.get_loc(ts)
        if not isinstance(loc,int) or loc+h>=len(df):return None
        p0=float(df.iloc[loc]["Close"]); ph=float(df.iloc[loc+h]["Close"])
        return (ph/p0-1)*100

    def theme_ret(codes,date,h):
        vals=[stock_ret(c,date,h) for c in set(codes)]
        vals=[v for v in vals if v is not None]
        return mean(vals) if vals else None

    obs=[]; pairs=[]
    for day in daily:
        date=day["date"]
        tmap={x["theme"]:x for x in day.get("themes",[])}
        gates={x["theme"]:x for x in day.get("themeGateDiagnostics",[]) if x.get("eligible")}
        top=[x["theme"] for x in day.get("themeTop5",[])]
        for rank,theme in enumerate(top,1):
            if theme not in gates or theme not in tmap: continue
            sigcodes=set(gates[theme].get("activeMarketCodes",[]))
            row={"date":date,"theme":theme,"rank":rank,"scale_flag":flags.get(theme),"static_weight_per_member":round(sw.get(theme,0),4)}
            for h in horizons: row[f"ret{h}"]=theme_ret(sigcodes,date,h)
            obs.append(row)

            candidates=[]
            for ctl,g in gates.items():
                if ctl in top or ctl not in tmap: continue
                ctlcodes=set(g.get("activeMarketCodes",[]))
                union=sigcodes|ctlcodes
                overlap=len(sigcodes&ctlcodes)/len(union) if union else 0
                if overlap>.30: continue
                # Match static scale first; constituent count and setup second.
                dist=(abs(sw.get(theme,0)-sw.get(ctl,0))*4
                      +abs(len(sigcodes)-len(ctlcodes))*.08
                      +abs(tmap[theme].get("setup",0)-tmap[ctl].get("setup",0))*.02)
                candidates.append((dist,ctl,ctlcodes,overlap))
            if not candidates: continue
            candidates.sort(key=lambda x:x[0])
            dist,ctl,ctlcodes,overlap=candidates[0]
            pr={"date":date,"signalTheme":theme,"controlTheme":ctl,"signalScale":flags.get(theme),
                "controlScale":flags.get(ctl),"matchDistance":round(dist,3),"overlap":round(overlap,3)}
            for h in horizons:
                sr=theme_ret(sigcodes,date,h); cr=theme_ret(ctlcodes,date,h)
                pr[f"signalRet{h}"]=sr; pr[f"controlRet{h}"]=cr
                pr[f"diff{h}"]=(sr-cr) if sr is not None and cr is not None else None
            pairs.append(pr)

    summary={}
    for h in horizons:
        vals=[x[f"ret{h}"] for x in obs if x[f"ret{h}"] is not None]
        dif=[x[f"diff{h}"] for x in pairs if x[f"diff{h}"] is not None]
        summary[str(h)]={
            "top5_n":len(vals),"top5_avg_return_pct":round(mean(vals),2) if vals else None,
            "top5_median_return_pct":round(med(vals),2) if vals else None,
            "top5_positive_pct":round(sum(v>0 for v in vals)/len(vals)*100,1) if vals else None,
            "matched_n":len(dif),"matched_avg_excess_pct":round(mean(dif),2) if dif else None,
            "matched_median_excess_pct":round(med(dif),2) if dif else None,
            "matched_win_pct":round(sum(v>0 for v in dif)/len(dif)*100,1) if dif else None
        }
    by_scale={}
    for flag in ("high-scale","balanced","low-scale"):
        rr=[x for x in obs if x["scale_flag"]==flag]
        by_scale[flag]={}
        for h in horizons:
            v=[x[f"ret{h}"] for x in rr if x[f"ret{h}"] is not None]
            by_scale[flag][str(h)]={"n":len(v),"avgReturnPct":round(mean(v),2) if v else None}

    result={"version":"Alpha22-v0.1","days":len(daily),"horizons":horizons,
            "summary":summary,"by_scale":by_scale,"observations":obs,"matched_pairs":pairs,
            "decision_rule":"Do not change scores unless matched excess is weak/negative while high-scale themes still dominate selection over a sufficiently large sample.",
            "formula_changed":False}
    out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"alpha22_forward_validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    lines=["# Alpha22 Theme Top5 Forward Validation","",f"- Historical days: {len(daily)}","",
           "| Horizon | Top5 N | Avg return | Positive | Matched N | Avg excess vs control | Win rate |",
           "|---|---:|---:|---:|---:|---:|---:|"]
    for h in horizons:
        x=summary[str(h)]
        fmt=lambda v:"-" if v is None else f"{v:.2f}%"
        lines.append(f"| +{h} | {x['top5_n']} | {fmt(x['top5_avg_return_pct'])} | {fmt(x['top5_positive_pct'])} | {x['matched_n']} | {fmt(x['matched_avg_excess_pct'])} | {fmt(x['matched_win_pct'])} |")
    lines += ["","## Scale groups"]
    for f,z in by_scale.items():
        lines.append(f"- {f}: "+", ".join(f"+{h} {z[str(h)]['avgReturnPct']}% (n={z[str(h)]['n']})" for h in horizons))
    lines += ["","## Interpretation","- Positive matched excess means Theme Top5 constituents outperformed a same-day eligible non-Top5 theme with similar static scale/size/setup.",
              "- Recent observations without enough future bars are automatically excluded per horizon.",
              "- This does not modify Heat, Setup, Purity or Confidence."]
    (out/"alpha22_forward_validation.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"summary":summary,"by_scale":by_scale},ensure_ascii=False,indent=2))

if __name__=="__main__": main()
