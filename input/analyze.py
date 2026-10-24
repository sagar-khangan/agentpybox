import csv
from pathlib import Path

with open("sales.csv") as f:
    rows = list(csv.DictReader(f))

total_revenue = 0

for row in rows:
    revenue = int(row["quantity"]) * float(row["price"])
    total_revenue += revenue
    print(f"{row['product']}: Rs {revenue:,.2f}")

report = f"Total Revenue: Rs {total_revenue:,.2f}\n"
Path("report.txt").write_text(report)

print(report)
