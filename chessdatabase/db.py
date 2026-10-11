#!/usr/bin/env python3
"""
csv_parquet_sqlite_converter.py

Convert between CSV, Parquet, and SQLite3 file formats with
threading and parallelism support.

Usage:
  python csv_parquet_sqlite_converter.py data.csv data.parquet
  python csv_parquet_sqlite_converter.py data.csv data.parquet --chunk-size 100000
  python csv_parquet_sqlite_converter.py data.db ./output/ --batch --workers 4
  python csv_parquet_sqlite_converter.py ./csv_dir/ data.db --batch-import --workers 4
"""

import argparse
import csv
import os
import sqlite3
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional, Dict, List, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq


# ---------------------------------------------------------------------------
# Format detection
# ---------------------------------------------------------------------------

FORMAT_MAP = {
    ".csv": "csv",
    ".tsv": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
    ".db": "sqlite",
    ".sqlite": "sqlite",
    ".sqlite3": "sqlite",
}


def detect_format(filepath: str) -> str:
    ext = Path(filepath).suffix.lower()
    fmt = FORMAT_MAP.get(ext)
    if fmt is None:
        raise ValueError(
            f"Unsupported extension '{ext}'. "
            f"Supported: {', '.join(FORMAT_MAP.keys())}"
        )
    return fmt


# ---------------------------------------------------------------------------
# SQLite helpers
# ---------------------------------------------------------------------------

def _list_tables(conn: sqlite3.Connection) -> List[str]:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name NOT LIKE 'sqlite_%';"
    )
    return [row[0] for row in cursor.fetchall()]


def _resolve_table(conn: sqlite3.Connection, table: Optional[str]) -> str:
    if table is not None:
        return table
    tables = _list_tables(conn)
    if len(tables) == 1:
        return tables[0]
    raise ValueError(
        f"SQLite has {len(tables)} tables ({', '.join(tables)}). Specify --table."
    )


# ---------------------------------------------------------------------------
# Full-file readers
# ---------------------------------------------------------------------------

def read_csv(filepath: str, **kwargs) -> pd.DataFrame:
    defaults = {"low_memory": False}
    defaults.update(kwargs)
    return pd.read_csv(filepath, **defaults)


def read_parquet(filepath: str, **kwargs) -> pd.DataFrame:
    return pd.read_parquet(filepath, **kwargs)


def read_sqlite(filepath: str, table: Optional[str] = None, **kwargs) -> pd.DataFrame:
    conn = sqlite3.connect(filepath)
    try:
        table = _resolve_table(conn, table)
        return pd.read_sql_query(f"SELECT * FROM [{table}]", conn, **kwargs)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Full-file writers
# ---------------------------------------------------------------------------

def write_csv(df: pd.DataFrame, filepath: str, **kwargs) -> None:
    defaults = {"index": False, "quoting": csv.QUOTE_NONNUMERIC}
    defaults.update(kwargs)
    df.to_csv(filepath, **defaults)


def write_parquet(df: pd.DataFrame, filepath: str, **kwargs) -> None:
    defaults = {"engine": "pyarrow", "index": False}
    defaults.update(kwargs)
    df.to_parquet(filepath, **defaults)


def write_sqlite(df: pd.DataFrame, filepath: str,
                 table: Optional[str] = None, if_exists: str = "replace",
                 **kwargs) -> None:
    if table is None:
        table = Path(filepath).stem
    conn = sqlite3.connect(filepath)
    try:
        df.to_sql(table, conn, if_exists=if_exists, index=False, **kwargs)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chunked readers
# ---------------------------------------------------------------------------

def read_csv_chunked(filepath: str, chunk_size: int, **kwargs):
    defaults = {"low_memory": False, "chunksize": chunk_size}
    defaults.update(kwargs)
    for chunk in pd.read_csv(filepath, **defaults):
        yield chunk


def read_parquet_chunked(filepath: str, chunk_size: int, **kwargs):
    pf = pq.ParquetFile(filepath)
    for batch in pf.iter_batches(batch_size=chunk_size):
        yield batch.to_pandas()


def read_sqlite_chunked(filepath: str, chunk_size: int,
                        table: Optional[str] = None, **kwargs):
    conn = sqlite3.connect(filepath)
    try:
        table = _resolve_table(conn, table)
        total = pd.read_sql_query(
            f"SELECT COUNT(*) AS cnt FROM [{table}]", conn
        ).iloc[0, 0]
        for offset in range(0, total, chunk_size):
            df = pd.read_sql_query(
                f"SELECT * FROM [{table}] LIMIT {chunk_size} OFFSET {offset}",
                conn,
            )
            if df.empty:
                break
            yield df
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Chunked writers
# ---------------------------------------------------------------------------

