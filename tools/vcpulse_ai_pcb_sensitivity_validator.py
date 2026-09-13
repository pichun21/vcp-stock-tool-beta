from __future__ import annotations
import argparse,json
from pathlib import Path
from collections import defaultdict
import pandas as pd
import numpy as np

H=(1,3,5,10,20)
VIEWS=("heat_top1","setup_top1","heat_top5","setup_top5")
CANDS=("B40","B55","B70","B85")
COEF={"B40":0.40,"B55":0.55,"B70":0.70,"B85":0.85}

def J(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def price(p):
    d=pd.read_csv(p); cc="Close" if "Close" in d.columns else "close"
    d["Date"]=pd.to_datetime(d["Date"]); d[cc]=pd.to_numeric(d[cc],errors="coerce")
    return d.dropna(subset=["Date",cc]).drop_duplicates("Date").sort_values("Date").set_index("Date")[[cc]].rename(columns={cc:"Close"})
def members(db):
    a=db["themeTaxonomy"]["alias_to_canonical"]; o=defaultdict(set)
    for code,s in db["stocks"].items():
        for raw,m in s.get("themes",{}).items():
            can=a.get(raw)
            if can and float(m.get("confidence",0) or 0)>=60:o[can].add(str(code))
    return {k:sorted(v) for k,v in o.items()}
def sel(day,v):
    x=day.get("themeTop5",[]) if v.startswith("heat") else day.get("setupTop5",[])
    return [q["theme"] for q in (x[:1] if v.endswith("top1") else x)]
def tret(theme,codes,date,prices,h):
    d=pd.Timestamp(date); a=[]
    for c in codes:
        x=prices.get(c)
        if x is None or d not in x.index:continue
        i=x.index.get_indexer([d])[0]
        if i<0 or i+h>=len(x):continue
        p0=float(x.iloc[i].Close); p1=float(x.iloc[i+h].Close)
        if p0>0 and np.isfinite(p1):a.append((p1/p0-1)*100)
    return float(np.mean(a)) if a else None
def st(x):
    a=pd.Series(x).dropna().astype(float)
    return {"n":int(len(a)),"mean":round(float(a.mean()),6) if len(a) else None,
            "median":round(float(a.median()),6) if len(a) else None,
            "positive_rate":round(float((a>0).mean()*100),4) if len(a) else None}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--theme-db",required=True); ap.add_argument("--max",required=True)
    for x in CANDS: ap.add_argument("--"+x.lower(),required=True)
    ap.add_argument("--price-cache",required=True); ap.add_argument("--benchmark-file",required=True)
    ap.add_argument("--out-dir",default="alpha134_result"); a=ap.parse_args()
    db=J(a.theme_db); mem=members(db)
    paths={"MAX":a.max,"B40":a.b40,"B55":a.b55,"B70":a.b70,"B85":a.b85}
    dm={m:{x["date"]:x for x in J(p)} for m,p in paths.items()}
    dates=sorted(set.intersection(*[set(v) for v in dm.values()]))
    prices={}
    for c in db["stocks"]:
        p=Path(a.price_cache)/f"{c}.csv"
        if p.exists():
            try:prices[str(c)]=price(p)
            except:pass
    bench=price(a.benchmark_file)
    rows=[]
    for date in dates:
      d0=pd.Timestamp(date)
      for view in VIEWS:
        ss={m:sel(dm[m][date],view) for m in paths}
        nr=1 if view.endswith("top1") else 5
        for rank in range(1,nr+1):
          themes={m:(ss[m][rank-1] if len(ss[m])>=rank else None) for m in paths}
          for h in H:
            br=None
            if d0 in bench.index:
              i=bench.index.get_indexer([d0])[0]
              if i>=0 and i+h<len(bench):
                p0=float(bench.iloc[i].Close); p1=float(bench.iloc[i+h].Close); br=(p1/p0-1)*100 if p0 else None
            rr={m:(tret(th,mem.get(th,[]),date,prices,h) if th else None) for m,th in themes.items()}
            if rr["MAX"] is None:continue
            for m in paths:
              if rr[m] is not None: rows.append({"date":date,"view":view,"rank":rank,"horizon":h,"mode":m,
                "theme":themes[m],"return":rr[m],"benchmark_return":br,
                "regime":"TAIEX_UP" if br is not None and br>0 else ("TAIEX_DOWN" if br is not None and br<0 else "TAIEX_FLAT")})
    r=pd.DataFrame(rows); keys=["date","view","rank","horizon"]
    mx=r[r.mode=="MAX"][keys+["theme","return","regime"]].rename(columns={"theme":"theme_max","return":"return_max","regime":"regime_max"})
    summaries={}; checks={}; detail=[]
    for c in CANDS:
      z=mx.merge(r[r.mode==c][keys+["theme","return"]],on=keys)
      z["delta"]=z["return"]-z["return_max"]; z["changed"]=z["theme"]!=z["theme_max"]
      detail.append(z.assign(candidate=c,coefficient=COEF[c]))
      s={}
      for view in VIEWS:
        s[view]={}
        for h in H:
          q=z[(z.view==view)&(z.horizon==h)]
          s[view][str(h)]={"all":st(q.delta),"changed":st(q.loc[q.changed,"delta"]),
            "up":st(q.loc[q.regime_max=="TAIEX_UP","delta"]),
            "up_changed":st(q.loc[(q.regime_max=="TAIEX_UP")&q.changed,"delta"])}
      summaries[c]=s
      ck=[]
      for h in ("10","20"):
        x=s["heat_top1"][h]["up"]; ck.append({"name":f"heat_up_{h}D_positive","pass":x["mean"] is not None and x["mean"]>0,"value":x})
        y=s["setup_top1"][h]["all"]; ck.append({"name":f"setup_all_{h}D_nonnegative","pass":y["mean"] is not None and y["mean"]>=0,"value":y})
      changed=sum(1 for _,x in z[(z.view=="heat_top1")].drop_duplicates(["date"]).iterrows() if x["changed"])
      ck.append({"name":"changes_at_least_one_heat_top1","pass":changed>0,"value":{"changed_dates":changed}})
      checks[c]=ck
    passing=[c for c in CANDS if all(x["pass"] for x in checks[c])]
    winner=passing[0] if passing else None
    report={"schema":"vcpulse-alpha134-ai-pcb-sensitivity","days":len(dates),"benchmark_loaded":not bench.empty,
      "coefficients":COEF,"selection_rule":"smallest coefficient passing all pre-declared gates",
      "gate":"PASS" if winner else "HOLD","selected":winner,"selected_coefficient":COEF[winner] if winner else None,
      "checks":checks,"summary_vs_global_max":summaries,"production":"UNCHANGED"}
    out=Path(a.out_dir);out.mkdir(parents=True,exist_ok=True)
    (out/"alpha134_ai_pcb_sensitivity.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    pd.concat(detail,ignore_index=True).to_csv(out/"alpha134_candidate_vs_max.csv",index=False,encoding="utf-8-sig")
    lines=["# VCPulse Alpha134 — AI PCB Breadth Sensitivity","",f"- Gate: **{report['gate']}**",
           f"- Selected: **{winner or 'NONE'}**",f"- Production: **UNCHANGED**","",
           "## Pre-declared gate results",""]
    for c in CANDS:
      lines.append(f"### {c} ({COEF[c]:.0%})")
      for x in checks[c]:
        v=x["value"]; val=v.get("mean",v.get("changed_dates"))
        lines.append(f"- {'PASS' if x['pass'] else 'HOLD'} — {x['name']}: {val}")
    (out/"alpha134_ai_pcb_sensitivity.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"gate":report["gate"],"selected":winner,"days":len(dates)},ensure_ascii=False))

if __name__=="__main__": main()
