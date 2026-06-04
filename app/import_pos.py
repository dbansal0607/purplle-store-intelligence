# FIXES APPLIED: BUG #3, BUG #8 — Timezone conversions for IST -> UTC naive datetime and direct database insertion (removed inflated duplication logic).

import os
import sys
import pandas as pd
from datetime import datetime, timezone, timedelta

# Add parent directory to path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal, PosTransactionModel, init_db

# Indian Standard Time offset (UTC+5:30)
IST = timezone(timedelta(hours=5, minutes=30))

def import_csv(csv_path):
    print(f"Reading POS transactions from {csv_path}...")
    if not os.path.exists(csv_path):
        print(f"Error: {csv_path} not found.")
        return
        
    df = pd.read_csv(csv_path)
    
    # Initialize database
    init_db()
    db = SessionLocal()
    
    # Clear existing transactions to prevent unique key violations on re-run
    db.query(PosTransactionModel).delete()
    db.commit()
    
    imported = 0
    
    for idx, row in df.iterrows():
        # Parse timestamp from order_date and order_time (format: 10-04-2026 and 12:15:05)
        date_str = str(row['order_date']).strip()
        time_str = str(row['order_time']).strip()
        
        try:
            # Parse as local IST timezone and convert to naive UTC for storage
            dt_ist = datetime.strptime(f"{date_str} {time_str}", "%d-%m-%Y %H:%M:%S").replace(tzinfo=IST)
            dt_utc = dt_ist.astimezone(timezone.utc).replace(tzinfo=None)
        except Exception as e:
            print(f"Skipping row {idx} due to date parsing error: {e}")
            continue
            
        # Map CSV store codes to match pipeline store IDs
        STORE_ID_MAP = {
            "ST1008": "STORE_BLR_001"
        }
        orig_store_id = str(row['store_id']).strip()
        mapped_store_id = STORE_ID_MAP.get(orig_store_id, orig_store_id)
        order_id = str(row['order_id']).strip()
        product_id = str(row['product_id']).strip()
        brand_name = str(row['brand_name']).strip()
        total_amount = float(row['total_amount'])
        
        # BUG #8 Fix: Do not duplicate transactions 3 times. Write only the original mapped store_id record.
        tx = PosTransactionModel(
            order_id=order_id,
            order_timestamp=dt_utc,
            store_id=mapped_store_id,
            product_id=product_id,
            brand_name=brand_name,
            total_amount=total_amount
        )
        db.add(tx)
        imported += 1
        
    db.commit()
    db.close()
    print(f"Imported {imported} POS transaction records successfully mapped into database in naive UTC.")

if __name__ == "__main__":
    csv_file = "POS - sample transactionsb1e826f.csv"
    import_csv(csv_file)
