"""VCPulse v1.1 candidate A/B validation (research only).

A = current formal VCP baseline used by frozen historical scanner:
    liquidity >= 20m TWD average value, score >= 4/5.
B = frozen v1.1 hypothesis inspired by the four core ideas:
    trend background + price contraction + volume dry-up + volatility contraction,
    then a clear pivot trigger (near pivot or volume-confirmed breakout).

This script does NOT modify production scanner/UI and does NOT optimize thresholds.
"""
from __future__ import annotations
import argparse, json, math
from pathlib import Path
import numpy as np
import pandas as pd

HORIZONS=(5,10,20)

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
    close=pd.to_numeric(df["Close"],errors="coerce"); vol=pd.to_numeric(df["Volume"],errors="coerce").fillna(0)
    high=pd.to_numeric(df["High"],errors="coerce"); low=pd.to_numeric(df["Low"],errors="coerce")
    if close.iloc[-170:].isna().any():return None
    ma50=close.rolling(50).mean().iloc[-1]; ma150=close.rolling(150).mean().iloc[-1]
    trend=bool(close.iloc[-1]>ma50>ma150)
    drops=[]; piv=local_turns(close.values)
    for a,b in zip(piv,piv[1:]):
        if a[1]=="H" and b[1]=="L" and a[2]>0:
            pct=(a[2]-b[2])/a[2]*100
            if math.isfinite(float(pct)) and 0<float(pct)<95:drops.append((a[0],b[0],pct))
    seq=[x[2] for x in drops[-4:]]
    two=len(seq)>=2
    contracting=two and all(seq[i]<seq[i-1]*1.12 for i in range(1,len(seq)))
    recent=close.iloc[-35:]; pivot=float(recent.iloc[:-3].max()); last=float(close.iloc[-1]); prev=float(close.iloc[-2])
    distance=(last/pivot-1)*100
    v20=float(vol.iloc[-20:].mean()); vprev=float(vol.iloc[-60:-20].mean())
    dry=bool(vprev>0 and v20<vprev*0.85)
    breakout=last>pivot; breakout_vol=bool(v20>0 and vol.iloc[-1]>v20*1.35)
    today_breakout=bool(prev<=pivot and breakout and breakout_vol)
    pivot_condition=bool(today_breakout or ((not breakout) and distance>-8))
    score=sum([trend,two,contracting,dry,pivot_condition])
    prev_close=close.shift(1)
    tr=pd.concat([(high-low).abs(),(high-prev_close).abs(),(low-prev_close).abs()],axis=1).max(axis=1)
    atr20=float(tr.rolling(20).mean().iloc[-1]); atr60=float(tr.rolling(60).mean().iloc[-1])
    atr_contract=bool(atr60>0 and atr20/atr60<=0.85)
    avg_value=float((close.iloc[-20:]*vol.iloc[-20:]).mean())
    # Frozen B trigger: near pivot within 5%, or a fresh breakout confirmed by volume.
    clear_trigger=bool(today_breakout or ((not breakout) and -5<distance<=0))
    baseline=bool(avg_value>=20_000_000 and score>=4)
    candidate=bool(avg_value>=20_000_000 and trend and two and contracting and dry and atr_contract and clear_trigger)
    return dict(trend=trend,twoContractions=two,priceContracting=contracting,volumeDry=dry,
                atrContracting=atr_contract,atr20To60=round(atr20/atr60,4) if atr60>0 else None,
                clearTrigger=clear_trigger,todayBreakout=today_breakout,distancePct=round(distance,2),
                score5=int(score),baseline=baseline,candidate=candidate,avgValue20=avg_value)

def median(x):
    return float(np.median(x)) if x else None

def summarize(rows,label):
    out={"label":label,"observations":len(rows)}
    for h in HORIZONS:
        valid=[r for r in rows if r.get(f"ret{h}") is not None]
        vals=[r[f"ret{h}"] for r in valid]
        maes=[r[f"mae{h}"] for r in valid if r.get(f"mae{h}") is not None]
        mfes=[r[f"mfe{h}"] for r in valid if r.get(f"mfe{h}") is not None]
        out[str(h)]={
            "n":len(vals),"avgReturnPct":round(sum(vals)/len(vals),2) if vals else None,
            "medianReturnPct":round(median(vals),2) if vals else None,
            "positivePct":round(sum(v>0 for v in vals)/len(vals)*100,1) if vals else None,
            "avgMAEPct":round(sum(maes)/len(maes),2) if maes else None,
            "avgMFEPct":round(sum(mfes)/len(mfes),2) if mfes else None,
        }
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--daily",required=True); ap.add_argument("--cache-dir",required=True); ap.add_argument("--out-dir",default="v11_ab_output")
    args=ap.parse_args(); out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    daily=json.loads(Path(args.daily).read_text(encoding="utf-8")); dates=[d["date"] for d in daily]
    prices={}
    for p in Path(args.cache_dir).glob("*.csv"):
        try: prices[p.stem]=pd.read_csv(p,parse_dates=["Date"]).set_index("Date").sort_index()
        except Exception: pass
    A=[];B=[];both=[];a_only=[];b_only=[]
    for date0 in dates:
        ts=pd.Timestamp(date0)
        for code,df in prices.items():
            cut=df.loc[:ts]
            if cut.empty or cut.index[-1]!=ts:continue
            f=features(cut)
            if not f or not (f["baseline"] or f["candidate"]):continue
            loc=df.index.get_loc(ts)
            if not isinstance(loc,(int,np.integer)):continue
            p0=float(df.iloc[loc]["Close"])
            row={"date":date0,"code":code,**f}
            for h in HORIZONS:
                if loc+h>=len(df): row[f"ret{h}"]=row[f"mae{h}"]=row[f"mfe{h}"]=None; continue
                future=df.iloc[loc+1:loc+h+1]
                row[f"ret{h}"]=(float(df.iloc[loc+h]["Close"])/p0-1)*100
                row[f"mae{h}"]=(float(pd.to_numeric(future["Low"],errors="coerce").min())/p0-1)*100
                row[f"mfe{h}"]=(float(pd.to_numeric(future["High"],errors="coerce").max())/p0-1)*100
            if f["baseline"]:A.append(row)
            if f["candidate"]:B.append(row)
            if f["baseline"] and f["candidate"]:both.append(row)
            elif f["baseline"]:a_only.append(row)
            else:b_only.append(row)
    summary={
      "version":"v1.1-candidate-ab-research","productionChanged":False,"thresholdsOptimized":False,
      "A_definition":"Current formal baseline: avg value >=20m and score >=4/5.",
      "B_definition":"Frozen candidate: trend + >=2 contractions + price contraction + volume dry + ATR20/ATR60 <=0.85 + clear pivot trigger (near within 5% or volume-confirmed fresh breakout).",
      "groups":{"A_current":summarize(A,"A current"),"B_candidate":summarize(B,"B v1.1 candidate"),"overlap":summarize(both,"A∩B"),"A_only":summarize(a_only,"A only"),"B_only":summarize(b_only,"B only")},
      "decisionRule":"Do not promote B from one metric. Prefer B only if 5/10/20d returns and/or positive rate improve without materially worse MAE or unusably low coverage; confirm on a later untouched OOS window before production.",
      "limitations":["Same historical price cache/universe is reused for A and B.","This is a rule comparison, not causal proof.","Fees, taxes, slippage and execution constraints are excluded."]
    }
    (out/"v11_ab_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    pd.DataFrame(A).to_csv(out/"A_current_observations.csv",index=False); pd.DataFrame(B).to_csv(out/"B_candidate_observations.csv",index=False)
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=="__main__":main()
