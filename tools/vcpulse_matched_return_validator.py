from __future__ import annotations

import argparse, json, math
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

HORIZONS=(1,3,5,10,20)
MODES=("CONTROL_current","DEDUP_max","DEDUP_decay")
VIEWS=("heat_top1","setup_top1","heat_top5","setup_top5")

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def normalize_prices(path):
    df=pd.read_csv(path)
    if "Date" not in df.columns:
        raise ValueError(f"{path}: missing Date")
    close_col="Close" if "Close" in df.columns else ("close" if "close" in df.columns else None)
    if not close_col:
        raise ValueError(f"{path}: missing Close/close")
    out=df[["Date",close_col]].copy()
    out["Date"]=pd.to_datetime(out["Date"])
    out[close_col]=pd.to_numeric(out[close_col],errors="coerce")
    out=out.dropna().drop_duplicates("Date").sort_values("Date").set_index("Date")
    return out.rename(columns={close_col:"Close"})

def canonical_members(theme_db):
    amap=theme_db["themeTaxonomy"]["alias_to_canonical"]
    out=defaultdict(set)
    for code,s in theme_db.get("stocks",{}).items():
        for raw,meta in s.get("themes",{}).items():
            can=amap.get(raw)
            if can and float(meta.get("confidence",0) or 0)>=60:
                out[can].add(str(code))
    return {k:sorted(v) for k,v in out.items()}

def theme_path(theme,codes,signal_date,prices,benchmark,max_h=20):
    d0=pd.Timestamp(signal_date)
    stock_paths=[]
    for code in codes:
        df=prices.get(code)
        if df is None or df.empty or d0 not in df.index:
            continue
        idx=df.index
        pos=idx.get_indexer([d0])[0]
        if pos < 0:
            continue
        base=float(df.iloc[pos]["Close"])
        if not np.isfinite(base) or base<=0:
            continue
        vals=[]
        for k in range(0,max_h+1):
            j=pos+k
            vals.append(float(df.iloc[j]["Close"]/base-1)*100 if j<len(df) else np.nan)
        stock_paths.append(vals)

    if not stock_paths:
        return None
    arr=np.asarray(stock_paths,float)
    portfolio=np.nanmean(arr,axis=0)
    n_by_h=np.sum(np.isfinite(arr),axis=0).astype(int)

    bench_path=np.full(max_h+1,np.nan)
    if benchmark is not None and not benchmark.empty and d0 in benchmark.index:
        idx=benchmark.index
        pos=idx.get_indexer([d0])[0]
        b0=float(benchmark.iloc[pos]["Close"])
        if np.isfinite(b0) and b0>0:
            for k in range(0,max_h+1):
                j=pos+k
                if j<len(benchmark):
                    bench_path[k]=float(benchmark.iloc[j]["Close"]/b0-1)*100

    out={}
    for h in HORIZONS:
        r=portfolio[h] if h<len(portfolio) else np.nan
        if not np.isfinite(r):
            out[h]=None
            continue
        sub=portfolio[1:h+1]
        finite=sub[np.isfinite(sub)]
        mae=float(np.min(finite)) if len(finite) else np.nan
        mfe=float(np.max(finite)) if len(finite) else np.nan
        br=bench_path[h] if h<len(bench_path) else np.nan
        out[h]={
            "return":float(r),
            "benchmark_return":float(br) if np.isfinite(br) else None,
            "excess_return":float(r-br) if np.isfinite(br) else None,
            "mae":mae if np.isfinite(mae) else None,
            "mfe":mfe if np.isfinite(mfe) else None,
            "stocks":int(n_by_h[h]) if h<len(n_by_h) else 0
        }
    return out

def extract_view(day,view):
    if view=="heat_top1":
        return [day["themeTop5"][0]["theme"]] if day.get("themeTop5") else []
    if view=="setup_top1":
        return [day["setupTop5"][0]["theme"]] if day.get("setupTop5") else []
    if view=="heat_top5":
        return [x["theme"] for x in day.get("themeTop5",[])]
    if view=="setup_top5":
        return [x["theme"] for x in day.get("setupTop5",[])]
    raise ValueError(view)

def mean_or_none(xs):
    xs=[float(x) for x in xs if x is not None and np.isfinite(float(x))]
    return float(np.mean(xs)) if xs else None

def median_or_none(xs):
    xs=[float(x) for x in xs if x is not None and np.isfinite(float(x))]
    return float(np.median(xs)) if xs else None

