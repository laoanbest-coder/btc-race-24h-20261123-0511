"""BTC trend bot for make.fun btc-race-24h-20261123-0511 (agent-fun/bars-replay/v1).

Long-only trend follower on 1-minute cbBTC/USDC bars, $1,000 paper money. It buys
the whole equity when a fresh uptrend is confirmed (fast EMA above slow EMA, close
above the long trend EMA, trailing momentum positive) and exits only on a hard stop
or a trailing stop. It trades rarely: a full-size round trip costs about 46 bps
in fees, slippage and price impact on this pool, so only multi-hour moves are worth
catching, and a cross-down exit was tested and removed because it churns on noise.
Deterministic: integer/float math only, no clock, no network, no files, no randomness.

Strategy parameters live in PARAMS below; the replay harness in the kit grades it
on the frozen 24 h dev window before it can race.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"

# Strategy parameters (tuned on the dev window; see DESIGN.md for the grid).
# Chosen from the middle of a wide good region, not the single best cell:
# entry on a fresh EMA cross + close above the 120-bar trend EMA + 60-bar
# momentum above 0.30%; exit only on a 2% hard stop or a 2% trailing stop.
# A cross-down exit was tested and REMOVED: on 1-minute bars it fires on noise
# and churns (the first grid's best was -$42 on 30 trades); the wide stops are
# what keep a position through normal chop while capping a real reversal.
PARAMS = {
    "fast_span": 12,        # fast EMA span (bars)
    "slow_span": 26,        # slow EMA span (bars)
    "long_span": 120,       # long trend EMA span (bars)
    "mom_lookback": 60,     # trailing momentum lookback (bars)
    "mom_min_bps": 30,      # min trailing momentum to enter (bps)
    "cross_fresh_bars": 60, # enter only if the fast/slow cross happened this recently
    "new_high_bars": 0,     # enter only on a new high of this many bars (0 = off)
    "stop_bps": 200,        # hard stop below entry fill price (bps)
    "trail_bps": 200,       # trailing stop below the peak since entry (bps)
    "cooldown_bars": 120,   # bars after an exit during which no new entry is taken
    "long_exit": False,     # also exit when the close falls under the long EMA
    "max_slippage_bps": 100,  # 1% past the latest close, either side
}


class Ema:
    """One EMA over closes: seeded as the mean of its first span, then the usual
    2 / (span + 1) recursion. Float64, same arithmetic every run."""

    def __init__(self, span):
        self.span = span
        self.warm = []
        self.value = None

    def push(self, close):
        if self.value is not None:
            self.value += (2.0 / (self.span + 1)) * (close - self.value)
            return
        self.warm.append(close)
        if len(self.warm) == self.span:
            self.value = sum(self.warm) / self.span

    @property
    def ready(self):
        return self.value is not None


class TrendBot:
    """Per-run strategy state: EMAs, close history, and the open position's bookkeeping."""

    def __init__(self, params):
        self.p = params
        self.fast = Ema(params["fast_span"])
        self.slow = Ema(params["slow_span"])
        self.long = Ema(params["long_span"])
        self.closes = []          # closes (int, price_scale units) in bar order
        self.prev_gap = None      # fast - slow after the previous bar
        self.cross_bar = None     # index of the latest fast-above-slow cross
        self.bars_since_exit = 10 ** 9  # bars since the last filled sell
        self.entry_close = None   # fill price of the current position
        self.peak_close = None    # highest close since entry

    def on_close(self, close):
        """Fold one bar's close in; returns the fast-minus-slow gap after this bar."""
        self.closes.append(close)
        self.bars_since_exit += 1
        self.fast.push(close)
        self.slow.push(close)
        self.long.push(close)
        gap = None
        if self.fast.ready and self.slow.ready:
            gap = self.fast.value - self.slow.value
            if self.prev_gap is not None and gap > 0 and self.prev_gap <= 0:
                self.cross_bar = len(self.closes) - 1
            self.prev_gap = gap
        return gap

    def momentum_bps(self):
        """Trailing return over mom_lookback bars, in bps (integer math)."""
        n = self.p["mom_lookback"]
        if len(self.closes) <= n:
            return None
        then = self.closes[-1 - n]
        now = self.closes[-1]
        if then <= 0:
            return None
        return (now - then) * 10000 // then

    def trend_up(self):
        """True when the trend filters all point up on the latest close."""
        if self.bars_since_exit < self.p["cooldown_bars"]:
            return False
        if not (self.fast.ready and self.slow.ready and self.long.ready):
            return False
        if self.fast.value <= self.slow.value:
            return False
        if self.closes[-1] <= self.long.value:
            return False
        mom = self.momentum_bps()
        if mom is None or mom < self.p["mom_min_bps"]:
            return False
        if self.cross_bar is None:
            return False
        age = (len(self.closes) - 1) - self.cross_bar
        if age > self.p["cross_fresh_bars"]:
            return False
        n = self.p["new_high_bars"]
        if n > 0:
            window = self.closes[-1 - n:-1]
            if len(window) < n or self.closes[-1] <= max(window):
                return False
        return True

    def should_exit(self, close, held_value, held_cost):
        """True when the open position must be sold at this close. Only the stops
        exit a position: a 2% hard stop under the entry fill, a 2% trailing stop
        under the peak since entry, and (if enabled) a close under the long EMA.
        There is deliberately no exit on a fast/slow cross-down: on 1-minute bars
        that fires on noise and churns the account through 46 bps round trips."""
        if self.p["long_exit"] and self.long.ready and close < self.long.value:
            return True
        if self.entry_close is not None:
            if close * 10000 <= self.entry_close * (10000 - self.p["stop_bps"]):
                return True
        if self.peak_close is not None:
            if close * 10000 <= self.peak_close * (10000 - self.p["trail_bps"]):
                return True
        return False


