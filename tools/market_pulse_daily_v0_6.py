#!/usr/bin/env python3
import argparse, json, math, sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
import pandas as pd
import requests
import yfinance as yf

ROOT=Path(__file__).resolve().parents[1]
MODEL=ROOT/'data'/'market_pulse_model_v0_6.json'
OUT=ROOT/'market_pulse.json'
TZ=ZoneInfo('Asia/Taipei')

def num(v):
    if v is None: return None
    s=str(v).replace(',','').replace('%','').replace('▲','').replace('▼','').strip()
    if s in ('','-','--','nan','None'): return None
    try: return float(s)
    except: return None

def pick(d,*names):
    for n in names:
        if n in d and d[n] not in (None,''): return d[n]
    return None

def fetch_tx_night():
    url='https://openapi.taifex.com.tw/v1/DailyMarketReportFut'
    r=requests.get(url,timeout=35,headers={'User-Agent':'VCPulse-Market-Pulse/0.6'})
    r.raise_for_status(); rows=r.json()
    cand=[]
    for x in rows:
        contract=str(pick(x,'Contract','契約') or '').strip()
        session=str(pick(x,'TradingSession','交易時段') or '').strip()
        month=str(pick(x,'ContractMonth(Week)','ContractMonth','到期月份(週別)','到期月份') or '').strip()
        if contract!='TX' or session not in ('盤後','After Hours','AfterHours'): continue
        if '/' in month: continue
        pct=num(pick(x,'Change%','ChangePercent','漲跌%'))
        vol=num(pick(x,'Volume','成交量')) or 0
        date=str(pick(x,'Date','交易日期') or '')
        last=num(pick(x,'Last','Close','收盤價'))
        if pct is not None: cand.append((vol,pct,date,month,last))
    if not cand: raise RuntimeError('TAIFEX OpenAPI 找不到 TX 盤後資料')
    vol,pct,date,month,last=max(cand,key=lambda z:z[0])
    return {'value':pct,'date':date,'contract':month,'last':last,'volume':vol,'source':'TAIFEX OpenAPI'}

def yf_change(symbol):
    x=yf.download(symbol,period='10d',interval='1d',auto_adjust=False,progress=False,threads=False)
    if x is None or len(x)<2: raise RuntimeError(f'{symbol} 歷史資料不足')
    close=x['Close']
    if hasattr(close,'columns'): close=close.iloc[:,0]
    close=pd.to_numeric(close,errors='coerce').dropna()
    if len(close)<2: raise RuntimeError(f'{symbol} 收盤資料不足')
    pct=(float(close.iloc[-1])/float(close.iloc[-2])-1)*100
    return {'value':pct,'date':str(pd.Timestamp(close.index[-1]).date()),'close':float(close.iloc[-1]),'source':'Yahoo Finance'}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--output',default=str(OUT)); args=ap.parse_args()
    model=json.loads(MODEL.read_text(encoding='utf-8'))
    errors=[]; raw={}
    try: raw['tx_night']=fetch_tx_night()
    except Exception as e: errors.append(f'TX night: {e}')
    for key,sym in {'nasdaq':'^IXIC','sox':'^SOX','us10y':'^TNX','brent':'BZ=F','usdtwd':'TWD=X'}.items():
        try: raw[key]=yf_change(sym)
        except Exception as e: errors.append(f'{key}: {e}')
    required=['tx_night','nasdaq','sox','us10y','brent','usdtwd']
    now=datetime.now(TZ)
    if any(k not in raw for k in required):
        out={'version':'market-pulse-v0.6-beta','status':'unavailable','generated_at':now.isoformat(),'errors':errors,'signals':raw}
        Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2)); return 2
    v={k:raw[k]['value'] for k in required}
    v['tx_tech_divergence']=v['tx_night']-(v['nasdaq']+v['sox'])/2
    v['oil_yield_shock']=max(v['brent'],0)*max(v['us10y'],0)
    contributions={}
    pred=model['coef']['intercept']
    for f in model['features']:
        z=(v[f]-model['mean'][f])/model['std'][f]
        c=model['coef'][f]*z; contributions[f]=c; pred+=c
    score=max(0,min(100,50+50*math.tanh(pred/(2*model['score_scale']))))
    if score<=30: state,emoji='偏空','🔴'
    elif score>=70: state,emoji='偏多','🟢'
    else: state,emoji='中性','🟡'
    primary=[v['tx_night'],v['nasdaq'],v['sox']]
    pos=sum(x>0 for x in primary); neg=sum(x<0 for x in primary)
    consistency='高' if max(pos,neg)==3 else ('中' if max(pos,neg)==2 else '低')
    labels={'tx_night':'台指夜盤','nasdaq':'Nasdaq','sox':'費半','us10y':'美債殖利率','brent':'Brent','usdtwd':'USD/TWD','tx_tech_divergence':'台股相對科技股','oil_yield_shock':'油價×殖利率風險'}
    strongest=sorted(contributions.items(),key=lambda kv:abs(kv[1]),reverse=True)[:3]
    reason='、'.join(f"{labels[k]}{'偏多' if c>0 else '偏空'}" for k,c in strongest)
    out={'version':'market-pulse-v0.6-beta','status':'ok','experimental':True,'generated_at':now.isoformat(),
         'score':round(score,1),'state':state,'emoji':emoji,'predicted_tw_close_ret':round(pred,3),
         'consistency':consistency,'reason':reason,'signals':raw,'derived':{k:round(v[k],4) for k in ['tx_tech_divergence','oil_yield_shock']},
         'contributions':{k:round(x,4) for k,x in contributions.items()},'model_trained_through':model['trained_through'],'errors':errors}
    Path(args.output).write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(out,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': sys.exit(main())
