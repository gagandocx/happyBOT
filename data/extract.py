#!/usr/bin/env python3
"""Regenerate the XAUUSD tick CSV from the tracked split chunks.

The full 526 MB tick CSV is too large to commit, so it is stored as split
byte-chunks (data/XAUUSD_202607011100_202609011203_2.zip.001 .. .005). This
helper reassembles them and extracts the CSV, using ONLY the Python standard
library (zipfile). It is idempotent: if the final CSV already exists and is
non-empty it does nothing unless --force is given.

Nesting (verified in-repo):
  chunks .001..005  --cat in numeric order-->  data/joined.bin  (a ZIP)
  joined.bin        --unzip-->  XAUUSD_202607011100_202609011203.zip  (inner ZIP)
  inner zip         --unzip-->  XAUUSD_202607011100_202609011203/
                                XAUUSD_202607011100_202609011203.csv

Usage:
  python3 data/extract.py [--force] [--data-dir data]
"""

import argparse
import os
import sys
import zipfile

# Base name of the dataset. Chunks, inner zip and the CSV all derive from it.
DATASET = "XAUUSD_202607011100_202609011203"

# The split chunks are named "<DATASET>_2.zip.001" .. ".005".
CHUNK_PREFIX = DATASET + "_2.zip."
NUM_CHUNKS = 5

# Streaming copy buffer (bytes). Keep it modest so we never load the whole file.
_BUFSIZE = 1024 * 1024


def _chunk_paths(data_dir):
    """Return the ordered list of chunk paths (numeric .001 .. .005 order)."""
    return [
        os.path.join(data_dir, "%s%03d" % (CHUNK_PREFIX, i))
        for i in range(1, NUM_CHUNKS + 1)
    ]


def _final_csv_path(data_dir):
    return os.path.join(data_dir, DATASET, DATASET + ".csv")


def _join_chunks(data_dir, joined_path):
    """Concatenate the chunk files in order into joined_path, streaming."""
    chunks = _chunk_paths(data_dir)
    missing = [c for c in chunks if not os.path.isfile(c)]
    if missing:
        raise FileNotFoundError(
            "Missing data chunk(s): %s. Cannot reassemble the CSV." % ", ".join(missing)
        )
    with open(joined_path, "wb") as out:
        for chunk in chunks:
            with open(chunk, "rb") as src:
                while True:
                    buf = src.read(_BUFSIZE)
                    if not buf:
                        break
                    out.write(buf)


def _single_member(zf, expected_suffix):
    """Return the single member of a zip whose name ends with expected_suffix."""
    names = zf.namelist()
    for name in names:
        if name.endswith(expected_suffix):
            return name
    if len(names) == 1:
        return names[0]
    raise ValueError(
        "Could not find a %r member in zip (members: %s)" % (expected_suffix, names)
    )


def extract_csv(data_dir="data", force=False):
    """Regenerate the tick CSV from the tracked chunks and return its path.

    Idempotent: if the CSV already exists and is non-empty, returns it
    immediately unless force is True.
    """
    csv_path = _final_csv_path(data_dir)
    if not force and os.path.isfile(csv_path) and os.path.getsize(csv_path) > 0:
        print("CSV already present, skipping extract: %s" % csv_path)
        return csv_path

    joined_path = os.path.join(data_dir, "joined.bin")
    inner_zip_name = DATASET + ".zip"
    inner_zip_path = os.path.join(data_dir, inner_zip_name)

    print("Reassembling %d chunks -> %s" % (NUM_CHUNKS, joined_path))
    _join_chunks(data_dir, joined_path)

    # Level 1: joined.bin is a ZIP whose single member is the inner zip.
    print("Opening %s (outer zip)" % joined_path)
    with zipfile.ZipFile(joined_path, "r") as outer:
        member = _single_member(outer, inner_zip_name)
        outer.extract(member, path=data_dir)
    if not os.path.isfile(inner_zip_path):
        # The member may have carried a subpath; fall back to whatever was
        # produced that matches the inner zip name.
        raise FileNotFoundError(
            "Expected inner zip at %s after extracting outer archive" % inner_zip_path
        )

    # Level 2: inner zip whose single member is the CSV (under a subdir).
    print("Opening %s (inner zip)" % inner_zip_path)
    with zipfile.ZipFile(inner_zip_path, "r") as inner:
        member = _single_member(inner, DATASET + ".csv")
        inner.extract(member, path=data_dir)

    if not os.path.isfile(csv_path) or os.path.getsize(csv_path) == 0:
        raise RuntimeError("Extraction finished but CSV is missing/empty: %s" % csv_path)

    size = os.path.getsize(csv_path)
    first_line = ""
    with open(csv_path, "r", newline="") as fh:
        fh.readline()  # header
        first_line = fh.readline().rstrip("\r\n")
    print("Extracted CSV: %s" % csv_path)
    print("Size: %d bytes (%.1f MB)" % (size, size / (1024.0 * 1024.0)))
    print("First data line: %s" % first_line)
    return csv_path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Regenerate the XAUUSD tick CSV from tracked chunks.")
    parser.add_argument("--force", action="store_true", help="re-extract even if the CSV already exists")
    parser.add_argument("--data-dir", default="data", help="directory holding the chunks (default: data)")
    args = parser.parse_args(argv)
    try:
        extract_csv(data_dir=args.data_dir, force=args.force)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