BOT = TrendBot(PARAMS)


def reset_bot(params=None):
    """Fresh strategy state (used by the local replay harness to grid-search
    parameters; the graded runs always use the module-level PARAMS)."""
    global BOT
    BOT = TrendBot(params if params is not None else PARAMS)
    return BOT


def on_batch(state, batch):
    """Decide this batch's orders. One reply per batch; sells first, then at most
    one buy (one open position max). Orders decided here fill at the next bar's open."""
    # Fold in this batch's fills first: a filled buy sets the position's cost basis
    # (its fill price); a filled sell clears it. A rejected order changes nothing,
    # so its trigger is still live on the next bar and is simply sent again.
    for f in batch["fills"]:
        if f["symbol"] != SYMBOL or f["status"] != "filled":
            continue
        if f["side"] == "buy":
            BOT.entry_close = int(f["price"])
            BOT.peak_close = int(f["price"])
        else:
            BOT.entry_close = None
            BOT.peak_close = None
            BOT.bars_since_exit = 0
    bar = None
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            bar = b
            break
    if bar is None:
        return []  # no bar for our symbol this minute: nothing to decide on
    close = int(bar["c"])
    BOT.on_close(close)
    if state.warming_up:
        return []  # warm-up bars seed history; orders on them would be rejected

    held = state.positions.get(SYMBOL)
    orders = []
    if held is not None:
        # Track the peak since entry for the trailing stop.
        if BOT.peak_close is None or close > BOT.peak_close:
            BOT.peak_close = close
        value = state.value(SYMBOL, held.qty)
        if BOT.should_exit(close, value, held.cost):
            orders.append({
                "side": "sell",
                "symbol": SYMBOL,
                "qty": held.qty,
                "max_slippage_bps": PARAMS["max_slippage_bps"],
            })
        return orders

    # Flat: enter only on a confirmed fresh uptrend.
    if BOT.trend_up():
        room = state.weight_room(SYMBOL)
        amount = state.cash if state.cash < room else room
        min_notional = int(state.hello["fees"]["min_notional_quote_units"])
        if amount >= min_notional and amount > 0:
            orders.append({
                "side": "buy",
                "symbol": SYMBOL,
                "notional_quote_units": amount,
                "max_slippage_bps": PARAMS["max_slippage_bps"],
            })
    return orders


if __name__ == "__main__":
    makefun_bars.run(on_batch)
