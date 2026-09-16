# V2.44.7 BETA — 結構品質標籤修正

本版只修正「💎 結構品質佳」的觸發語意，不改 VCP 分數、雷達篩選、排序或 Pulse 分數。

## 修正
- V2.44.6：結構品質佳還要求「今天突破或仍在 Pivot 下方 5% 內」，導致已突破 D+N 的好型態失去標籤。
- V2.44.7：結構品質只看型態本身：
  - 中期趨勢成立
  - 至少 2 次 contraction
  - contraction regression slope < 0 且最後一波小於第一波
  - 量縮
  - ATR20 / ATR60 <= 1.00
  - Pivot 有效
- Pivot / 突破階段仍由原本 near / breakout / postbreakout / extended 狀態獨立顯示。

## 上傳
替換 BETA 的：
- `scanner.py`
- `index.html`

然後跑一次 BETA 正常掃描 workflow 重新產生 `screening.json`。
