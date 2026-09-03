"""
Seed synthetic RevenueRescueAI demo data into MongoDB.

Usage (from backend folder, with backend/.env configured):
    python seed_demo_data.py <BUSINESS_ID>

Example:
    python seed_demo_data.py 6a9936aab4dd765bdc4ba7d4

This script creates Transactions first, then matching FailedPayments records.
It only creates synthetic/demo data. It does not require Razorpay credentials.
"""

import csv
import sys
from datetime import datetime, timezone

from bson import ObjectId
from pymongo import MongoClient

from app.config import settings


CSV_FILE = "../dataset/sample_failed_payments.csv"


def parse_dt(value):
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def main():
    if len(sys.argv) != 2:
        print("Usage: python seed_demo_data.py <BUSINESS_ID>")
        raise SystemExit(1)

    try:
        business_id = ObjectId(sys.argv[1])
    except Exception:
        print("Invalid BUSINESS_ID. Copy the business_id shown after registration.")
        raise SystemExit(1)

    client = MongoClient(settings.MONGO_URI)
    db = client[settings.MONGO_DB_NAME]

    csv_path = __import__("pathlib").Path(__file__).resolve().parent / CSV_FILE
    if not csv_path.exists():
        print(f"Dataset not found: {csv_path}")
        raise SystemExit(1)

    # Remove only records created by this demo seed, for safe re-runs.
    old_orders = [d["_id"] for d in db.transactions.find(
        {"business_id": business_id, "razorpay_order_id": {"$regex": "^demo_order_"}}, {"_id": 1}
    )]
    if old_orders:
        db.failed_payments.delete_many({"business_id": business_id, "transaction_id": {"$in": old_orders}})
        db.transactions.delete_many({"_id": {"$in": old_orders}})

    transactions = []
    failed_payments = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tx_id = ObjectId()
            detected_at = parse_dt(row["detected_at"])
            transaction = {
                "_id": tx_id,
                "business_id": business_id,
                "customer": {
                    "customer_id": row["customer_id"],
                    "name": row["customer_name"],
                    "email": row["customer_email"],
                    "phone": row["customer_phone"],
                    "timezone": "Asia/Kolkata",
                },
                "razorpay_order_id": f"demo_order_{row['demo_id']}",
                "razorpay_payment_id": f"demo_payment_{row['demo_id']}",
                "type": "payment",
                "status": "failed",
                "amount": int(row["amount_paise"]),
                "currency": row["currency"],
                "payment_method": row["payment_method"],
                "error_code": row["raw_error_code"],
                "error_reason": row["failure_reason_category"].replace("_", " "),
                "metadata": {"demo": True, "dataset": "sample_failed_payments"},
                "raw_webhook_payload": None,
                "occurred_at": detected_at,
                "created_at": detected_at,
            }
            transactions.append(transaction)

            fp = {
                "_id": ObjectId(),
                "business_id": business_id,
                "transaction_id": tx_id,
                "customer": transaction["customer"],
                "source_type": row["source_type"],
                "amount": int(row["amount_paise"]),
                "currency": row["currency"],
                "failure_reason_category": row["failure_reason_category"],
                "raw_error_code": row["raw_error_code"],
                "retry_attempts_count": int(row["retry_attempts_count"]),
                "status": row["status"],
                "recovered_amount": (
                    int(row["recovered_amount_paise"]) if row["recovered_amount_paise"] else None
                ),
                "recovered_at": parse_dt(row["recovered_at"]),
                "detected_at": detected_at,
                "updated_at": parse_dt(row["recovered_at"]) or detected_at,
            }
            failed_payments.append(fp)

    if transactions:
        db.transactions.insert_many(transactions)
    if failed_payments:
        db.failed_payments.insert_many(failed_payments)

    print(f"Inserted {len(transactions)} demo transactions.")
    print(f"Inserted {len(failed_payments)} demo failed-payment records.")
    print("Refresh the RevenueRescueAI dashboard.")


if __name__ == "__main__":
    main()
