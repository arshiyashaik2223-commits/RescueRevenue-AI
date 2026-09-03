# RevenueRescueAI – Demo Dataset

This folder contains **synthetic payment-failure data** for demonstrating the RevenueRescueAI analytics dashboard.

## Files

- `sample_failed_payments.csv` – 50 synthetic failed-payment cases.
- `seed_demo_data.py` – inserts the CSV data into MongoDB as `transactions` and `failed_payments`.

## Important

The dataset contains no real customer/payment information and no secrets.

## Run the seed

1. Keep the RevenueRescueAI backend `.env` configured with your working MongoDB connection.
2. Copy `seed_demo_data.py` into the `backend` folder, or run it from there.
3. Activate the backend virtual environment.
4. Run:

```powershell
python seed_demo_data.py YOUR_BUSINESS_ID
```

Use the `business_id` printed by the registration endpoint for your account.

Then refresh the frontend dashboard.

The script is safe to re-run: it removes only previous records whose Razorpay order IDs start with `demo_order_`.
