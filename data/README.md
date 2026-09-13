# data/ — market data for the in-sandbox Python backtester

This folder holds the XAUUSD historical data used by the (upcoming) Python
research backtester so strategies can be developed and ranked entirely in the
sandbox, without a round-trip to MT5.

## Drop your split archive chunks here

The full compressed tick CSV is too large to commit as one file (GitHub caps a
single file at 100 MB). So it is committed as **split chunks** and reassembled
on the sandbox side.

Put the chunk files in this folder and commit them, e.g.:

```
data/xauusd_ticks.zip.001
data/xauusd_ticks.zip.002
data/xauusd_ticks.zip.003
data/xauusd_ticks.zip.004
```

(Names may differ depending on how you split — that is fine; just tell me the
exact filenames and which tool you used.)

### IMPORTANT: keep each chunk UNDER ~90 MB

GitHub rejects any single file over 100 MB. When you split, choose a volume
size around **20-50 MB** so every part commits cleanly with margin.

## How the chunks get reassembled (sandbox side, done by Kiro)

The reassembly command depends on HOW you split the file:

- **7-Zip "split to volumes" (`.7z.001/.002` or `.zip.001/.002`):** the parts
  are a raw byte split. Reassemble by concatenating in order, then extract:
  `cat data/*.001 data/*.002 ... > joined.zip` (or `copy /b` on Windows), then unzip.
- **WinRAR multi-volume (`.part1.rar`, `.part2.rar`):** do NOT cat these; they
  are a true multi-volume RAR — extract `part1` with `unrar`/7-Zip and it pulls
  in the rest automatically.
- **`split` / manual byte split:** `cat` the parts back in order.

So when you commit the chunks, tell me:
1. The exact filenames (a `dir data` listing).
2. Which tool made them (7-Zip? WinRAR? something else?).
3. The split/volume method (byte-split "volumes" vs multi-volume archive).

That tells me the correct reassembly command so I don't corrupt the join.

## Even simpler alternative: M1 bar CSV (recommended)

A month of XAUUSD **M1 bars is only a few MB** (vs the ~500 MB tick file /
~89 MB compressed). It is small enough to commit as a single file, needs no
splitting at all, and is plenty accurate to DEVELOP and RANK strategies. Real
ticks are only needed later to VALIDATE the single winning strategy, and that
validation runs on your own MT5 (which already has the ticks).

To export M1 bars: MT5 -> press **F2** (History Center) -> **XAUUSD -> 1 Minute
(M1)** -> **Export** -> save as `.csv` -> drop it here as e.g.
`data/xauusd_m1.csv`.

## After the data is in, paste the format

Whatever you send (ticks or M1 bars), also paste the **first ~5 lines** of the
CSV so the loader can be written to match your exact column layout (MT5 export
columns vary by build).
