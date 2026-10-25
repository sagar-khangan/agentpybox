"""Analyze sales data using a registered pandas environment."""

import pandas as pd

sales = pd.read_csv("sales.csv")
customers = pd.read_csv("customers.csv")

sales["revenue"] = sales["quantity"] * sales["price"]

report = sales.merge(
    customers,
    on="customer_id",
    how="left",
    validate="many_to_one",
)

report = report[
    [
        "customer_id",
        "name",
        "city",
        "product",
        "quantity",
        "price",
        "revenue",
    ]
]

report.to_csv("report.csv", index=False)

summary = (
    report.groupby("city", dropna=False)["revenue"]
    .sum()
    .reset_index()
    .sort_values("revenue", ascending=False)
)

summary.to_json("summary.json", orient="records", indent=2)

print(f"pandas version: {pd.__version__}")
print(f"Total sales: {report['revenue'].sum():,.2f}")
print(f"Customers: {report['customer_id'].nunique()}")
print("Generated report.csv and summary.json")