def aggregate(rows):
    result={}
    for h in HORIZONS:
        rr=[r for r in rows if r["horizon"]==h and r["return"] is not None]
        vals=[r["return"] for r in rr]
        exc=[r["excess_return"] for r in rr if r["excess_return"] is not None]
        result[str(h)]={
            "observations":len(rr),
            "mean_return":mean_or_none(vals),
            "median_return":median_or_none(vals),
            "win_rate":(sum(v>0 for v in vals)/len(vals)*100) if vals else None,
            "mean_excess_return":mean_or_none(exc),
            "mean_mae":mean_or_none([r["mae"] for r in rr]),
            "mean_mfe":mean_or_none([r["mfe"] for r in rr]),
        }
    return result

def round_nested(obj):
    if isinstance(obj,dict):
        return {k:round_nested(v) for k,v in obj.items()}
    if isinstance(obj,list):
        return [round_nested(v) for v in obj]
    if isinstance(obj,float):
        if math.isnan(obj): return None
        return round(obj,4)
    return obj

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--theme-db",required=True)
    ap.add_argument("--control",required=True)
    ap.add_argument("--max",dest="max_file",required=True)
    ap.add_argument("--decay",required=True)
    ap.add_argument("--price-cache",required=True)
    ap.add_argument("--benchmark-file",default="")
    ap.add_argument("--out-dir",default="alpha129_return_validation")
    args=ap.parse_args()

    theme_db=load_json(args.theme_db)
    members=canonical_members(theme_db)
    daily={
        "CONTROL_current":load_json(args.control),
        "DEDUP_max":load_json(args.max_file),
        "DEDUP_decay":load_json(args.decay),
    }
    by_mode_date={m:{d["date"]:d for d in arr} for m,arr in daily.items()}
    common_dates=sorted(set.intersection(*[set(x) for x in by_mode_date.values()]))

    cache=Path(args.price_cache)
    prices={}
    for code in theme_db.get("stocks",{}):
        p=cache/f"{code}.csv"
        if p.exists():
            try: prices[str(code)]=normalize_prices(p)
            except Exception as e: print("price skip",code,e)

    benchmark=None
    bp=Path(args.benchmark_file) if args.benchmark_file else cache/"001.csv"
    if bp.exists():
        try: benchmark=normalize_prices(bp)
        except Exception as e: print("benchmark skip",e)

    # Precompute per date/theme once.
    needed=set()
    for m in MODES:
        for d in common_dates:
            day=by_mode_date[m][d]
            for v in VIEWS:
                for th in extract_view(day,v):
                    needed.add((d,th))
    pre={}
    for i,(d,th) in enumerate(sorted(needed),1):
        pre[(d,th)]=theme_path(th,members.get(th,[]),d,prices,benchmark,max(HORIZONS))
        if i%100==0: print("return paths",i,"/",len(needed))

    rows=[]
    for mode in MODES:
        for d in common_dates:
            day=by_mode_date[mode][d]
            for view in VIEWS:
                themes=extract_view(day,view)
                for rank,th in enumerate(themes,1):
                    p=pre.get((d,th))
                    if not p: continue
                    for h in HORIZONS:
                        x=p.get(h)
                        if not x: continue
                        rows.append({
                            "mode":mode,"date":d,"view":view,"rank":rank,"theme":th,"horizon":h,
                            **x
                        })

    # disagreement flags
    diff_control={}
    diff_max_decay={}
    for d in common_dates:
        diff_control[d]={}
        diff_max_decay[d]={}
        for view in VIEWS:
            c=extract_view(by_mode_date["CONTROL_current"][d],view)
            b=extract_view(by_mode_date["DEDUP_max"][d],view)
            q=extract_view(by_mode_date["DEDUP_decay"][d],view)
            diff_control[d][view]=(c!=b or c!=q)
            diff_max_decay[d][view]=(b!=q)

    overall={}
    control_changed={}
    max_decay_disagree={}
    for mode in MODES:
        overall[mode]={}
        control_changed[mode]={}
        max_decay_disagree[mode]={}
        for view in VIEWS:
            rs=[r for r in rows if r["mode"]==mode and r["view"]==view]
            overall[mode][view]=aggregate(rs)
            rs2=[r for r in rs if diff_control[r["date"]][view]]
            control_changed[mode][view]=aggregate(rs2)
            rs3=[r for r in rs if diff_max_decay[r["date"]][view]]
            max_decay_disagree[mode][view]=aggregate(rs3)

    # Pairwise deltas on date/view/rank/horizon where both modes have scored observations.
    idx={(r["mode"],r["date"],r["view"],r["rank"],r["horizon"]):r for r in rows}
    pairwise={}
    for a,b in [("DEDUP_max","CONTROL_current"),("DEDUP_decay","CONTROL_current"),("DEDUP_decay","DEDUP_max")]:
        key=f"{a}_minus_{b}"
        pairwise[key]={}
        for view in VIEWS:
            pairwise[key][view]={}
            for h in HORIZONS:
                ds=[]
                for d in common_dates:
                    # Compare rank-matched signals. If theme is identical, delta is naturally 0.
                    ranks=range(1,2) if view.endswith("top1") else range(1,6)
                    for rank in ranks:
                        ra=idx.get((a,d,view,rank,h)); rb=idx.get((b,d,view,rank,h))
                        if ra and rb:
                            ds.append(ra["return"]-rb["return"])
                pairwise[key][view][str(h)]={
                    "paired_observations":len(ds),
                    "mean_return_delta":mean_or_none(ds),
                    "median_return_delta":median_or_none(ds),
                    "positive_delta_rate":(sum(x>0 for x in ds)/len(ds)*100) if ds else None
                }

    coverage={}
    for view in VIEWS:
        coverage[view]={}
        for h in HORIZONS:
            mode_keys={}
            for mode in MODES:
                mode_keys[mode]={
                    (r["date"],r["rank"]) for r in rows
                    if r["mode"]==mode and r["view"]==view and r["horizon"]==h and r["return"] is not None
                }
            common=set.intersection(*mode_keys.values()) if mode_keys else set()
            coverage[view][str(h)]={
                "CONTROL_valid":len(mode_keys["CONTROL_current"]),
                "MAX_valid":len(mode_keys["DEDUP_max"]),
                "DECAY_valid":len(mode_keys["DEDUP_decay"]),
                "all_three_matched":len(common)
            }

    report={
        "schema":"vcpulse-alpha130-return-coverage-repair",
        "common_days":len(common_dates),
        "first_date":common_dates[0] if common_dates else None,
        "last_date":common_dates[-1] if common_dates else None,
        "price_files_loaded":len(prices),
        "benchmark_loaded":benchmark is not None,
        "horizons":list(HORIZONS),
        "coverage":coverage,
        "overall":overall,
        "control_changed_days":control_changed,
        "max_decay_disagreement_days":max_decay_disagree,
        "pairwise_rank_matched":pairwise
    }
    report=round_nested(report)

    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"alpha130_return_validation.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    pd.DataFrame(rows).to_csv(out/"alpha130_return_observations.csv",index=False,encoding="utf-8-sig")

    # Compact markdown report
    lines=[
        "# VCPulse Alpha130 — Matched Return Validation",
        "",
        f"- Common signal days: **{report['common_days']}** ({report['first_date']} → {report['last_date']})",
        f"- Price files loaded: **{report['price_files_loaded']}**",
        f"- Benchmark loaded: **{report['benchmark_loaded']}**",
        "- Horizons: **1 / 3 / 5 / 10 / 20 trading days**",
        "- Production: **UNCHANGED**",
        "",
        "## Primary comparison — Heat Top1",
        ""
    ]
    for h in HORIZONS:
        lines.append(f"### {h}D")
        for mode in MODES:
            x=report["overall"][mode]["heat_top1"][str(h)]
            lines.append(
                f"- {mode}: n={x['observations']}, mean={x['mean_return']}%, "
                f"win={x['win_rate']}%, excess={x['mean_excess_return']}%, "
                f"MAE={x['mean_mae']}%, MFE={x['mean_mfe']}%"
            )
        lines.append("")
    lines += [
        "## Pairwise rank-matched return deltas",
        "",
        "Positive delta means the first mode outperformed the second mode on the same date/view/rank/horizon.",
        ""
    ]
    for pair,pv in report["pairwise_rank_matched"].items():
        lines.append(f"### {pair}")
        for h in HORIZONS:
            x=pv["heat_top1"][str(h)]
            lines.append(
                f"- Heat Top1 {h}D: n={x['paired_observations']}, "
                f"mean delta={x['mean_return_delta']}%, positive-rate={x['positive_delta_rate']}%"
            )
        lines.append("")
    (out/"alpha130_return_validation.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({
        "common_days":report["common_days"],
        "price_files_loaded":report["price_files_loaded"],
        "benchmark_loaded":report["benchmark_loaded"],
        "output":str(out)
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
