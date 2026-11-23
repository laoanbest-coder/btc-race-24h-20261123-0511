# BTC Race Bot — btc-race-24h-20261123-0511

A long-only trend-following bot for make.fun's "Race a BTC trading bot live for
24 hours" bounty. It trades cbBTC/USDC on 1-minute bars from the Orca Whirlpool,
starting with $1,000 of paper money, under the `agent-fun/bars-replay/v1`
protocol (newline-delimited JSON on stdin/stdout).

## Strategy

- **Enter** (whole equity, one open position at most) when a fresh uptrend is
  confirmed: fast EMA(12) above slow EMA(26) on a cross within the last 60
  bars, close above the long trend EMA(120), and trailing 60-bar momentum above
  +0.30%.
- **Exit** only on a hard stop (2% below the entry fill) or a trailing stop (2%
  below the peak since entry). There is deliberately no exit on an EMA
  cross-down: on 1-minute bars that fires on noise, and each full-size round
  trip costs about 46 bps in fees, slippage and price impact on this pool, so
  churning through chop is how bots lose. A 120-bar cooldown follows an exit.
- **Deterministic**: integer/float math only; no clock, no network, no files,
  no randomness. Two runs on the same window produce byte-identical replies.

## Files

- `main.py` — the bot (Python 3.13, standard library only)
- `vendor/makefun_bars.py` — byte-identical copy of the kit's Python SDK shim
- `LICENSE` — MIT
- `.makefun/owner.json` — entry claim file

## Dev-window result (kit's frozen 24 h window, 1,440 bars)

Local replay with the kit harness's exact fill model (validated to the
micro-unit against the kit's `grade-local` on the buy-and-hold and momentum
baselines):

- **Net PnL: +$26.84 (+2.68%)**, 1 trade, fees $0.81, max drawdown 1.98%
- No rejected orders; two subprocess runs produce byte-identical action logs
- For comparison on the same window: buy-and-hold +$32.17, momentum +$34.94,
  house ema-cross −$114.83 (76 trades), adx-momentum −$11.20, rsi-bollinger
  −$9.32, hold-cash $0.00

Note: the kit's `grade-local --driver process` runs Node bots only — a Python
bot grades inside Docker, which is not available on the build machine — so the
dev grade above comes from the validated local replay plus an end-to-end wire
test of `main.py` run exactly as the grader runs it
(`python3 -P -s main.py`, `PYTHONHASHSEED=0`). The server's dev grade on
submission is the authority.

## Grade locally

```sh
# with the kit unpacked next to this repo:
node cli/makefun.mjs grade-local --kit <kit-dir> --bot <this-repo> --driver docker
```

## Tuning notes

Parameter grids were run over EMA spans, momentum thresholds, stop/trail
widths, cooldowns and exit rules. The chosen parameters sit in the middle of a
wide profitable region (hundreds of nearby combinations also clear the dev
gate), not on a single best cell: the race window is unseen data, so robustness
was picked over the maximum dev score. Splitting the dev window in half, the
same parameters make +$22.64 on the first half (the big up-move) and +$0.56 on
the choppy second half.

[![make.fun · btc-race-24h-20261123-0511](https://make.fun/badge/btc-race-24h-20261123-0511.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![rank](https://make.fun/badge/btc-race-24h-20261123-0511/laoanbest-coder/btc-race-24h-20261123-0511/rank.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
[![reward](https://make.fun/badge/btc-race-24h-20261123-0511/laoanbest-coder/btc-race-24h-20261123-0511/reward.svg)](https://make.fun/bounty/btc-race-24h-20261123-0511?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261123-0511)
