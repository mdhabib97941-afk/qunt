import requests

def format_symbol(symbol):
    """Converts Yahoo Finance format (BTC-USD) to Binance Futures format (BTCUSDT)"""
    if "-USD" in symbol:
        return symbol.replace("-USD", "USDT")
    return symbol

def get_whale_data(symbol):
    """
    Fetches real-time Open Interest, Funding Rate, and Long/Short ratios from Binance Futures.
    Returns a dictionary of raw derivatives data to gauge Whale vs Retail sentiment.
    """
    b_sym = format_symbol(symbol)
    data = {
        "symbol": b_sym,
        "funding_rate": 0.0,
        "open_interest": 0.0,
        "retail_ls_ratio": 1.0,
        "whale_ls_ratio": 1.0,
        "retail_sentiment": "Neutral",
        "whale_sentiment": "Neutral"
    }
    
    headers = {"User-Agent": "Mozilla/5.0"}
    
    try:
        # 1. Funding Rate (Premium Index)
        url_fr = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={b_sym}"
        res_fr = requests.get(url_fr, headers=headers, timeout=5).json()
        if "lastFundingRate" in res_fr:
            data["funding_rate"] = float(res_fr["lastFundingRate"]) * 100 # In percentage
            
        # 2. Open Interest
        url_oi = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={b_sym}"
        res_oi = requests.get(url_oi, headers=headers, timeout=5).json()
        if "openInterest" in res_oi:
            data["open_interest"] = float(res_oi["openInterest"])
            
        # 3. Global Long/Short Ratio (Retail proxy)
        url_global_ls = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={b_sym}&period=15m&limit=1"
        res_global = requests.get(url_global_ls, headers=headers, timeout=5).json()
        if isinstance(res_global, list) and len(res_global) > 0:
            data["retail_ls_ratio"] = float(res_global[0]["longShortRatio"])
            
        # 4. Top Trader Long/Short Ratio (Whale/Smart Money proxy)
        url_top_ls = f"https://fapi.binance.com/futures/data/topLongShortPositionRatio?symbol={b_sym}&period=15m&limit=1"
        res_top = requests.get(url_top_ls, headers=headers, timeout=5).json()
        if isinstance(res_top, list) and len(res_top) > 0:
            data["whale_ls_ratio"] = float(res_top[0]["longShortRatio"])

        # Determine Sentiments
        if data["retail_ls_ratio"] > 1.1:
            data["retail_sentiment"] = "Very Bullish (Trappable)"
        elif data["retail_ls_ratio"] < 0.9:
            data["retail_sentiment"] = "Very Bearish (Trappable)"
            
        if data["whale_ls_ratio"] > 1.1:
            data["whale_sentiment"] = "Whales Accumulating Longs"
        elif data["whale_ls_ratio"] < 0.9:
            data["whale_sentiment"] = "Whales Distributing Shorts"

    except Exception as e:
        print(f"Whale Tracker API Error on {b_sym}: {e}")
        
    return data

if __name__ == "__main__":
    # Test
    print(get_whale_data("BTC-USD"))
