import os
import uuid
import random
import sqlite3
from datetime import datetime, timedelta

def seed_events():
    db_path = "store_intelligence.db"
    print(f"Connecting to database at {db_path}...")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Clear existing events
    print("Clearing existing events...")
    cursor.execute("DELETE FROM events")
    
    # 1. Check if we need to seed STORE_BLR_002 transactions
    # Let's seed some transactions for STORE_BLR_002 if none exist
    cursor.execute("SELECT COUNT(*) FROM pos_transactions WHERE store_id = 'STORE_BLR_002'")
    st2_count = cursor.fetchone()[0]
    if st2_count == 0:
        print("Seeding sample transactions for STORE_BLR_002...")
        base_time = datetime(2026, 4, 10, 6, 50, 0)
        for i in range(30):
            tx_time = base_time + timedelta(minutes=random.randint(0, 500))
            order_id = f"TX_BLR2_{1000 + i}"
            cursor.execute(
                "INSERT INTO pos_transactions (order_id, order_timestamp, store_id, product_id, brand_name, total_amount) VALUES (?, ?, ?, ?, ?, ?)",
                (order_id, tx_time.strftime("%Y-%m-%d %H:%M:%S"), "STORE_BLR_002", f"prod_{i}", "Faces Canada", 450.0 + random.randint(-150, 600))
            )
        conn.commit()

    # Fetch all transactions to build corresponding customer events
    cursor.execute("SELECT store_id, order_timestamp FROM pos_transactions")
    transactions = cursor.fetchall()
    print(f"Loaded {len(transactions)} POS transactions.")

    events_to_insert = []
    visitor_counter = 10000

    # We want a conversion rate around 40-50%
    # So we map about 50% of transactions to converting customer sessions.
    # The rest of transactions will be mapped to converting sessions, and we'll add non-converting sessions.
    
    print("Generating simulated events mapped to POS transactions...")
    for store_id, tx_time_str in transactions:
        tx_time = datetime.strptime(tx_time_str.split(".")[0], "%Y-%m-%d %H:%M:%S")
        
        # Decide if this transaction is matched to a visitor session (80% match rate)
        if random.random() > 0.8:
            continue
            
        visitor_counter += 1
        visitor_id = f"VIS_{visitor_counter}"
        
        # Journey timeline (UTC naive)
        # Entry -> Zone Visits -> Billing Queue Join -> Billing Queue Exit -> Exit
        t_entry = tx_time - timedelta(minutes=random.randint(8, 15))
        t_zone = t_entry + timedelta(minutes=random.randint(2, 4))
        t_billing = tx_time - timedelta(minutes=random.randint(2, 4))
        t_exit = tx_time + timedelta(minutes=random.randint(2, 5))
        
        # Choose camera and zones based on store
        entry_cam = "CAM_3" if store_id == "STORE_BLR_001" else "entry_1"
        zone_cam = "CAM_1" if store_id == "STORE_BLR_001" else "zone"
        billing_cam = "CAM_5" if store_id == "STORE_BLR_001" else "billing_area"
        
        zones = ["SKINCARE", "HAIRCARE"] if store_id == "STORE_BLR_001" else ["COSMETICS", "SKINCARE"]
        selected_zone = random.choice(zones)
        
        # 1. ENTRY
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "ENTRY",
            t_entry.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.95, None, None, 1
        ))
        
        # 2. ZONE_ENTER
        events_to_insert.append((
            str(uuid.uuid4()), store_id, zone_cam, visitor_id, "ZONE_ENTER",
            t_zone.strftime("%Y-%m-%d %H:%M:%S"), selected_zone, 0, 0, 0.92, None, selected_zone, 2
        ))
        
        # 3. ZONE_DWELL
        events_to_insert.append((
            str(uuid.uuid4()), store_id, zone_cam, visitor_id, "ZONE_DWELL",
            (t_zone + timedelta(seconds=30)).strftime("%Y-%m-%d %H:%M:%S"), selected_zone, 30000, 0, 0.90, None, selected_zone, 3
        ))
        
        # 4. ZONE_EXIT
        events_to_insert.append((
            str(uuid.uuid4()), store_id, zone_cam, visitor_id, "ZONE_EXIT",
            t_billing.strftime("%Y-%m-%d %H:%M:%S"), selected_zone, 45000, 0, 0.91, None, selected_zone, 4
        ))
        
        # 5. BILLING_QUEUE_JOIN
        events_to_insert.append((
            str(uuid.uuid4()), store_id, billing_cam, visitor_id, "BILLING_QUEUE_JOIN",
            t_billing.strftime("%Y-%m-%d %H:%M:%S"), "BILLING", 0, 0, 0.98, random.randint(1, 4), "BILLING", 5
        ))
        
        # 6. ZONE_EXIT (Billing)
        events_to_insert.append((
            str(uuid.uuid4()), store_id, billing_cam, visitor_id, "ZONE_EXIT",
            tx_time.strftime("%Y-%m-%d %H:%M:%S"), "BILLING", 120000, 0, 0.99, None, "BILLING", 6
        ))
        
        # 7. EXIT
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "EXIT",
            t_exit.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.94, None, None, 7
        ))

    # Add Non-Converting Visitors (Window Shoppers / Browsers)
    print("Generating simulated events for non-converting visitors...")
    for i in range(120):
        visitor_counter += 1
        visitor_id = f"VIS_NC_{visitor_counter}"
        
        store_id = "STORE_BLR_001" if random.random() < 0.7 else "STORE_BLR_002"
        base_time = datetime(2026, 4, 10, 6, 50, 0)
        t_entry = base_time + timedelta(minutes=random.randint(0, 520))
        t_zone = t_entry + timedelta(minutes=random.randint(1, 3))
        t_exit = t_zone + timedelta(minutes=random.randint(2, 6))
        
        entry_cam = "CAM_3" if store_id == "STORE_BLR_001" else "entry_1"
        zone_cam = "CAM_1" if store_id == "STORE_BLR_001" else "zone"
        
        zones = ["SKINCARE", "HAIRCARE", "COSMETICS", "FRAGRANCE"]
        selected_zone = random.choice(zones)
        
        # ENTRY
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "ENTRY",
            t_entry.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.93, None, None, 1
        ))
        # ZONE_ENTER
        events_to_insert.append((
            str(uuid.uuid4()), store_id, zone_cam, visitor_id, "ZONE_ENTER",
            t_zone.strftime("%Y-%m-%d %H:%M:%S"), selected_zone, 0, 0, 0.88, None, selected_zone, 2
        ))
        # EXIT
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "EXIT",
            t_exit.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.91, None, None, 3
        ))

    # Add Queue Abandonment Visitors (entered billing line but left without purchase)
    print("Generating simulated events for checkout queue abandonments...")
    for i in range(25):
        visitor_counter += 1
        visitor_id = f"VIS_AB_{visitor_counter}"
        
        store_id = "STORE_BLR_001" if random.random() < 0.7 else "STORE_BLR_002"
        base_time = datetime(2026, 4, 10, 6, 50, 0)
        t_entry = base_time + timedelta(minutes=random.randint(0, 520))
        t_billing = t_entry + timedelta(minutes=random.randint(2, 5))
        t_abandon = t_billing + timedelta(minutes=random.randint(1, 3))
        t_exit = t_abandon + timedelta(seconds=30)
        
        entry_cam = "CAM_3" if store_id == "STORE_BLR_001" else "entry_1"
        billing_cam = "CAM_5" if store_id == "STORE_BLR_001" else "billing_area"
        
        # ENTRY
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "ENTRY",
            t_entry.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.92, None, None, 1
        ))
        # BILLING_QUEUE_JOIN
        events_to_insert.append((
            str(uuid.uuid4()), store_id, billing_cam, visitor_id, "BILLING_QUEUE_JOIN",
            t_billing.strftime("%Y-%m-%d %H:%M:%S"), "BILLING", 0, 0, 0.96, random.randint(4, 9), "BILLING", 2
        ))
        # BILLING_QUEUE_ABANDON
        events_to_insert.append((
            str(uuid.uuid4()), store_id, billing_cam, visitor_id, "BILLING_QUEUE_ABANDON",
            t_abandon.strftime("%Y-%m-%d %H:%M:%S"), "BILLING", 0, 0, 0.97, None, "BILLING", 3
        ))
        # EXIT
        events_to_insert.append((
            str(uuid.uuid4()), store_id, entry_cam, visitor_id, "EXIT",
            t_exit.strftime("%Y-%m-%d %H:%M:%S"), None, 0, 0, 0.90, None, None, 4
        ))

    # Add Staff Members (to verify staff exclusion)
    print("Generating simulated events for store staff...")
    for i in range(6):
        visitor_counter += 1
        visitor_id = f"VIS_STAFF_{visitor_counter}"
        store_id = "STORE_BLR_001" if i % 2 == 0 else "STORE_BLR_002"
        base_time = datetime(2026, 4, 10, 6, 30, 0)
        
        entry_cam = "CAM_3" if store_id == "STORE_BLR_001" else "entry_1"
        zone_cam = "CAM_1" if store_id == "STORE_BLR_001" else "zone"
        
        # Staff stays in the store for hours
        for hour in range(8):
            t_work = base_time + timedelta(hours=hour, minutes=random.randint(0, 10))
            events_to_insert.append((
                str(uuid.uuid4()), store_id, zone_cam, visitor_id, "ZONE_ENTER",
                t_work.strftime("%Y-%m-%d %H:%M:%S"), "SKINCARE", 0, 1, 0.95, None, "SKINCARE", hour + 1
            ))

    # Insert events into database
    print(f"Inserting {len(events_to_insert)} events into SQLite database...")
    cursor.executemany(
        "INSERT INTO events (event_id, store_id, camera_id, visitor_id, event_type, timestamp, zone_id, dwell_ms, is_staff, confidence, queue_depth, sku_zone, session_seq) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        events_to_insert
    )
    conn.commit()
    conn.close()
    print("Events seeded successfully!")

if __name__ == "__main__":
    seed_events()
