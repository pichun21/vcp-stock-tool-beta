#!/usr/bin/env python3
import argparse, json, math
from pathlib import Path
import pandas as pd

def load_prices(cache_dir):
    out={}
    for p in Path(cache_dir).glob("*.csv"):
        try:
            df=pd.read_csv(p,parse_dates=["Date"]).set_index("Date").sort_index()
            out[p.stem]=df
        except Exception:
            pass
    return out

def basket_return(codes, prices, d, horizon):
    vals=[]
    dt=pd.Timestamp(d)
    for c in codes:
        df=prices.get(c)
        if df is None or df.empty or dt not in df.index: continue
        loc=df.index.get_loc(dt)
        if not isinstance(loc,(int,)): continue
        j=loc+horizon
        if j>=len(df): continue
        p0=float(df["Close"].iloc[loc]); p1=float(df["Close"].iloc[j])
        if p0>0: vals.append((p1/p0-1)*100)
    return sum(vals)/len(vals) if vals else None

def avg(xs):
    xs=[x for x in xs if x is not None]
    return sum(xs)/len(xs) if xs else None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--daily",required=True)
    ap.add_argument("--theme-db",required=True)
    ap.add_argument("--cache-dir",required=True)
    ap.add_argument("--out-dir",required=True)
    ap.add_argument("--theme",default="AI眼鏡")
    args=ap.parse_args()

    daily=json.loads(Path(args.daily).read_text(encoding="utf-8"))
    db=json.loads(Path(args.theme_db).read_text(encoding="utf-8"))
    prices=load_prices(args.cache_dir)
    theme=args.theme
    amap=db["themeTaxonomy"]["alias_to_canonical"]
    codes=[]
    for code,s in db["stocks"].items():
        if any(amap.get(raw)==theme for raw in s.get("themes",{})):
            codes.append(code)

    rows=[]; prev_in=False
    all_themes=set()
    for day in daily:
        for x in day.get("themes",[]): all_themes.add(x["theme"])
    for day in daily:
        ranked=sorted(day.get("themes",[]),key=lambda x:x["heat"],reverse=True)
        rank=next((i+1 for i,x in enumerate(ranked) if x["theme"]==theme),None)
        top5=rank is not None and rank<=5
        fresh=top5 and not prev_in
        rec=next((x for x in ranked if x["theme"]==theme),None)
        if top5:
            row={"date":day["date"],"rank":rank,"freshEntry":fresh,
                 "heat":rec.get("heat") if rec else None,"setup":rec.get("setup") if rec else None}
            for h in (1,3,5,10):
                row[f"ret{h}"]=basket_return(codes,prices,day["date"],h)
                controls=[]
                # matched control = other eligible themes on same day, excluding shadow theme
                for x in ranked:
                    if x["theme"]==theme: continue
                    cc=[]
                    for code,s in db["stocks"].items():
                        if any(amap.get(raw)==x["theme"] for raw in s.get("themes",{})): cc.append(code)
                    r=basket_return(cc,prices,day["date"],h)
                    if r is not None: controls.append(r)
                ctrl=avg(controls)
                row[f"control{h}"]=ctrl
                row[f"excess{h}"]=(row[f"ret{h}"]-ctrl) if row[f"ret{h}"] is not None and ctrl is not None else None
            rows.append(row)
        prev_in=top5

    fresh=[r for r in rows if r["freshEntry"]]
    summary={
      "theme":theme,
      "tradingDays":len(daily),
      "themeConstituents":codes,
      "top5Days":len(rows),
      "top5Frequency":round(len(rows)/len(daily),4) if daily else 0,
      "freshEntryEvents":len(fresh),
      "avgTop5Rank":round(avg([r["rank"] for r in rows]),3) if rows else None,
      "freshEntryForwardReturns":{},
      "freshEntryMatchedExcess":{},
      "decision":"WAIT_MORE_HISTORY"
    }
    for h in (1,3,5,10):
        rr=[r[f"ret{h}"] for r in fresh if r[f"ret{h}"] is not None]
        ee=[r[f"excess{h}"] for r in fresh if r[f"excess{h}"] is not None]
        summary["freshEntryForwardReturns"][f"+{h}"]={
            "n":len(rr),"avgPct":round(avg(rr),3) if rr else None,
            "positiveRate":round(sum(x>0 for x in rr)/len(rr),4) if rr else None
        }
        summary["freshEntryMatchedExcess"][f"+{h}"]={
            "n":len(ee),"avgPct":round(avg(ee),3) if ee else None,
            "winRate":round(sum(x>0 for x in ee)/len(ee),4) if ee else None
        }

    # Conservative gate: enough fresh events + no obvious redundancy + positive medium-term behavior.
    if len(fresh)>=8:
        r5=summary["freshEntryForwardReturns"]["+5"]["avgPct"]
        r10=summary["freshEntryForwardReturns"]["+10"]["avgPct"]
        e10=summary["freshEntryMatchedExcess"]["+10"]["avgPct"]
        if r5 is not None and r10 is not None and r5>0 and r10>0 and e10 is not None and e10>=0:
            summary["decision"]="PROMOTION_REVIEW_READY"
        else:
            summary["decision"]="KEEP_SHADOW_RESEARCH"
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"alpha34_ai_glasses_shadow_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"alpha34_ai_glasses_shadow_events.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
