import requests

def get_market_xray():
    print("=========================================")
    print("🧠 LOADING QUANT MEMORY CORE...")
    import os
    if os.path.exists("quant_memory_bank.md"):
        print("✅ Historical Context & Whale Psychology Loaded.")
    print("=========================================\n")
    print("=========================================")
    print("🕵️‍♂️ LOCAL AGENT: DEEP QUANT X-RAY SCAN 🕵️‍♂️")
    print("=========================================\n")

    try:
        # 1. Price & Trend
        k_1h = requests.get('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=1h&limit=5').json()
        curr_price = float(k_1h[-1][4])
        prev_price = float(k_1h[-2][4])
        trend_1h = "🟢 UP" if curr_price >= prev_price else "🔴 DOWN"

        # 2. Orderbook Walls
        depth = requests.get('https://fapi.binance.com/fapi/v1/depth?symbol=BTCUSDT&limit=50').json()
        bids = [(float(p), float(q)) for p, q in depth['bids']]
        asks = [(float(p), float(q)) for p, q in depth['asks']]
        
        max_bid = max(bids, key=lambda x: x[1])
        max_ask = max(asks, key=lambda x: x[1])

        # 3. Volume Profile (POC) - 48 Hours
        k_15m = requests.get('https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT&interval=15m&limit=192').json()
        volume_profile = {}
        for k in k_15m:
            mid_price = (float(k[2]) + float(k[3])) / 2
            price_level = round(mid_price / 10) * 10
            volume_profile[price_level] = volume_profile.get(price_level, 0) + float(k[5])
        
        poc = max(volume_profile, key=volume_profile.get)
        poc_vol = volume_profile[poc]

        # 4. Order Flow (1H CVD)
        # Approximate using taker buy volume vs total volume of last 4 15m candles
        taker_buy = sum([float(k[9]) for k in k_15m[-4:]])
        total_vol = sum([float(k[5]) for k in k_15m[-4:]])
        taker_sell = total_vol - taker_buy
        net_delta = taker_buy - taker_sell

        # 5. Open Interest
        oi_data = requests.get('https://fapi.binance.com/fapi/v1/openInterest?symbol=BTCUSDT').json()
        oi = float(oi_data['openInterest'])

        # 6. Sentiment (L/S Ratios)
        retail_data = requests.get('https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol=BTCUSDT&period=15m&limit=1').json()
        retail_ls = float(retail_data[0]['longShortRatio'])

        whale_data = requests.get('https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol=BTCUSDT&period=15m&limit=1').json()
        whale_ls = float(whale_data[0]['longShortRatio'])

        print(f"[1] PRICE & TREND: $ {curr_price:,.2f} | 1H Trend: {trend_1h}\n")
        print(f"[2] ORDERBOOK SPOOF/WALL CHECK:\n   🛡️ Strongest Buy Wall (Support):  $ {max_bid[0]:,.2f} ({max_bid[1]:.1f} BTC)\n   🧱 Strongest Sell Wall (Resist):  $ {max_ask[0]:,.2f} ({max_ask[1]:.1f} BTC)\n")
        print(f"[3] VOLUME PROFILE (MACRO ORDER BLOCK):\n   🏦 Heaviest POC (Point of Control): $ {poc:,.2f} (Vol: {poc_vol:.1f} BTC)\n")
        print(f"[4] 1-HOUR ORDER FLOW (CVD):\n   📈 Taker Buy: {taker_buy:.1f} BTC | 📉 Taker Sell: {taker_sell:.1f} BTC | Net Delta: {'+' if net_delta > 0 else ''}{net_delta:.1f} BTC\n")
        print(f"[5] OPEN INTEREST: {oi:,.1f} BTC\n")
        print(f"[6] SENTIMENT (L/S RATIO):\n   🏃‍♂️ Retail (Global): {retail_ls:.4f} ({'LONGING' if retail_ls > 1 else 'SHORTING'})\n   🐋 Whales (Top):    {whale_ls:.4f} ({'LONGING' if whale_ls > 1 else 'SHORTING'})\n")
        
    except Exception as e:
        print(f"Error fetching data: {e}")

if __name__ == "__main__":
    get_market_xray()
