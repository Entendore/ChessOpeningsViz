import pyarrow.parquet as pq
import random
from pathlib import Path

parquet_files = [
    "lichess_db_puzzle.parquet",
    "lichess_db_openings.parquet"
]

output_lines = []

for parquet_file in parquet_files:
    output_lines.append(f"{'=' * 60}")
    output_lines.append(f"FILE: {parquet_file}")
    output_lines.append(f"{'=' * 60}")

    # Load parquet file
    pf = pq.ParquetFile(parquet_file)

    # Column names
    output_lines.append("\nColumns:")
    for name in pf.schema.names:
        output_lines.append(f"- {name}")

    # Read table
    table = pf.read()

    # Convert to rows
    rows = table.to_pylist()

    # Random row
    if rows:
        random_row = random.choice(rows)

        output_lines.append("\nRandom Row:")
        for k, v in random_row.items():
            output_lines.append(f"{k}: {v}")
    else:
        output_lines.append("\nNo rows found.")

    output_lines.append("\n")

# Write output to file
output_file = "parquet_summary.txt"

with open(output_file, "w", encoding="utf-8") as f:
    f.write("\n".join(output_lines))

print(f"Output written to: {output_file}")