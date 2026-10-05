import time
import requests
import datetime
import os
from pymongo import MongoClient

# ==========================================
# 🛑 PASTE YOUR MONGODB LINK BELOW 🛑
# ==========================================
# Replace "mongodb+srv://mdhabib97941_db_user:FoQH7HjGaLOIzwNY@cluster0.iiyn4rv.mongodb.net/?appName=Cluster0" with your actual Atlas URI
# Keep the quotes! Example: "mongodb+srv://admin:pass@cluster..."
MONGO_URI = os.getenv("MONGO_URI", "mongodb+srv://mdhabib97941_db_user:FoQH7HjGaLOIzwNY@cluster0.iiyn4rv.mongodb.net/?appName=Cluster0")

print("=========================================")
print("🧠 CLOUD AUTO-MEMORY SYSTEM (MONGODB) STARTED")
print("=========================================\n")

# Connect to MongoDB
try:
    client = MongoClient(MONGO_URI)
    db = client['quant_ai']             # Database Name
    memory_col = db['memory_bank']      # Collection Name
    
    # Quick test to see if connection works
    client.admin.command('ping')
    print("✅ Successfully connected to MongoDB Atlas!")
except Exception as e:
    print(f"❌ MongoDB Connection Failed! Check your URI.\nError: {e}")
    exit()

SYMBOL = "BTCUSDT"
last_oi = None

print("\nMonitoring for anomalies, spoofs, and liquidations (Syncing to Cloud)...")

while True:
    try:
        # 1. Fetch Data
        price_data = requests.get(f"https://fapi.binance.com/fapi/v1/ticker/price?symbol={SYMBOL}").json()
        curr_price = float(price_data['price'])

        oi_data = requests.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={SYMBOL}").json()
        curr_oi = float(oi_data['openInterest'])

        depth = requests.get(f"https://fapi.binance.com/fapi/v1/depth?symbol={SYMBOL}&limit=50").json()
        max_buy_wall = max([float(x[1]) for x in depth['bids']])
        max_buy_price = [float(x[0]) for x in depth['bids'] if float(x[1]) == max_buy_wall][0]
        max_sell_wall = max([float(x[1]) for x in depth['asks']])
        max_sell_price = [float(x[0]) for x in depth['asks'] if float(x[1]) == max_sell_wall][0]

        whale_data = requests.get(f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={SYMBOL}&period=15m&limit=1").json()
        whale_ls = float(whale_data[0]['longShortRatio']) if whale_data else 1.0
        
        retail_data = requests.get(f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={SYMBOL}&period=15m&limit=1").json()
        retail_ls = float(retail_data[0]['longShortRatio']) if retail_data else 1.0

        now_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        logs_to_insert = []

        # 2. Logic (Detect Anomalies)
        if last_oi is not None:
            oi_diff = curr_oi - last_oi
            if oi_diff < -200:
                logs_to_insert.append({
                    "timestamp": now_str, "price": curr_price, "event": "LIQUIDATION_FLUSH",
                    "message": f"Open Interest dropped violently by {abs(oi_diff):.1f} BTC. Weak hands stopped out.",
                    "severity": "HIGH"
                })
            elif oi_diff > 300:
                logs_to_insert.append({
                    "timestamp": now_str, "price": curr_price, "event": "LEVERAGE_SPIKE",
                    "message": f"Open Interest spiked by {oi_diff:.1f} BTC. High leverage entering.",
                    "severity": "MEDIUM"
                })

        if max_sell_wall > 70:
            logs_to_insert.append({
                "timestamp": now_str, "price": curr_price, "event": "SPOOF_WALL_SELL",
                "message": f"Massive {max_sell_wall:.1f} BTC Sell Wall placed at ${max_sell_price:,.2f}. Whales capping price.",
                "severity": "HIGH"
            })
        
        if max_buy_wall > 70:
            logs_to_insert.append({
                "timestamp": now_str, "price": curr_price, "event": "DEFENSE_WALL_BUY",
                "message": f"Massive {max_buy_wall:.1f} BTC Buy Wall placed at ${max_buy_price:,.2f}. Whales absorbing sells.",
                "severity": "HIGH"
            })

        if whale_ls > 1.85:
            logs_to_insert.append({
                "timestamp": now_str, "price": curr_price, "event": "WHALE_ACCUMULATION",
                "message": f"Whale L/S ratio extremely high at {whale_ls:.4f}. Institutional buying.",
                "severity": "MEDIUM"
            })
        
        if retail_ls < 0.96:
            logs_to_insert.append({
                "timestamp": now_str, "price": curr_price, "event": "RETAIL_TRAP",
                "message": f"Retail L/S dropped to {retail_ls:.4f}. Retail is heavily shorting.",
                "severity": "MEDIUM"
            })

        # 3. Push to MongoDB
        if logs_to_insert:
            memory_col.insert_many(logs_to_insert)
            for log in logs_to_insert:
                print(f"[{now_str}] ☁️ SAVED TO CLOUD: {log['message']}")
        else:
            print(f"[{now_str}] Normal market conditions. Nothing logged.")

        last_oi = curr_oi

    except Exception as e:
        print(f"Error fetching/saving data: {e}")
    
    # Wait 3 minutes before next check
    time.sleep(180)
