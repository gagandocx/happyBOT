# data/ - market data for the in-sandbox Python backtester

This folder holds the XAUUSD historical tick data used by the Python research
backtester (`python_bt/`) so strategies can be developed and ranked entirely in
the sandbox, without a round-trip to MT5.

## What is tracked vs regenerated

The full compressed tick CSV is too large to commit as one file (GitHub caps a
single file at 100 MB), so it is committed as SPLIT CHUNKS and reassembled on
demand. The chunks are tracked; the reassembled archive and the extracted CSV
are gitignored and regenerated whenever needed.

Tracked in the repo:

```
data/XAUUSD_202607011100_202609011203_2.zip.001
data/XAUUSD_202607011100_202609011203_2.zip.002
data/XAUUSD_202607011100_202609011203_2.zip.003
data/XAUUSD_202607011100_202609011203_2.zip.004
data/XAUUSD_202607011100_202609011203_2.zip.005
```

Regenerated (gitignored, never committed):

```
data/joined.bin                                              (reassembled outer zip)
data/XAUUSD_202607011100_202609011203.zip                    (inner zip)
data/XAUUSD_202607011100_202609011203/XAUUSD_202607011100_202609011203.csv   (526 MB CSV)
```

## Canonical regenerate step: data/extract.py

Run this from the repo root to rebuild the CSV from the tracked chunks (stdlib
only, no external tools needed):

```
python3 data/extract.py
```

What it does:

1. Concatenates the five chunks `..._2.zip.001 .. .005` in numeric order into
   `data/joined.bin` (a ZIP), streaming so it never loads the whole file into
   memory.
2. Extracts `joined.bin` to get the inner zip
   `XAUUSD_202607011100_202609011203.zip`.
3. Extracts the inner zip to produce
   `data/XAUUSD_202607011100_202609011203/XAUUSD_202607011100_202609011203.csv`
   (526 MB, about 11.86M data rows).

It is idempotent: if the CSV already exists and is non-empty it does nothing.
Use `python3 data/extract.py --force` to re-extract, and `--data-dir DIR` to
point at a different chunk directory.

## CSV format (verified)

Tab-separated with CRLF line endings. Header:

```
<DATE>	<TIME>	<BID>	<ASK>	<LAST>	<VOLUME>	<FLAGS>
```

Example row (LAST and VOLUME are often empty; TIME has millisecond precision):

```
2026.07.01	11:00:00.051	3975.95	3976.00			6
```

DATE is YYYY.MM.DD, TIME is HH:MM:SS.mmm. Both BID and ASK are present on every
tick, so the spread is real per tick. The window runs 2026.07.01 11:00 to
2026.09.01 12:03.

## Using the data

Once extracted, `python_bt/loader.py` streams the CSV line by line (with date
slicing and a tick cap), and the runner / research CLIs read it via
`python_bt.runner.DEFAULT_DATA`. See `python_bt/README.md` for how to run a
backtest and the research loop.

Reminder: this Python backtester is for FAST SEARCH only. MT5 remains the source
of truth; validate any promising candidate on a real MT5 run of the same period.
