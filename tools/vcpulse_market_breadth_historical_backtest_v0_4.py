#!/usr/bin/env python3
"""VCPulse Market Breadth Historical Backtest v0.4

Replays the CURRENT scanner logic as-of each historical TW trading session.
No future bars are passed into scanner.analyze(). The daily radar is sorted and
capped at 200 exactly like current production scan().

Outputs:
  data/market_breadth_backtest_daily.csv
  data/market_breadth_backtest_summary.json
  data/market_breadth_backtest_diagnostics.json

Research only. Does not write screening.json and does not modify production rules.
"""
from __future__ import annotations
import argparse, json, math, time
from collections import defaultdict
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

import scanner
from tools.vcpulse_market_breadth_v0_1 import compute as compute_v01
from tools.vcpulse_market_breadth_v0_2 import compute as compute_v02

ROOT=Path(__file__).resolve().parents[1]
STATE_RANK={"breakout":0,"postbreakout":1,"near":2,"forming":3}


def _slice_ticker(raw, ticker, single=False):
    if raw is None or raw.empty: return pd.DataFrame()
    if single: return raw.copy()
    try:
        if isinstance(raw.columns,pd.MultiIndex) and ticker in raw.columns.get_level_values(0):
            return raw[ticker].copy()
    except Exception: pass
    return pd.DataFrame()


def download_prices(universe, period="2y", batch_size=80, sleep=0.4):
    prices={}; failures=[]
    for bi in range(0,len(universe),batch_size):
        batch=universe[bi:bi+batch_size]; tickers=[x["yf"] for x in batch]
        print(f"download batch {bi//batch_size+1}/{math.ceil(len(universe)/batch_size)} ({len(batch)} symbols)")
        raw=None
        for attempt in range(3):
            try:
                raw=yf.download(tickers=tickers,period=period,interval="1d",group_by="ticker",
                                auto_adjust=False,progress=False,threads=True,timeout=45)
                if raw is not None and len(raw): break
            except Exception as e:
                print("download retry",attempt+1,type(e).__name__,e); time.sleep(2*(attempt+1))
        for item in batch:
            d=_slice_ticker(raw,item["yf"],len(tickers)==1)
            if d.empty or "Close" not in d.columns:
                failures.append(item["symbol"]); continue
            d=d.dropna(subset=["Close"]).copy()
            if len(d)<170:
                failures.append(item["symbol"]); continue
            d.index=pd.to_datetime(d.index).tz_localize(None)
            # Apply the same official-event price-scale engine once to the full history.
            ev=scanner.detect_restore_events(d,item)
            prices[item["symbol"]]=(scanner.apply_restore_events_df(d,ev),item)
        time.sleep(sleep)
    return prices,failures


def benchmark(period="2y"):
    b=yf.download("^TWII",period=period,interval="1d",auto_adjust=False,progress=False,threads=False,timeout=45)
    if isinstance(b.columns,pd.MultiIndex):
        b.columns=b.columns.get_level_values(0)
    b=b.dropna(subset=["Close"]).copy(); b.index=pd.to_datetime(b.index).tz_localize(None)
    return b


def flow_row(df,item,pos,date_str):
    if pos<20:return None
    c=pd.to_numeric(df["Close"],errors="coerce"); v=pd.to_numeric(df["Volume"],errors="coerce").fillna(0)
    if pd.isna(c.iloc[pos]) or pd.isna(c.iloc[pos-1]):return None
    value=c*v; latest=float(value.iloc[pos]) if pd.notna(value.iloc[pos]) else 0.0
    hist=value.iloc[max(0,pos-20):pos].dropna(); avg20=float(hist.mean()) if len(hist) else 0.0
    prev=float(c.iloc[pos-1]); px=float(c.iloc[pos]); chg=(px/prev-1)*100 if prev else 0.0
    return {"symbol":item["symbol"],"industry":item.get("industry") or "其他","data_date":date_str,
            "value":latest,"avg20_value":avg20,"change_pct":chg,"up":bool(chg>0)}


def forward_returns(b, pos, horizons=(1,3,5,10)):
    c=float(b["Close"].iloc[pos]); out={}
    for h in horizons:
        out[f"t{h}_return_pct"]=round((float(b["Close"].iloc[pos+h])/c-1)*100,4) if pos+h<len(b) else None
    return out


def stats_for(df,col,score_col):
    x=df[[score_col,col]].dropna()
    if len(x)<8:return {"n":len(x)}
    return {"n":len(x),"mean_return_pct":round(float(x[col].mean()),4),
            "median_return_pct":round(float(x[col].median()),4),
            "positive_rate_pct":round(float((x[col]>0).mean()*100),2),
            "pearson_score_return":round(float(x[score_col].corr(x[col])),4)}