def write_csv_chunked(filepath: str, chunks, **kwargs) -> int:
    defaults = {"index": False, "quoting": csv.QUOTE_NONNUMERIC}
    defaults.update(kwargs)
    total = 0
    header = True
    for df in chunks:
        df.to_csv(filepath, mode="a" if not header else "w",
                  header=header, **defaults)
        total += len(df)
        header = False
    return total


def write_parquet_chunked(filepath: str, chunks, **kwargs) -> int:
    compression = kwargs.pop("compression", "snappy")
    total = 0
    writer = None
    for df in chunks:
        table = pa.Table.from_pandas(df, preserve_index=False)
        if writer is None:
            writer = pq.ParquetWriter(filepath, table.schema,
                                      compression=compression)
        writer.write_table(table)
        total += len(df)
    if writer is not None:
        writer.close()
    return total


def write_sqlite_chunked(filepath: str, chunks,
                         table: Optional[str] = None,
                         if_exists: str = "replace", **kwargs) -> int:
    if table is None:
        table = Path(filepath).stem
    total = 0
    first = True
    for df in chunks:
        mode = if_exists if first else "append"
        conn = sqlite3.connect(filepath)
        try:
            df.to_sql(table, conn, if_exists=mode, index=False, **kwargs)
        finally:
            conn.close()
        total += len(df)
        first = False
    return total


# ---------------------------------------------------------------------------
# Sanitize kwargs so writer-specific keys don't leak to wrong writers
# ---------------------------------------------------------------------------

_SQLITE_ONLY_KEYS = {"if_exists", "table"}


def _clean_kwargs(kwargs: Dict, dest_fmt: str) -> Dict:
    """Remove keys that the destination writer cannot accept."""
    out = dict(kwargs)
    if dest_fmt != "sqlite":
        for k in _SQLITE_ONLY_KEYS:
            out.pop(k, None)
    return out


# ---------------------------------------------------------------------------
# Main convert (full-file, loads everything into memory)
# ---------------------------------------------------------------------------

_READERS = {"csv": read_csv, "parquet": read_parquet, "sqlite": read_sqlite}
_WRITERS = {"csv": write_csv, "parquet": write_parquet, "sqlite": write_sqlite}


def convert(
    input_path: str,
    output_path: str,
    table: Optional[str] = None,
    read_kwargs: Optional[Dict] = None,
    write_kwargs: Optional[Dict] = None,
) -> pd.DataFrame:
    src_fmt = detect_format(input_path)
    dst_fmt = detect_format(output_path)

    if src_fmt == dst_fmt:
        raise ValueError(
            f"Same format ({src_fmt}). No conversion needed."
        )

    read_kwargs = read_kwargs or {}
    write_kwargs = write_kwargs or {}

    # Read
    if src_fmt == "sqlite":
        df = _READERS[src_fmt](input_path, table=table, **read_kwargs)
    else:
        df = _READERS[src_fmt](input_path, **read_kwargs)

    # Write — only pass sqlite-specific kwargs when dest is sqlite
    safe_wkwargs = _clean_kwargs(write_kwargs, dst_fmt)
    if dst_fmt == "sqlite":
        _WRITERS[dst_fmt](
            df, output_path, table=table,
            if_exists=write_kwargs.get("if_exists", "replace"),
            **safe_wkwargs,
        )
    else:
        _WRITERS[dst_fmt](df, output_path, **safe_wkwargs)

    return df


# ---------------------------------------------------------------------------
# Chunked convert (memory-efficient)
# ---------------------------------------------------------------------------

_CHUNKED_READERS = {
    "csv": read_csv_chunked,
    "parquet": read_parquet_chunked,
    "sqlite": read_sqlite_chunked,
}


