"""VCPulse v1.1b ablation validation — research only.

Purpose:
1) Measure the sequential funnel from the current A baseline into the strict v1.1 candidate.
2) Run leave-one-condition-out ablation to identify which rule is the main coverage bottleneck.
3) Report both observation-level and event-deduplicated forward outcomes.

Production scanner/UI are never modified. Thresholds are frozen; this runner only measures them.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS=(5,10,20)
DATA_QUALITY={"invalidBaseClose":0,"invalidFutureClose":0,"invalidFutureLow":0,"invalidFutureHigh":0}
CONDS=["trend","twoContractions","priceContracting","volumeDry","atrContracting","clearTrigger"]
LABELS={
 "trend":"Trend: close > MA50 > MA150",
 "twoContractions":">=2 contractions",
 "priceContracting":"Price contractions shrink",
 "volumeDry":"Volume dry-up",
 "atrContracting":"ATR20/ATR60 <= 0.85",
 "clearTrigger":"Clear Pivot trigger",
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
    contracting=two and all(seq[i]<seq[i-1]*1.12 for i in range(1,len(seq)))
    recent=close.iloc[-35:]; pivot=float(recent.iloc[:-3].max()); last=float(close.iloc[-1]); prev=float(close.iloc[-2]); distance=(last/pivot-1)*100
    v20=float(vol.iloc[-20:].mean()); vprev=float(vol.iloc[-60:-20].mean()); dry=bool(vprev>0 and v20<vprev*0.85)
    breakout=last>pivot; breakout_vol=bool(v20>0 and vol.iloc[-1]>v20*1.35); today_breakout=bool(prev<=pivot and breakout and breakout_vol)
    pivot_condition=bool(today_breakout or ((not breakout) and distance>-8))
    score=sum([trend,two,contracting,dry,pivot_condition])
    prev_close=close.shift(1); tr=pd.concat([(high-low).abs(),(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    atr20=float(tr.rolling(20).mean().iloc[-1]); atr60=float(tr.rolling(60).mean().iloc[-1]); atr_contract=bool(atr60>0 and atr20/atr60<=0.85)
    avg_value=float((close.iloc[-20:]*vol.iloc[-20:]).mean()); clear_trigger=bool(today_breakout or ((not breakout) and -5<distance<=0))
    baseline=bool(avg_value>=20_000_000 and score>=4)
    return dict(trend=trend,twoContractions=two,priceContracting=contracting,volumeDry=dry,atrContracting=atr_contract,
                clearTrigger=clear_trigger,score5=int(score),baseline=baseline,liquid=avg_value>=20_000_000,
                atr20To60=round(atr20/atr60,4) if atr60>0 else None,distancePct=round(distance,2),avgValue20=avg_value)

def add_returns(row,df,loc):
    p0=pd.to_numeric(pd.Series([df.iloc[loc].get("Close")]),errors="coerce").iloc[0]
    if not np.isfinite(p0) or p0<=0:
        DATA_QUALITY["invalidBaseClose"]+=1
        for h in HORIZONS: row[f"ret{h}"]=row[f"mae{h}"]=row[f"mfe{h}"]=None
        return
    p0=float(p0)
    for h in HORIZONS:
        if loc+h>=len(df):
            row[f"ret{h}"]=row[f"mae{h}"]=row[f"mfe{h}"]=None
            continue
        future=df.iloc[loc+1:loc+h+1]
        end_close=pd.to_numeric(pd.Series([df.iloc[loc+h].get("Close")]),errors="coerce").iloc[0]
        lows=_num(future["Low"]); lows=lows[np.isfinite(lows) & (lows>0)]
        highs=_num(future["High"]); highs=highs[np.isfinite(highs) & (highs>0)]
        if not np.isfinite(end_close) or end_close<=0:
            DATA_QUALITY["invalidFutureClose"]+=1; row[f"ret{h}"]=None
        else: row[f"ret{h}"]=(float(end_close)/p0-1)*100
        if lows.empty:
            DATA_QUALITY["invalidFutureLow"]+=1; row[f"mae{h}"]=None
        else: row[f"mae{h}"]=(float(lows.min())/p0-1)*100
        if highs.empty:
            DATA_QUALITY["invalidFutureHigh"]+=1; row[f"mfe{h}"]=None
        else: row[f"mfe{h}"]=(float(highs.max())/p0-1)*100

def summarize(rows):
    out={"observations":len(rows),"uniqueStocks":len({r["code"] for r in rows})}
    for h in HORIZONS:
        v=[r for r in rows if r.get(f"ret{h}") is not None]
        vals=[r[f"ret{h}"] for r in v]; maes=[r[f"mae{h}"] for r in v if r.get(f"mae{h}") is not None]; mfes=[r[f"mfe{h}"] for r in v if r.get(f"mfe{h}") is not None]
        out[str(h)]={"n":len(vals),"avgReturnPct":round(float(np.mean(vals)),2) if vals else None,"medianReturnPct":round(float(np.median(vals)),2) if vals else None,
                     "positivePct":round(sum(x>0 for x in vals)/len(vals)*100,1) if vals else None,"avgMAEPct":round(float(np.mean(maes)),2) if maes else None,"avgMFEPct":round(float(np.mean(mfes)),2) if mfes else None}
    return out

def dedupe_events(rows,date_pos):
    # Consecutive qualifying trading dates for the same stock are one event; keep first signal only.
    by={}
    for r in rows: by.setdefault(r["code"],[]).append(r)
    keep=[]
    for code,rs in by.items():
        rs=sorted(rs,key=lambda x:date_pos.get(x["date"],10**9)); prev=None
        for r in rs:
            pos=date_pos.get(r["date"])
            if prev is None or pos is None or pos!=prev+1: keep.append(r)
            prev=pos
    return keep

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--daily",required=True); ap.add_argument("--cache-dir",required=True); ap.add_argument("--out-dir",default="v11b_ablation_output")
    args=ap.parse_args(); out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    daily=json.loads(Path(args.daily).read_text(encoding="utf-8")); dates=[d["date"] for d in daily]; date_pos={d:i for i,d in enumerate(dates)}
    prices={}
    for p in Path(args.cache_dir).glob("*.csv"):
        try: prices[p.stem]=pd.read_csv(p,parse_dates=["Date"]).set_index("Date").sort_index()
        except Exception: pass
    universe=[]
    for date0 in dates:
        ts=pd.Timestamp(date0)
        for code,df in prices.items():
            cut=df.loc[:ts]
            if cut.empty or cut.index[-1]!=ts: continue
            f=features(cut)
            if not f or not f["liquid"]: continue
            loc=df.index.get_loc(ts)
            if not isinstance(loc,(int,np.integer)): continue
            row={"date":date0,"code":code,**f}; add_returns(row,df,loc); universe.append(row)

    baseline=[r for r in universe if r["baseline"]]
    # Sequential funnel starts at A baseline to answer what shrinks 2,378 observations to the strict set.
    funnel=[]; current=baseline
    funnel.append({"stage":"A baseline","condition":None,**summarize(current)})
    for c in CONDS:
        before=len(current); current=[r for r in current if r[c]]
        funnel.append({"stage":LABELS[c],"condition":c,"before":before,"after":len(current),"retentionPct":round(len(current)/before*100,1) if before else None,**summarize(current)})
    strict=current

    variants={"A_baseline":baseline,"B_full":strict}
    # Leave-one-out: all strict conditions except one, within the same liquid universe.
    for omit in CONDS:
        variants[f"minus_{omit}"]=[r for r in universe if all(r[c] for c in CONDS if c!=omit)]
    summary={"version":"v1.1b-ablation-research","productionChanged":False,"thresholdsOptimized":False,
             "eventDedupRule":"For each stock, consecutive qualifying dates in the historical trading-date sequence are one event; keep the first date.",
             "dataQuality":DATA_QUALITY.copy(),
             "conditionOrder":[{"key":c,"label":LABELS[c]} for c in CONDS],"funnel":funnel,"variants":{}}
    for name,rows in variants.items():
        ev=dedupe_events(rows,date_pos)
        summary["variants"][name]={"observationLevel":summarize(rows),"eventDeduped":summarize(ev)}
        pd.DataFrame(rows).to_csv(out/f"{name}_observations.csv",index=False)
        pd.DataFrame(ev).to_csv(out/f"{name}_events_deduped.csv",index=False)
    (out/"v11b_ablation_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    pd.DataFrame(funnel).to_csv(out/"funnel.csv",index=False)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__": main()
