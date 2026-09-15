#!/usr/bin/env python3
"""
VCPulse Market Pulse validation v0.1
Research-only: does not modify scanner.py/index.html.

Input CSV columns:
date, tx_night, nasdaq, sox, us10y, brent, usdtwd,
tw_open_ret, tw_close_ret, tw_open_to_close_ret

All signal columns are percentage changes except us10y, which should be
the daily change in basis points. `date` is the Taiwan target trading date.
"""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd

FEATURES = ["tx_night","nasdaq","sox","us10y","brent","usdtwd"]
TARGETS = ["tw_open_ret","tw_close_ret","tw_open_to_close_ret"]

def safe_corr(a, b):
    x = pd.concat([a, b], axis=1).dropna()
    return float(x.iloc[:,0].corr(x.iloc[:,1])) if len(x) >= 10 else None

def direction_hit(signal, target):
    x = pd.concat([signal, target], axis=1).dropna()
    x = x[(x.iloc[:,0] != 0) & (x.iloc[:,1] != 0)]
    return float((np.sign(x.iloc[:,0]) == np.sign(x.iloc[:,1])).mean()) if len(x) else None

def zscore_train_apply(train, test, cols):
    mu = train[cols].mean()
    sd = train[cols].std(ddof=0).replace(0, np.nan)
    return (train[cols]-mu)/sd, (test[cols]-mu)/sd, mu, sd

def fit_linear(x, y):
    ok = x.notna().all(axis=1) & y.notna()
    X = np.c_[np.ones(ok.sum()), x.loc[ok].values]
    yy = y.loc[ok].values
    if len(yy) < len(x.columns)+20:
        raise ValueError("Not enough training observations.")
    beta = np.linalg.lstsq(X, yy, rcond=None)[0]
    return beta

def predict_linear(x, beta):
    return np.c_[np.ones(len(x)), x.fillna(0).values] @ beta

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/market_pulse_history.csv")
    ap.add_argument("--outdir", default="validation_output/market_pulse_v0_1")
    ap.add_argument("--train-ratio", type=float, default=0.70)
    args = ap.parse_args()

    df = pd.read_csv(args.input)
    missing = [c for c in ["date"]+FEATURES+TARGETS if c not in df.columns]
    if missing:
        raise SystemExit("Missing columns: " + ", ".join(missing))
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").drop_duplicates("date").reset_index(drop=True)

    # Research interactions. Brent is NOT hard-coded as bearish:
    # only shock combinations are tested explicitly.
    df["tech_consensus"] = (df["nasdaq"] + df["sox"]) / 2
    df["tx_tech_divergence"] = df["tx_night"] - df["tech_consensus"]
    df["oil_yield_shock"] = df["brent"].clip(lower=0) * df["us10y"].clip(lower=0)
    model_features = FEATURES + ["tx_tech_divergence","oil_yield_shock"]

    split = max(int(len(df)*args.train_ratio), 30)
    if split >= len(df)-20:
        raise SystemExit("Need more history for a meaningful chronological OOS split.")
    train, test = df.iloc[:split].copy(), df.iloc[split:].copy()

    # Simple baseline = TX night only. Model weights are learned on train only.
    ztr, zte, mu, sd = zscore_train_apply(train, test, model_features)
    beta = fit_linear(ztr, train["tw_close_ret"])
    test["model_pred_close_ret"] = predict_linear(zte, beta)
    test["baseline_tx_pred"] = test["tx_night"]

    report = {
        "version":"market-pulse-validation-v0.1",
        "rows":len(df),
        "train_rows":len(train),
        "test_rows":len(test),
        "train_end":str(train["date"].max().date()),
        "test_start":str(test["date"].min().date()),
        "single_signal":{},
        "oos":{},
        "learned_standardized_coefficients":{
            "intercept":float(beta[0]),
            **{k:float(v) for k,v in zip(model_features,beta[1:])}
        }
    }
    for f in FEATURES:
        report["single_signal"][f] = {
            "corr_next_close":safe_corr(df[f],df["tw_close_ret"]),
            "direction_hit_next_close":direction_hit(df[f],df["tw_close_ret"])
        }

    for name, pred in [("tx_night_baseline",test["baseline_tx_pred"]),
                       ("multisignal_model",test["model_pred_close_ret"])]:
        y=test["tw_close_ret"]
        ok=pred.notna() & y.notna()
        report["oos"][name]={
            "n":int(ok.sum()),
            "direction_accuracy":float((np.sign(pred[ok])==np.sign(y[ok])).mean()),
            "correlation":safe_corr(pred[ok],y[ok]),
            "mae":float(np.mean(np.abs(pred[ok]-y[ok])))
        }

    # Divergence study
    q = df["tx_tech_divergence"].abs().quantile(.75)
    div = df[df["tx_tech_divergence"].abs() >= q].copy()
    report["divergence"] = {
        "threshold_abs_q75":float(q),
        "n":len(div),
        "tx_direction_hit":direction_hit(div["tx_night"],div["tw_close_ret"]),
        "tech_direction_hit":direction_hit(div["tech_consensus"],div["tw_close_ret"])
    }

    out=Path(args.outdir); out.mkdir(parents=True,exist_ok=True)
    test.to_csv(out/"oos_predictions.csv",index=False)
    pd.DataFrame({
        "feature":model_features,
        "standardized_coefficient":beta[1:]
    }).to_csv(out/"learned_coefficients.csv",index=False)
    (out/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")

    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__":
    main()
