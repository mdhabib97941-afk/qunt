import requests
import time

def format_symbol(symbol):
    if "-USD" in symbol:
        return symbol.replace("-USD", "USDT")
    return symbol

def check_whale_walls(symbol, limit=100):
    """
    Fetches the order book to find massive whale limit orders (Walls).
    """
    b_sym = format_symbol(symbol)
    url = f"https://fapi.binance.com/fapi/v1/depth?symbol={b_sym}&limit={limit}"
    
    data = {"huge_buy_wall_price": None, "huge_sell_wall_price": None, "wall_imbalance": "Neutral"}
    try:
        res = requests.get(url, timeout=5).json()
        if "bids" not in res or "asks" not in res:
            return data
            
        # Parse Bids (Buy Walls) and Asks (Sell Walls)
        bids = [(float(price), float(qty)) for price, qty in res["bids"]]
        asks = [(float(price), float(qty)) for price, qty in res["asks"]]
        
        # Find the largest walls by USD value
        max_bid = max(bids, key=lambda x: x[0]*x[1])
        max_ask = max(asks, key=lambda x: x[0]*x[1])
        
        total_bid_vol = sum([p*q for p,q in bids])
        total_ask_vol = sum([p*q for p,q in asks])
        
        data["huge_buy_wall_price"] = max_bid[0]
        data["huge_sell_wall_price"] = max_ask[0]
        
        if total_bid_vol > total_ask_vol * 1.5:
            data["wall_imbalance"] = "Heavy Buy Support (Whale Bids)"
        elif total_ask_vol > total_bid_vol * 1.5:
            data["wall_imbalance"] = "Heavy Sell Pressure (Whale Asks)"
            
    except Exception as e:
        print(f"Orderflow Wall API Error: {e}")
        
    return data

def check_absorption(symbol):
    """
    Checks recent volume vs price action to detect Whale Absorption.
    Taker Buy Volume = Market Buys.
    Total Volume - Taker Buy Volume = Market Sells.
    """
    b_sym = format_symbol(symbol)
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={b_sym}&interval=15m&limit=3"
    
    data = {"absorption_status": "No clear absorption"}
    try:
        res = requests.get(url, timeout=5).json()
        if not res: return data
        
        # Look at the most recent completed candle
        c = res[-2]
        open_p, high, low, close_p = float(c[1]), float(c[2]), float(c[3]), float(c[4])
        total_vol = float(c[5])
        taker_buy_vol = float(c[9])
        taker_sell_vol = total_vol - taker_buy_vol
        
        body = abs(close_p - open_p)
        total_range = high - low
        
        # If massive Market Buys but price forms a Doji/Bearish = Buy Absorption
        if taker_buy_vol > total_vol * 0.65 and body < total_range * 0.3 and close_p <= open_p:
            data["absorption_status"] = "STRONG BUY ABSORPTION (Whales absorbing retail buys with limit sells - Bearish Signal)"
            
        # If massive Market Sells but price forms a Doji/Bullish = Sell Absorption
        elif taker_sell_vol > total_vol * 0.65 and body < total_range * 0.3 and close_p >= open_p:
            data["absorption_status"] = "STRONG SELL ABSORPTION (Whales absorbing retail sells with limit buys - Bullish Signal)"
            
    except Exception as e:
        print(f"Orderflow Absorption API Error: {e}")
        
    return data

def get_whale_gameplan(symbol, lookback=4):
    """
    Analyzes the last 'lookback' 15m candles to calculate average whale activity,
    buying/selling pressure, and deduce the overarching 'Game Plan' (Accumulation/Distribution/Breakout).
    """
    b_sym = format_symbol(symbol)
    url = f"https://fapi.binance.com/fapi/v1/klines?symbol={b_sym}&interval=15m&limit={lookback+1}"
    
    try:
        res = requests.get(url, timeout=5).json()
        if not res: return {"whale_gameplan": "Data Error"}
        
        # Exclude the running unclosed candle
        closed_candles = res[:-1]
        
        total_vol = 0
        total_buy_vol = 0
        total_sell_vol = 0
        
        start_open = float(closed_candles[0][1])
        end_close = float(closed_candles[-1][4])
        net_price_change = end_close - start_open
        
        highs = [float(c[2]) for c in closed_candles]
        lows = [float(c[3]) for c in closed_candles]
        total_range = max(highs) - min(lows)
        
        for c in closed_candles:
            vol = float(c[5])
            buy_vol = float(c[9])
            sell_vol = vol - buy_vol
            
            total_vol += vol
            total_buy_vol += buy_vol
            total_sell_vol += sell_vol
            
        buy_pct = (total_buy_vol / total_vol) * 100 if total_vol > 0 else 50
        sell_pct = (total_sell_vol / total_vol) * 100 if total_vol > 0 else 50
        
        gameplan = "NEUTRAL (Chop phase, balanced order flow)"
        
        # Accumulation Logic: High Sell Volume, but Price didn't drop much
        if sell_pct > 55 and net_price_change >= -(total_range * 0.2):
            gameplan = "WHALE ACCUMULATION (Absorbing retail sells, preparing to Pump)"
            
        # Distribution Logic: High Buy Volume, but Price didn't rise much
        elif buy_pct > 55 and net_price_change <= (total_range * 0.2):
            gameplan = "WHALE DISTRIBUTION (Absorbing retail buys, preparing to Dump / Short Trap)"
            
        # Breakout / Momentum Logic: High Volume pushing price aggressively
        elif buy_pct > 55 and net_price_change > (total_range * 0.5):
            gameplan = "AGGRESSIVE BULLISH MOMENTUM (Whales aggressively pushing price up)"
            
        elif sell_pct > 55 and net_price_change < -(total_range * 0.5):
            gameplan = "AGGRESSIVE BEARISH MOMENTUM (Whales aggressively pushing price down)"

        return {
            'analyzed_candles': lookback,
            'total_volume': total_vol,
            'avg_buy_pct': buy_pct,
            'avg_sell_pct': sell_pct,
            'net_price_change': net_price_change,
            'whale_gameplan': gameplan
        }
    except Exception as e:
        return {'whale_gameplan': f"Error: {str(e)}"}

if __name__ == "__main__":
    print(check_whale_walls("BTC-USD"))
    print(check_absorption("BTC-USD"))
    print(get_whale_gameplan("BTC-USD"))
