#!/usr/bin/env python3
"""
VCPulse Scale Bias Validation v0.1

Purpose
-------
Diagnose whether static membership scoring scale (Grade/Purity/Confidence)
causes some Rankable themes to appear in Theme Top5 / Setup Top5 more often.

This is a *selection-bias diagnostic*, not a return-performance backtest.
It consumes the existing historical runner's backtest_daily.json and the
V2.9 Alpha20/Alpha21 theme DB.

It DOES NOT modify theme DB scores, formulas, production files, or screening.json.
"""

from __future__ import annotations
import argparse, json, math, statistics
from collections import defaultdict
from pathlib import Path

GRADE_W = {"A":1.0,"B":0.75,"C":0.45,"D":0.20}

def membership_weight(m):
    if (m.get("confidence") or 0) < 60:
        return 0.0
    return (
        GRADE_W.get(m.get("grade"),0.0)
        * (0.40 + 0.60*(m.get("purity",0)/100))
        * (0.50 + 0.50*(m.get("confidence",0)/100))
    )

def pearson(xs, ys):
    if len(xs) < 3 or len(xs) != len(ys):
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    dx=[x-mx for x in xs]; dy=[y-my for y in ys]
    den=(sum(x*x for x in dx)*sum(y*y for y in dy))**0.5
    return (sum(a*b for a,b in zip(dx,dy))/den) if den else None

def load_static_scale(db):
    aliases=db["themeTaxonomy"].get("alias_to_canonical",{})
    rankable=set(db["themeTaxonomy"]["rankable_index"].keys())
    vals=defaultdict(list)
    for code,s in db["stocks"].items():
        for raw,m in s.get("themes",{}).items():
            c=aliases.get(raw,raw)
            if c in rankable:
                vals[c].append(membership_weight(m))
    rows={}
    per_member=[]
    for c in sorted(rankable):
        ws=vals.get(c,[])
        avg=statistics.mean(ws) if ws else 0.0
        rows[c]={
            "member_count":len(ws),
            "static_effective_weight":round(sum(ws),4),
            "avg_static_weight_per_member":round(avg,4),
        }
        per_member.append(avg)
    med=statistics.median(per_member) if per_member else 0
    for c,r in rows.items():
        d=r["avg_static_weight_per_member"]-med
        r["scale_flag"]="high-scale" if d>=0.14 else "low-scale" if d<=-0.14 else "balanced"
        r["delta_vs_median"]=round(d,4)
    return rows, med

def analyze(db, daily):
    static, median_scale = load_static_scale(db)
    rankable=set(static)
    stats={c:{
        "theme_top5":0,"setup_top5":0,"theme_top1":0,"setup_top1":0,
        "eligible_days":0,"observed_theme_days":0,
        "heat_values":[],"setup_values":[]
    } for c in rankable}

    boundary_pairs=[
        ("AI電力基建","重電/強韌電網"),
        ("CPO/矽光子","高速光通訊"),
        ("機器人","機器人關鍵零組件")
    ]
    pair_days={f"{a} ↔ {b}":{"both_theme_top5":0,"both_setup_top5":0,"days":0}
               for a,b in boundary_pairs}

    valid_days=0
    for day in daily:
        themes=day.get("themes") or []
        if not themes:
            continue
        valid_days+=1
        by_name={x.get("theme"):x for x in themes if x.get("theme")}
        theme5=[x.get("theme") for x in (day.get("themeTop5") or [])]
        setup5=[x.get("theme") for x in (day.get("setupTop5") or [])]

        for c in rankable:
            x=by_name.get(c)
            if x:
                stats[c]["observed_theme_days"]+=1
                if x.get("constituents",0)>=4 and x.get("effectiveWeight",0)>=2:
                    stats[c]["eligible_days"]+=1
                if isinstance(x.get("heat"),(int,float)): stats[c]["heat_values"].append(x["heat"])
                if isinstance(x.get("setup"),(int,float)): stats[c]["setup_values"].append(x["setup"])
            if c in theme5: stats[c]["theme_top5"]+=1
            if c in setup5: stats[c]["setup_top5"]+=1
            if theme5 and theme5[0]==c: stats[c]["theme_top1"]+=1
            if setup5 and setup5[0]==c: stats[c]["setup_top1"]+=1

        for a,b in boundary_pairs:
            k=f"{a} ↔ {b}"
            pair_days[k]["days"]+=1
            if a in theme5 and b in theme5: pair_days[k]["both_theme_top5"]+=1
            if a in setup5 and b in setup5: pair_days[k]["both_setup_top5"]+=1

    rows=[]
    for c in sorted(rankable):
        s=stats[c]; elig=s["eligible_days"]
        row={
            "theme":c,
            **static[c],
            "eligible_days":elig,
            "theme_top5_days":s["theme_top5"],
            "setup_top5_days":s["setup_top5"],
            "theme_top1_days":s["theme_top1"],
            "setup_top1_days":s["setup_top1"],
            "theme_top5_rate_per_eligible":round(s["theme_top5"]/elig,4) if elig else None,
            "setup_top5_rate_per_eligible":round(s["setup_top5"]/elig,4) if elig else None,
            "avg_heat":round(statistics.mean(s["heat_values"]),2) if s["heat_values"] else None,
            "avg_setup":round(statistics.mean(s["setup_values"]),2) if s["setup_values"] else None,
        }
        rows.append(row)

    usable=[r for r in rows if r["theme_top5_rate_per_eligible"] is not None]
    corr_theme=pearson(
        [r["avg_static_weight_per_member"] for r in usable],
        [r["theme_top5_rate_per_eligible"] for r in usable]
    )
    usable_s=[r for r in rows if r["setup_top5_rate_per_eligible"] is not None]
    corr_setup=pearson(
        [r["avg_static_weight_per_member"] for r in usable_s],
        [r["setup_top5_rate_per_eligible"] for r in usable_s]
    )

    grouped={}
    for flag in ("high-scale","balanced","low-scale"):
        rr=[r for r in rows if r["scale_flag"]==flag and r["theme_top5_rate_per_eligible"] is not None]
        grouped[flag]={
            "themes":[r["theme"] for r in rr],
            "mean_theme_top5_rate":round(statistics.mean(r["theme_top5_rate_per_eligible"] for r in rr),4) if rr else None,
            "mean_setup_top5_rate":round(statistics.mean(r["setup_top5_rate_per_eligible"] for r in rr),4) if rr else None,
        }

    caution=[]
    if valid_days < 20:
        caution.append("sample_lt_20_days")
    if corr_theme is not None and abs(corr_theme)>=0.45:
        caution.append("static_scale_correlates_with_theme_top5_frequency")
    if corr_setup is not None and abs(corr_setup)>=0.45:
        caution.append("static_scale_correlates_with_setup_top5_frequency")

    return {
        "version":"0.1",
        "purpose":"selection-bias diagnostic only",
        "valid_days":valid_days,
        "preferred_min_days":20,
        "better_days":40,
        "median_avg_static_weight_per_member":round(median_scale,4),
        "correlation":{
            "static_weight_vs_theme_top5_rate":round(corr_theme,4) if corr_theme is not None else None,
            "static_weight_vs_setup_top5_rate":round(corr_setup,4) if corr_setup is not None else None
        },
        "scale_groups":grouped,
        "boundary_pair_coappearance":pair_days,
        "themes":rows,
        "flags":caution,
        "decision":"WAIT_MORE_DATA" if valid_days<20 else ("REVIEW_SCALE" if caution else "KEEP_SCALE"),
        "note":"Do not treat this as return-performance validation. Use matched-control / forward-return tools for predictive validity."
    }

