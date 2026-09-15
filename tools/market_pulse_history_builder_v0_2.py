#!/usr/bin/env python3
"""
VCPulse Market Pulse history builder v0.2
Research-only. Builds data/market_pulse_history.csv for v0.1 validator.

Design:
- Taiwan target calendar comes from ^TWII.
- US market signals are the latest completed US session before each Taiwan target date.
- Macro/market series use yfinance to keep GitHub Actions secret-free.
- TX night can be merged from a local TAIFEX CSV when available.
- Never fills a missing market session with 0.
"""
from pathlib import Path
import argparse, json, re
import numpy as np
import pandas as pd
import yfinance as yf

TICKERS={
    "tw":"^TWII",
    "nasdaq":"^IXIC",
    "sox":"^SOX",
    "us10y":"^TNX",
    "brent":"BZ=F",
    "usdtwd":"TWD=X",
}

def dl(ticker,start,end):
    x=yf.download(ticker,start=start,end=end,auto_adjust=False,progress=False,threads=False)
    if x.empty: return pd.DataFrame()
    if isinstance(x.columns,pd.MultiIndex): x.columns=x.columns.get_level_values(0)
    x=x.reset_index()
    x["Date"]=pd.to_datetime(x["Date"]).dt.tz_localize(None).dt.normalize()
    return x

def pct_close(x):
    s=x.set_index("Date")["Close"].astype(float)
    return s.pct_change(fill_method=None)*100

def latest_before(series, dates):
    s=series.dropna().sort_index()
    out=[]
    for d in dates:
        q=s.loc[s.index < d]
        out.append(q.iloc[-1] if len(q) else np.nan)
    return out

def parse_num(v):
    if pd.isna(v): return np.nan
    s=str(v).replace(",","").replace("%","").replace("▲","").replace("▼","").strip()
    try:return float(s)
    except:return np.nan

def load_tx(path):
    p=Path(path)
    if not p.exists(): return pd.Series(dtype=float)
    x=pd.read_csv(p)
    # Supports common English/Chinese TAIFEX column names.
    cols={str(c).lower().replace(" ",""):c for c in x.columns}
    def pick(*names):
        for n in names:
            k=n.lower().replace(" ","")
            if k in cols:return cols[k]
        return None
    datec=pick("Date","日期")
    contractc=pick("Contract","商品代號","契約")
    monthc=pick("ContractMonth(Week)","ContractMonth","到期月份(週別)","契約月份")
    sessionc=pick("TradingSession","交易時段")
    pctc=pick("%","Change%","漲跌幅")
    volc=pick("Volume","成交量")
    if not all([datec,contractc,monthc,sessionc,pctc]):
        raise ValueError("TX CSV schema not recognized.")
    x=x[x[contractc].astype(str).str.strip().eq("TX")].copy()
    x=x[x[sessionc].astype(str).str.contains("盤後|after",case=False,regex=True,na=False)]
    x=x[~x[monthc].astype(str).str.contains("/",regex=False)]
    x["date"]=pd.to_datetime(x[datec],errors="coerce").dt.normalize()
    x["ret"]=x[pctc].map(parse_num)
    x["vol"]=x[volc].map(parse_num) if volc else 0
    # Per trading date choose the liquid outright contract, reducing roll-day mistakes.
    x=x.sort_values(["date","vol"],ascending=[True,False]).drop_duplicates("date")
    return x.set_index("date")["ret"].sort_index()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--start",default="2021-01-01")
    ap.add_argument("--end",default=None)
    ap.add_argument("--tx-csv",default="data/raw_taifex_daily_futures.csv")
    ap.add_argument("--output",default="data/market_pulse_history.csv")
    args=ap.parse_args()
    end=args.end or (pd.Timestamp.utcnow().normalize()+pd.Timedelta(days=2)).strftime("%Y-%m-%d")

    raw={k:dl(t,args.start,end) for k,t in TICKERS.items()}
    tw=raw["tw"].copy()
    if tw.empty: raise SystemExit("No Taiwan index data.")
    tw=tw.sort_values("Date")
    dates=tw["Date"]

    out=pd.DataFrame({"date":dates})
    prev_close=tw["Close"].shift(1)
    out["tw_open_ret"]=(tw["Open"]/prev_close-1)*100
    out["tw_close_ret"]=(tw["Close"]/prev_close-1)*100
    out["tw_open_to_close_ret"]=(tw["Close"]/tw["Open"]-1)*100

    for k in ["nasdaq","sox","brent","usdtwd"]:
        out[k]=latest_before(pct_close(raw[k]),dates)

    # ^TNX is yield level in percent; convert session-to-session move to basis points.
    y=raw["us10y"].set_index("Date")["Close"].astype(float)
    bp=y.diff(fill_method=None)*100
    out["us10y"]=latest_before(bp,dates)

    tx=load_tx(args.tx_csv)
    out["tx_night"]=[tx.get(d,np.nan) for d in dates]

    cols=["date","tx_night","nasdaq","sox","us10y","brent","usdtwd",
          "tw_open_ret","tw_close_ret","tw_open_to_close_ret"]
    out=out[cols]
    Path(args.output).parent.mkdir(parents=True,exist_ok=True)
    out.to_csv(args.output,index=False)

    meta={
      "version":"market-pulse-history-v0.2",
      "rows":len(out),
      "start":str(out["date"].min().date()),
      "end":str(out["date"].max().date()),
      "missing":{c:int(out[c].isna().sum()) for c in cols if c!="date"},
      "tx_source_file":args.tx_csv,
      "note":"TX remains missing until TAIFEX historical/accumulated after-hours CSV is supplied."
    }
    mp=Path(args.output).with_suffix(".meta.json")
    mp.write_text(json.dumps(meta,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(meta,ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