def convert_chunked(
    input_path: str,
    output_path: str,
    table: Optional[str] = None,
    chunk_size: int = 100_000,
    read_kwargs: Optional[Dict] = None,
    write_kwargs: Optional[Dict] = None,
) -> int:
    src_fmt = detect_format(input_path)
    dst_fmt = detect_format(output_path)

    if src_fmt == dst_fmt:
        raise ValueError("Same format. No conversion needed.")

    read_kwargs = read_kwargs or {}
    write_kwargs = write_kwargs or {}

    # Build chunk generator
    if src_fmt == "sqlite":
        chunks = _CHUNKED_READERS[src_fmt](
            input_path, chunk_size, table=table, **read_kwargs
        )
    else:
        chunks = _CHUNKED_READERS[src_fmt](
            input_path, chunk_size, **read_kwargs
        )

    # Write
    safe_wkwargs = _clean_kwargs(write_kwargs, dst_fmt)
    if dst_fmt == "csv":
        return write_csv_chunked(output_path, chunks, **safe_wkwargs)
    elif dst_fmt == "parquet":
        return write_parquet_chunked(output_path, chunks, **safe_wkwargs)
    elif dst_fmt == "sqlite":
        return write_sqlite_chunked(
            output_path, chunks, table=table,
            if_exists=write_kwargs.get("if_exists", "replace"),
            **safe_wkwargs,
        )
    raise ValueError(f"Unsupported dest format: {dst_fmt}")


# ---------------------------------------------------------------------------
# Parallel batch: SQLite DB → directory of files
# ---------------------------------------------------------------------------

def _export_one_table(args_tuple):
    (db_path, table_name, output_file, output_format,
     chunk_size, read_kwargs, write_kwargs) = args_tuple
    try:
        if chunk_size:
            rows = convert_chunked(
                db_path, output_file, table=table_name,
                chunk_size=chunk_size,
                read_kwargs=read_kwargs, write_kwargs=write_kwargs,
            )
        else:
            df = convert(
                db_path, output_file, table=table_name,
                read_kwargs=read_kwargs, write_kwargs=write_kwargs,
            )
            rows = len(df)
        return (table_name, output_file, rows)
    except Exception as exc:
        return (table_name, f"ERROR: {exc}", 0)


def batch_convert_sqlite(
    db_path: str,
    output_dir: str,
    output_format: str = "parquet",
    workers: int = 4,
    chunk_size: Optional[int] = None,
    write_kwargs: Optional[Dict] = None,
) -> Dict[str, str]:
    conn = sqlite3.connect(db_path)
    tables = _list_tables(conn)
    conn.close()

    if not tables:
        raise ValueError(f"No user tables found in '{db_path}'.")

    os.makedirs(output_dir, exist_ok=True)
    ext = ".parquet" if output_format == "parquet" else ".csv"
    write_kwargs = write_kwargs or {}

    task_args = []
    for tbl in tables:
        out_file = os.path.join(output_dir, f"{tbl}{ext}")
        task_args.append(
            (db_path, tbl, out_file, output_format,
             chunk_size, None, write_kwargs)
        )

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_export_one_table, t): t[1] for t in task_args
        }
        for fut in as_completed(futures):
            tbl_name, path, rows = fut.result()
            if isinstance(path, str) and path.startswith("ERROR:"):
                print(f"  ✗ {tbl_name}: {path}", file=sys.stderr)
            else:
                print(f"  ✓ {tbl_name} -> {path}  ({rows:,} rows)")
            results[tbl_name] = path

    return results


# ---------------------------------------------------------------------------
# Parallel batch: directory of files → one SQLite DB
# ---------------------------------------------------------------------------

def _import_one_file(args_tuple):
    (fpath, db_path, tbl, if_exists, chunk_size,
     read_kwargs, write_kwargs) = args_tuple
    try:
        wkwargs = dict(write_kwargs or {})
        wkwargs["if_exists"] = if_exists
        if chunk_size:
            rows = convert_chunked(
                fpath, db_path, table=tbl,
                chunk_size=chunk_size,
                read_kwargs=read_kwargs, write_kwargs=wkwargs,
            )
        else:
            df = convert(
                fpath, db_path, table=tbl,
                read_kwargs=read_kwargs, write_kwargs=wkwargs,
            )
            rows = len(df)
        return (tbl, fpath, rows)
    except Exception as exc:
        return (tbl, f"ERROR: {exc}", 0)