def render_md(r):
    lines=[
        "# VCPulse Scale Bias Validation v0.1","",
        f"- 有效交易日：**{r['valid_days']}**",
        f"- 建議最低樣本：{r['preferred_min_days']} 日；較佳：{r['better_days']} 日",
        f"- Theme Top5頻率與靜態尺度相關：`{r['correlation']['static_weight_vs_theme_top5_rate']}`",
        f"- Setup Top5頻率與靜態尺度相關：`{r['correlation']['static_weight_vs_setup_top5_rate']}`",
        f"- 判定：**{r['decision']}**","",
        "## 各題材",
        "",
        "| Theme | Scale | Eligible | Theme Top5率 | Setup Top5率 | Avg Heat | Avg Setup |",
        "|---|---|---:|---:|---:|---:|---:|",
    ]
    for x in sorted(r["themes"],key=lambda z:(z["theme_top5_rate_per_eligible"] or -1),reverse=True):
        tr=x["theme_top5_rate_per_eligible"]; sr=x["setup_top5_rate_per_eligible"]
        lines.append(
            f"| {x['theme']} | {x['scale_flag']} | {x['eligible_days']} | "
            f"{'-' if tr is None else f'{tr*100:.1f}%'} | "
            f"{'-' if sr is None else f'{sr*100:.1f}%'} | "
            f"{x['avg_heat'] if x['avg_heat'] is not None else '-'} | "
            f"{x['avg_setup'] if x['avg_setup'] is not None else '-'} |"
        )
    lines += ["","## 邊界題材共現"]
    for k,v in r["boundary_pair_coappearance"].items():
        lines.append(f"- {k}：Theme Top5同時出現 {v['both_theme_top5']} 日；Setup Top5同時出現 {v['both_setup_top5']} 日。")
    lines += ["","## 解讀規則",
              "- 樣本少於20個交易日：不調分。",
              "- 若High-scale題材在『eligible-day標準化後』仍顯著更常進Top5，且至少20–40日持續，再進入Purity/Confidence校準候選。",
              "- 若尺度與Top5頻率關聯不強，維持原始分數，避免為了看起來平均而過度校正。",
              "- 本工具只測『選榜偏差』；預測力仍需 forward return / matched control 驗證。"]
    return "\n".join(lines)

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--theme-db",required=True)
    ap.add_argument("--backtest-daily",required=True)
    ap.add_argument("--out-dir",default="scale_bias_output")
    args=ap.parse_args()

    db=json.loads(Path(args.theme_db).read_text(encoding="utf-8"))
    daily=json.loads(Path(args.backtest_daily).read_text(encoding="utf-8"))
    if isinstance(daily,dict):
        daily=daily.get("daily") or daily.get("rows") or []
    result=analyze(db,daily)
    out=Path(args.out_dir); out.mkdir(parents=True,exist_ok=True)
    (out/"scale_bias_validation.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
    (out/"scale_bias_validation.md").write_text(render_md(result),encoding="utf-8")
    print(json.dumps({
        "valid_days":result["valid_days"],
        "decision":result["decision"],
        "correlation":result["correlation"],
        "flags":result["flags"]
    },ensure_ascii=False,indent=2))

if __name__=="__main__":
    main()
