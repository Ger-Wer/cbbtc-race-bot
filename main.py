"""cbbtc-race-bot: a mean-reversion bot for cbBTC on 1-minute bars.

Strategy (long only, one position, full size):
  - Buy the dip: when the close falls at least 0.75% below the highest close
    of the last 30 bars, the 14-bar RSI is under 35 (oversold), and the close
    ticks up from the previous bar (confirmation), buy with all cash.
  - Sell the rebound: when the position is worth 1.0% over its cost, sell it
    all. A trailing stop sells if the close falls 1.0% below the best close
    seen since entry, so a dip that keeps dipping costs at most about 1%.
  - Late-day fallback: if no dip ever came and nothing was traded by bar
    1200 (four hours left), buy once when the close sits above its 60-bar
    average, so the entry still meets the race's one-trade bar instead of
    sitting in cash all day. On a day with dips this never fires.
  - One trade costs about 26 bps round-trip (4 bps fee, 2 bps slippage,
    ~13-20 bps of pool impact at full size), so a trade needs a move bigger
    than that; the 1.0% take-profit clears it with room.

The bot speaks agent-fun/bars-replay/v1: the harness sends a hello once,
then one batch per bar (the bar that just closed, the fills of the previous
reply's orders, the account), and the bot answers every batch with exactly
one reply carrying its orders (at most one order here). Orders decided on a
batch fill at the next bar's open. No wall clock, no network, no files
outside the repository, no randomness: the same bars give the same orders
every run, so two executions produce byte-identical action logs.

Only the standard library is used. The wire shim lives in
vendor/makefun_bars.py (a byte-for-byte copy of the kit's SDK).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
# Entry: the close is this far below the highest close of the last LOOKBACK bars.
DROP_BPS = 75            # 0.75%
LOOKBACK_BARS = 30
# Entry: the 14-bar Wilder RSI is under this (oversold).
RSI_BARS = 14
RSI_MAX = 35.0
# Exit: the position is worth this much over its cost (take-profit).
TAKE_PROFIT_BPS = 100    # 1.0%
# Exit: the close falls this far below the best close since entry (stop).
STOP_BPS = 100           # 1.0%
# Fallback: the first batch on which the bot buys late in the day if it has
# never held a position (four hours left at bar 1200 of 1440).
FALLBACK_BAR = 1200
FALLBACK_EMA_BARS = 60
# The market refuses a fill that moves more than this past the latest close.
MAX_SLIPPAGE_BPS = 100

# Every close seen so far, oldest first (ints, the bar's raw close).
closes = []
# RSI state (Wilder's smoothing, float64, exactly as the kit's rsi-bollinger).
_rsi_first = []          # the first RSI_BARS changes, while the averages are not set
_rsi_gain = None         # average gain per bar, once set
_rsi_loss = None         # average loss per bar, once set
# The best close seen since the current position was entered (0 when flat).
peak_close = 0
# True once the bot has ever held a position (a fill landed).
ever_held = False


def ema_last(span):
    """The EMA of the closes seen so far over `span` bars, or None."""
    if len(closes) < span:
        return None
    value = sum(closes[:span]) / span
    k = 2.0 / (span + 1)
    for c in closes[span:]:
        value += k * (c - value)
    return value


def rsi_push(close):
    """Fold a close into the RSI state; return the RSI after it, or None."""
    global _rsi_gain, _rsi_loss
    if not closes:
        return None
    prev = closes[-1]
    change = float(close - prev)
    if _rsi_gain is None or _rsi_loss is None:
        _rsi_first.append(change)
        if len(_rsi_first) < RSI_BARS:
            return None
        gain = sum(c for c in _rsi_first if c > 0) / RSI_BARS
        loss = sum(-c for c in _rsi_first if c < 0) / RSI_BARS
        _rsi_gain, _rsi_loss = gain, loss
    else:
        _rsi_gain = (_rsi_gain * (RSI_BARS - 1) + (change if change > 0 else 0.0)) / RSI_BARS
        _rsi_loss = (_rsi_loss * (RSI_BARS - 1) + (-change if change < 0 else 0.0)) / RSI_BARS
    moved = _rsi_gain + _rsi_loss
    return 50.0 if moved == 0 else 100.0 * _rsi_gain / moved


def on_batch(state, batch):
    """Decide the orders for this batch (one bar of CBBTC)."""
    global peak_close, ever_held
    if state.warming_up:
        return []
    bar = None
    for b in batch["bars"]:
        if b["symbol"] == SYMBOL:
            bar = b
            break
    if bar is None:
        return []  # no bar for CBBTC this minute: nothing to decide on
    close = int(bar["c"])
    rsi = rsi_push(close)
    closes.append(close)

    held = state.positions.get(SYMBOL)
    if held is not None:
        ever_held = True
        if close > peak_close:
            peak_close = close
        value = state.value(SYMBOL, held.qty)
        # Take the profit: the position is worth TAKE_PROFIT_BPS over its cost.
        if value * 10_000 >= held.cost * (10_000 + TAKE_PROFIT_BPS):
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        # Stop out: the close fell STOP_BPS below the best close since entry.
        if peak_close and close * 10_000 < peak_close * (10_000 - STOP_BPS):
            return [{"side": "sell", "symbol": SYMBOL, "qty": held.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    # Flat: look for an oversold dip to buy.
    if len(closes) >= LOOKBACK_BARS and rsi is not None:
        high = max(closes[-LOOKBACK_BARS:])
        dip = close * 10_000 <= high * (10_000 - DROP_BPS)
        oversold = rsi < RSI_MAX
        turning_up = close > closes[-2]
        if dip and oversold and turning_up:
            return buy_all(state, close)
    # Late-day fallback: never traded and four hours left, the close above
    # its 60-bar average (not a downtrend), so buy once and hold to the end.
    if not ever_held and batch["seq"] >= FALLBACK_BAR:
        average = ema_last(FALLBACK_EMA_BARS)
        if average is not None and close > average:
            return buy_all(state, close)
    return []


def buy_all(state, close):
    """Buy with all cash (within the weight cap), tracking the entry peak."""
    global peak_close
    peak_close = close
    notional = state.cash
    room = state.weight_room(SYMBOL)
    if room < notional:
        notional = room
    if notional < int(state.hello["fees"]["min_notional_quote_units"]):
        return []
    return [{"side": "buy", "symbol": SYMBOL,
             "notional_quote_units": notional,
             "max_slippage_bps": MAX_SLIPPAGE_BPS}]


makefun_bars.run(on_batch)