def batch_import_to_sqlite(
    input_dir: str,
    db_path: str,
    input_format: str = "csv",
    workers: int = 4,
    if_exists: str = "replace",
    chunk_size: Optional[int] = None,
    read_kwargs: Optional[Dict] = None,
    write_kwargs: Optional[Dict] = None,
) -> Dict[str, str]:
    ext_match = ".csv" if input_format == "csv" else ".parquet"
    files = sorted(f for f in os.listdir(input_dir) if f.endswith(ext_match))
    if not files:
        raise ValueError(f"No {ext_match} files in '{input_dir}'.")

    read_kwargs = read_kwargs or {}
    write_kwargs = write_kwargs or {}

    task_args = []
    for fname in files:
        fpath = os.path.join(input_dir, fname)
        tbl = Path(fname).stem
        task_args.append(
            (fpath, db_path, tbl, if_exists, chunk_size,
             read_kwargs, write_kwargs)
        )

    results = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_import_one_file, t): t[2] for t in task_args
        }
        for fut in as_completed(futures):
            tbl_name, path, rows = fut.result()
            if isinstance(path, str) and path.startswith("ERROR:"):
                print(f"  ✗ {tbl_name}: {path}", file=sys.stderr)
            else:
                print(f"  ✓ {path} -> {tbl_name}  ({rows:,} rows)")
            results[tbl_name] = path

    return results


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Convert between CSV, Parquet, and SQLite3 "
                    "with threading and parallelism.",
    )
    parser.add_argument("input", help="Input file or directory")
    parser.add_argument("output", help="Output file or directory")
    parser.add_argument("--table", "-t", default=None,
                        help="SQLite table name")
    parser.add_argument("--batch", "-b", action="store_true",
                        help="Batch: export all SQLite tables → files")
    parser.add_argument("--batch-import", action="store_true",
                        help="Batch: import all files in dir → one SQLite DB")
    parser.add_argument("--workers", "-w", type=int, default=4,
                        help="Parallel workers for batch mode (default: 4)")
    parser.add_argument("--chunk-size", "-c", type=int, default=None,
                        help="Chunk size in rows (for large files)")
    parser.add_argument("--if-exists", choices=["fail", "replace", "append"],
                        default="replace",
                        help="SQLite table conflict policy (default: replace)")
    parser.add_argument("--delimiter", "-d", default=None,
                        help="CSV delimiter")
    parser.add_argument("--encoding", "-e", default=None,
                        help="File encoding")
    parser.add_argument("--compression", default="snappy",
                        choices=["snappy", "gzip", "brotli", "zstd", "none"],
                        help="Parquet compression (default: snappy)")

    args = parser.parse_args()

    read_kwargs = {}
    write_kwargs = {"if_exists": args.if_exists}

    if args.encoding:
        read_kwargs["encoding"] = args.encoding
    if args.delimiter:
        read_kwargs["sep"] = args.delimiter
    if args.compression and args.compression != "none":
        write_kwargs["compression"] = args.compression

    # ---- Batch import ----
    if args.batch_import:
        if not os.path.isdir(args.input):
            parser.error("--batch-import requires input to be a directory.")
        # Detect format from first file
        src_fmt = None
        for f in os.listdir(args.input):
            try:
                src_fmt = detect_format(os.path.join(args.input, f))
                break
            except ValueError:
                continue
        if src_fmt is None:
            parser.error("Cannot determine input format.")
        results = batch_import_to_sqlite(
            args.input, args.output, input_format=src_fmt,
            workers=args.workers, if_exists=args.if_exists,
            chunk_size=args.chunk_size,
            read_kwargs=read_kwargs, write_kwargs=write_kwargs,
        )
        print(f"Imported {len(results)} table(s) into '{args.output}'.")
        return

    # ---- Batch export ----
    if args.batch:
        src_fmt = detect_format(args.input)
        if src_fmt != "sqlite":
            parser.error("--batch requires a SQLite input file.")
        if os.path.isdir(args.output) or args.output.endswith(("/", "\\")):
            out_fmt = "parquet"
        else:
            try:
                out_fmt = detect_format(args.output)
            except ValueError:
                out_fmt = "parquet"
        if out_fmt == "sqlite":
            parser.error("Batch output must be a directory.")
        results = batch_convert_sqlite(
            args.input, args.output, output_format=out_fmt,
            workers=args.workers, chunk_size=args.chunk_size,
            write_kwargs=write_kwargs,
        )
        print(f"Exported {len(results)} table(s).")
        return

    # ---- Single-file conversion ----
    try:
        if args.chunk_size:
            total = convert_chunked(
                args.input, args.output, table=args.table,
                chunk_size=args.chunk_size,
                read_kwargs=read_kwargs, write_kwargs=write_kwargs,
            )
            print(f"Converted '{args.input}' -> '{args.output}' "
                  f"({total:,} rows, chunked x{args.chunk_size:,})")
        else:
            df = convert(
                args.input, args.output, table=args.table,
                read_kwargs=read_kwargs, write_kwargs=write_kwargs,
            )
            print(f"Converted '{args.input}' -> '{args.output}' "
                  f"({df.shape[0]:,} rows x {df.shape[1]} cols)")
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()