def bucket_stats(df,score_col,ret_col):
    bins=[-0.001,30,45,55,70,100.001]; labels=["<30","30-44.9","45-54.9","55-69.9",">=70"]
    z=df[[score_col,ret_col]].dropna().copy(); z["bucket"]=pd.cut(z[score_col],bins=bins,labels=labels,right=False)
    out=[]
    for label,g in z.groupby("bucket",observed=False):
        if len(g)==0:continue
        out.append({"bucket":str(label),"n":int(len(g)),"mean_return_pct":round(float(g[ret_col].mean()),4),
                    "positive_rate_pct":round(float((g[ret_col]>0).mean()*100),2)})
    return out


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--sessions",type=int,default=252,help="historical test sessions; default ~1 trading year")
    ap.add_argument("--period",default="2y")
    ap.add_argument("--max-stocks",type=int,default=0,help="smoke test only; 0=full TW universe")
    ap.add_argument("--out",default="data/market_breadth_backtest_daily.csv")
    a=ap.parse_args()

    # Same official-event source used by scanner; failure falls back to verified seed cache.
    scanner.OFFICIAL_RESTORE_EVENTS=scanner.fetch_official_restore_events()
    universe=scanner.fetch_tw_universe()
    if a.max_stocks>0: universe=universe[:a.max_stocks]
    print("TW universe",len(universe))
    b=benchmark(a.period)
    if len(b)<180: raise RuntimeError(f"benchmark history too short: {len(b)}")
    # Leave 10 future sessions available for T+10 labels.
    eligible=list(b.index[:-10]); test_dates=eligible[-a.sessions:]
    test_set=set(pd.Timestamp(x) for x in test_dates)
    print("test window",test_dates[0].date(),"to",test_dates[-1].date(),"sessions",len(test_dates))

    prices,failures=download_prices(universe,a.period)
    print("usable stocks",len(prices),"failures",len(failures))
    by_date=defaultdict(list); flows=defaultdict(list)

    for si,(sym,(df,item)) in enumerate(prices.items(),1):
        # Map exact exchange sessions. Each analyze call sees ONLY bars <= as-of date.
        posmap={pd.Timestamp(d):i for i,d in enumerate(df.index)}
        for d in test_dates:
            ts=pd.Timestamp(d); pos=posmap.get(ts)
            if pos is None or pos<169: continue
            cut=df.iloc[:pos+1]
            try:r=scanner.analyze(cut,item,"TW")
            except Exception as e:
                print("analyze warning",sym,ts.date(),type(e).__name__); r=None
            if r:
                r["industry"]=item.get("industry") or ""
                by_date[ts].append(r)
            fr=flow_row(df,item,pos,ts.strftime("%Y-%m-%d"))
            if fr:flows[ts].append(fr)
        if si%100==0:print("replayed",si,"/",len(prices))

    rows=[]
    for d in test_dates:
        ts=pd.Timestamp(d); cand=by_date.get(ts,[])
        cand.sort(key=lambda r:(STATE_RANK.get(r.get("type"),9),-int(r.get("score") or 0),abs(float(r.get("distance") or 0))))
        cand=cand[:200]
        hotspots=scanner.build_capital_hotspots(flows.get(ts,[]),cand) if flows.get(ts) else []
        bi=b.index.get_loc(ts); close=float(b["Close"].iloc[bi]); prev=float(b["Close"].iloc[bi-1]) if bi>0 else close
        chg=(close/prev-1)*100 if prev else 0.0
        snap={"official_results":cand,"official_capital_hotspots":{"TW":hotspots},
              "official_benchmarks":{"TW":{"TWSE":{"close":close,"change_pct":chg}}}}
        v1=compute_v01(snap); v2=compute_v02(snap)
        rec={"date":ts.strftime("%Y-%m-%d"),"twse_close":round(close,2),"twse_change_pct":round(chg,4),
             "candidate_count":len(cand),"v01_score":v1["score"],"v01_regime":v1["regime"],
             "v02_score":v2["score"],"v02_regime":v2["regime"],
             "breakout_count":v2["breakout_count"],"postbreakout_count":v2["postbreakout_count"],
             "near_pivot_count":v2["near_pivot_count"],"forming_count":v2["forming_count"],
             "extended_count":v2["extended_count"],"active_industry_count":v2["active_industry_count"]}
        rec.update(forward_returns(b,bi)); rows.append(rec)

    out=ROOT/a.out; out.parent.mkdir(parents=True,exist_ok=True)
    df=pd.DataFrame(rows); df["v02_delta_1d"]=df["v02_score"].diff(); df["v02_delta_5d"]=df["v02_score"].diff(5)
    df["divergence_1d"]=df["v02_delta_1d"]-df["twse_change_pct"]
    df.to_csv(out,index=False,encoding="utf-8-sig")

    summary={"version":"market_breadth_historical_backtest_v0.4","scanner_build":scanner.__doc__ or "see scanner.py header",
             "test_start":df["date"].iloc[0] if len(df) else None,"test_end":df["date"].iloc[-1] if len(df) else None,
             "sessions":int(len(df)),"universe_requested":len(universe),"usable_price_histories":len(prices),
             "warning":"Historical replay of current scanner rules; not a trading recommendation. Forward recorder remains the clean OOS check.",
             "v01":{},"v02":{}}
    for score_col,key in [("v01_score","v01"),("v02_score","v02")]:
        for h in (1,3,5,10):
            rc=f"t{h}_return_pct"; summary[key][f"t{h}"]=stats_for(df,rc,score_col)
            summary[key][f"t{h}_buckets"]=bucket_stats(df,score_col,rc)
    (ROOT/"data/market_breadth_backtest_summary.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding="utf-8")
    diag={"download_failures":failures,"failure_count":len(failures),"daily_candidate_min":int(df.candidate_count.min()) if len(df) else 0,
          "daily_candidate_median":float(df.candidate_count.median()) if len(df) else 0,"daily_candidate_max":int(df.candidate_count.max()) if len(df) else 0,
          "lookahead_guard":"For each stock/date, scanner.analyze receives df.iloc[:pos+1] only. T+ labels are added only after scores are frozen."}
    (ROOT/"data/market_breadth_backtest_diagnostics.json").write_text(json.dumps(diag,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":main()
