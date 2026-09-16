"""VCPulse v1.1d holdout validation — research only.

Frozen after v1.1c calibration. Tests a small preregistered candidate set on a
separate historical window. Production scanner/UI are never modified.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

RUNNER_VERSION="2.44.5"
HORIZONS=(5,10,20)
DATA_QUALITY={"invalidBaseClose":0,"invalidFutureClose":0,"invalidFutureLow":0,"invalidFutureHigh":0}
CANDIDATES={
    "regression_atr_1.00": {"priceDefinition":"regression","atrThreshold":1.00},
    "regression_atr_0.95": {"priceDefinition":"regression","atrThreshold":0.95},
    "first_vs_last_atr_1.00": {"priceDefinition":"first_vs_last","atrThreshold":1.00},
}

def _num(s): return pd.to_numeric(s,errors="coerce")

def local_turns(close):
    vals=np.asarray(close,float); p=[]
    for i in range(3,len(vals)-3):
        w=vals[i-3:i+4]
        if vals[i]==np.nanmax(w): p.append((i,"H",vals[i]))
        if vals[i]==np.nanmin(w): p.append((i,"L",vals[i]))
    q=[]
    for item in p:
        if not q or q[-1][1]!=item[1]: q.append(item)
        elif (item[1]=="H" and item[2]>q[-1][2]) or (item[1]=="L" and item[2]<q[-1][2]): q[-1]=item
    return q

def contraction_flags(seq):
    if len(seq)<2:return {"regression":False,"first_vs_last":False}
    a=np.asarray(seq,dtype=float)
    if not np.isfinite(a).all() or (a<=0).any():return {"regression":False,"first_vs_last":False}
    x=np.arange(len(a),dtype=float)
    slope=float(np.polyfit(x,a,1)[0])
    return {
        "regression":bool(slope<0 and a[-1]<a[0]),
        "first_vs_last":bool(a[-1]<=a[0]*0.70),
    }

def features(df):
    df=df.dropna(subset=["Close"]).copy()
    if len(df)<170:return None
    close=_num(df["Close"]); vol=_num(df["Volume"]).fillna(0); high=_num(df["High"]); low=_num(df["Low"])
    if close.iloc[-170:].isna().any():return None
    ma50=close.rolling(50).mean().iloc[-1]; ma150=close.rolling(150).mean().iloc[-1]
    trend=bool(close.iloc[-1]>ma50>ma150)
    drops=[]; piv=local_turns(close.values)
    for a,b in zip(piv,piv[1:]):
        if a[1]=="H" and b[1]=="L" and a[2]>0:
            pct=(a[2]-b[2])/a[2]*100
            if np.isfinite(pct) and 0<pct<95:drops.append((a[0],b[0],pct))
    seq=[x[2] for x in drops[-4:]]; two=len(seq)>=2
    flags=contraction_flags(seq)

    # Current v1.0 baseline-compatible score definition (from v1.1b)
    baseline_contracting=two and all(seq[i]<seq[i-1]*1.12 for i in range(1,len(seq)))
    recent=close.iloc[-35:]; pivot=float(recent.iloc[:-3].max()); last=float(close.iloc[-1]); prev=float(close.iloc[-2]); distance=(last/pivot-1)*100
    v20=float(vol.iloc[-20:].mean()); vprev=float(vol.iloc[-60:-20].mean()); dry=bool(vprev>0 and v20<vprev*0.85)
    breakout=last>pivot; breakout_vol=bool(v20>0 and vol.iloc[-1]>v20*1.35); today_breakout=bool(prev<=pivot and breakout and breakout_vol)
    baseline_pivot=bool(today_breakout or ((not breakout) and distance>-8))
    clear_trigger=bool(today_breakout or ((not breakout) and -5<distance<=0))
    score5=sum([trend,two,baseline_contracting,dry,baseline_pivot])

    prev_close=close.shift(1); tr=pd.concat([(high-low).abs(),(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    atr20=float(tr.rolling(20).mean().iloc[-1]); atr60=float(tr.rolling(60).mean().iloc[-1]); atr_ratio=(atr20/atr60 if atr60>0 else np.nan)
    avg_value=float((close.iloc[-20:]*vol.iloc[-20:]).mean()); liquid=bool(avg_value>=20_000_000)
    return dict(
        liquid=liquid,trend=trend,twoContractions=two,volumeDry=dry,clearTrigger=clear_trigger,
        price_regression=flags["regression"],price_first_vs_last=flags["first_vs_last"],
        atr20To60=float(atr_ratio) if np.isfinite(atr_ratio) else None,
        baseline=bool(liquid and score5>=4),score5=int(score5),distancePct=round(distance,2),avgValue20=avg_value,
        contractionSeq="|".join(f"{x:.4f}" for x in seq)
    )

def _safe_positive(v):
    try:x=float(v)
    except Exception:return None
    return x if np.isfinite(x) and x>0 else None

def add_returns(row,df,loc):
    p0=_safe_positive(df.iloc[loc].get("Close"))
    if p0 is None:
        DATA_QUALITY["invalidBaseClose"]+=1
        for h in HORIZONS:row[f"ret{h}"]=row[f"mae{h}"]=row[f"mfe{h}"]=None
        return
    for h in HORIZONS:
        row[f"ret{h}"]=row[f"mae{h}"]=row[f"mfe{h}"]=None
        if loc+h>=len(df):continue
        future=df.iloc[loc+1:loc+h+1]
        ec=_safe_positive(df.iloc[loc+h].get("Close"))
        if ec is None:DATA_QUALITY["invalidFutureClose"]+=1
        else:row[f"ret{h}"]=(ec/p0-1)*100
        lows=_num(future.get("Low",pd.Series(index=future.index,dtype=float))); lows=lows[np.isfinite(lows)&(lows>0)]
        if lows.empty:DATA_QUALITY["invalidFutureLow"]+=1
        else:row[f"mae{h}"]=(float(lows.min())/p0-1)*100
        highs=_num(future.get("High",pd.Series(index=future.index,dtype=float))); highs=highs[np.isfinite(highs)&(highs>0)]
        if highs.empty:DATA_QUALITY["invalidFutureHigh"]+=1
        else:row[f"mfe{h}"]=(float(highs.max())/p0-1)*100

def summarize(rows):
    out={"events":len(rows),"uniqueStocks":len({r["code"] for r in rows})}
    for h in HORIZONS:
        vals=[r[f"ret{h}"] for r in rows if r.get(f"ret{h}") is not None]
        maes=[r[f"mae{h}"] for r in rows if r.get(f"mae{h}") is not None]
        mfes=[r[f"mfe{h}"] for r in rows if r.get(f"mfe{h}") is not None]
        out[str(h)]={"n":len(vals),"avgReturnPct":round(float(np.mean(vals)),2) if vals else None,
                     "medianReturnPct":round(float(np.median(vals)),2) if vals else None,
                     "positivePct":round(sum(x>0 for x in vals)/len(vals)*100,1) if vals else None,
                     "avgMAEPct":round(float(np.mean(maes)),2) if maes else None,
                     "avgMFEPct":round(float(np.mean(mfes)),2) if mfes else None}
    return out

def dedupe_events(rows,date_pos):
    by={}
    for r in rows:by.setdefault(r["code"],[]).append(r)
    keep=[]
    for code,rs in by.items():
        rs=sorted(rs,key=lambda x:date_pos.get(x["date"],10**9)); prev=None
        for r in rs:
            pos=date_pos.get(r["date"])
            if prev is None or pos is None or pos!=prev+1:keep.append(r)
            prev=pos
    return keep

def candidate_qualifies(r,cfg):
    if not (r["liquid"] and r["trend"] and r["twoContractions"] and r["volumeDry"] and r["clearTrigger"]):return False
    if not r[f'price_{cfg["priceDefinition"]}']:return False
    ratio=r.get("atr20To60")
    return ratio is not None and ratio<=cfg["atrThreshold"]

def flat(name,s):
    z={"variant":name,"events":s["events"],"uniqueStocks":s["uniqueStocks"]}
    for h in HORIZONS:
        for k,v in s[str(h)].items():z[f"{h}d_{k}"]=v
    return z

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--daily",required=True);ap.add_argument("--cache-dir",required=True);ap.add_argument("--out-dir",default="v11d_holdout_output")
    args=ap.parse_args();out=Path(args.out_dir);out.mkdir(parents=True,exist_ok=True)
    print(f"VCPulse v1.1d runner {RUNNER_VERSION}")
    daily=json.loads(Path(args.daily).read_text(encoding="utf-8"));dates=[d["date"] for d in daily];date_pos={d:i for i,d in enumerate(dates)}
    prices={}
    for p in Path(args.cache_dir).glob("*.csv"):
        try:prices[p.stem]=pd.read_csv(p,parse_dates=["Date"]).set_index("Date").sort_index()
        except Exception:pass
    universe=[]
    for date0 in dates:
        ts=pd.Timestamp(date0)
        for code,df in prices.items():
            cut=df.loc[:ts]
            if cut.empty or cut.index[-1]!=ts:continue
            f=features(cut)
            if not f or not f["liquid"]:continue
            loc=df.index.get_loc(ts)
            if not isinstance(loc,(int,np.integer)):continue
            row={"date":date0,"code":code,**f};add_returns(row,df,loc);universe.append(row)

    variants={"A_current_v1_0":[r for r in universe if r["baseline"]]}
    for name,cfg in CANDIDATES.items():variants[name]=[r for r in universe if candidate_qualifies(r,cfg)]

    summary={"version":"v1.1d-holdout-validation","runnerVersion":RUNNER_VERSION,"productionChanged":False,
             "selectionFrozenFrom":"v1.1c calibration window 2025-09-10 through 2026-09-10",
             "warning":"This run is intended for a separate holdout window. Do not change candidate definitions after seeing holdout results.",
             "candidates":CANDIDATES,"dataQuality":DATA_QUALITY.copy(),"variants":{}}
    rows=[]
    for name,obs in variants.items():
        events=dedupe_events(obs,date_pos); s=summarize(events);summary["variants"][name]=s;rows.append(flat(name,s))
        pd.DataFrame(events).to_csv(out/f"{name}_events.csv",index=False)
    pd.DataFrame(rows).to_csv(out/"holdout_summary.csv",index=False)
    (out/"v11d_holdout_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    print(pd.DataFrame(rows).to_string(index=False))
    print(json.dumps({"runnerVersion":RUNNER_VERSION,"dataQuality":DATA_QUALITY},ensure_ascii=False))

if __name__=="__main__":main()
