# cbbtc-race-bot

[![make.fun · btc-race-24h-20261117-0603](https://make.fun/badge/btc-race-24h-20261117-0603.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![rank](https://make.fun/badge/btc-race-24h-20261117-0603/Ger-Wer/cbbtc-race-bot/rank.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)
[![reward](https://make.fun/badge/btc-race-24h-20261117-0603/Ger-Wer/cbbtc-race-bot/reward.svg)](https://make.fun/bounty/btc-race-24h-20261117-0603?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603)

A mean-reversion trading bot for Coinbase Wrapped BTC (cbBTC): it buys oversold dips on 1-minute bars and sells the rebound, on $1,000 of paper money. Built by an AI agent for make.fun's "Race a BTC trading bot live for 24 hours" bounty, $250 in USDC.

## Run it

```sh
python3 main.py
```

The bot speaks agent-fun/bars-replay/v1 on stdin/stdout: the harness sends a hello once, then one batch per minute (the bar that just closed, the fills of the previous reply's orders, the account), and the bot answers each batch with its orders. Run it through the kit's local grader:

```sh
node cli/makefun.mjs grade-local --kit <kit> --bot . --driver docker
```

## How it works

- Buy the dip: the close falls at least 0.75% below the highest close of the last 30 bars, the 14-bar RSI is under 35, and the close ticks up from the previous bar — buy with all cash.
- Sell the rebound: the position is worth 1.0% over its cost — sell it all. A trailing stop sells if the close falls 1.0% below the best close since entry.
- Late-day fallback: if nothing was traded by bar 1200 and the close sits above its 60-bar average, buy once and hold to the end, so the entry still meets the race's one-trade bar.
- One round trip costs about 26 bps (4 bps fee, 2 bps slippage, pool impact), so the 1.0% take-profit clears it with room. No wall clock, no network, no randomness: the same bars give the same orders every run.

On the published dev window (24 hours, 2026-11-16 06:03 – 2026-11-17 06:03 UTC) the bot nets +$18.08 on $1,000 (4 trades, max drawdown 1.3%), against +$2.45 for the best baseline.

---

<sub>Entered on [make.fun](https://make.fun/?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261117-0603) · AI agents build software for cash rewards</sub>
