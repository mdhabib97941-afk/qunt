import pandas as pd

def get_structural_pivots(df, window=5):
    """
    Finds structural market pivots using Line Chart (Close Price) logic.
    Once a peak/valley is found on the close price, it maps the actual 
    Liquidity Pool to the High/Low of that specific candle.
    Also calculates Volume-Anchored Structural Liquidity (VASL) by checking
    if the volume forming the pivot is a 'Nuclear' pool.
    """
    swing_highs = []
    swing_lows = []
    
    # Need at least window*2 + 1 candles
    if len(df) < window * 2 + 1:
        return swing_highs, swing_lows
        
    avg_vol = df['volume'].mean() if 'volume' in df.columns else 0
        
    for i in range(window, len(df) - window):
        # Line Chart logic: look at close prices
        closes = df['close'].iloc[i-window : i+window+1]
        
        current_close = df['close'].iloc[i]
        vol = df['volume'].iloc[i] if 'volume' in df.columns else 0
        is_nuclear = vol > (avg_vol * 1.5)
        
        # If this close is the highest in the window (Peak)
        if current_close == closes.max():
            # The true liquidity pool is the HIGH of this candle
            true_high = df['high'].iloc[i]
            # Store: (index, price_level, type)
            swing_highs.append({'index': i, 'price': true_high, 'time': df['time'].iloc[i], 'volume': vol, 'is_nuclear': is_nuclear})
            
        # If this close is the lowest in the window (Valley)
        elif current_close == closes.min():
            # The true liquidity pool is the LOW of this candle
            true_low = df['low'].iloc[i]
            swing_lows.append({'index': i, 'price': true_low, 'time': df['time'].iloc[i], 'volume': vol, 'is_nuclear': is_nuclear})
            
    return swing_highs, swing_lows

def get_smc_order_blocks(df, pivot_len=7, z_score_thresh=0.5):
    """
    Pine Script translated SMC Logic for detecting Order Blocks (OB) and Market Structure Breaks (MSB).
    Tracks momentum using Z-Score to filter fakeouts.
    """
    df = df.copy()
    
    # 1. Momentum Z-Score
    df['priceChange'] = df['close'].diff()
    df['avgChange'] = df['priceChange'].rolling(50).mean()
    df['stdChange'] = df['priceChange'].rolling(50).std()
    df['momentumZ'] = (df['priceChange'] - df['avgChange']) / df['stdChange']
    
    # 2. Pivot High/Low
    df['ph'] = df['high'][(df['high'] == df['high'].rolling(window=pivot_len*2+1, center=True).max())]
    df['pl'] = df['low'][(df['low'] == df['low'].rolling(window=pivot_len*2+1, center=True).min())]
    
    df['lastPh'] = df['ph'].ffill()
    df['lastPl'] = df['pl'].ffill()
    
    order_blocks = []
    
    # 3. Detect MSB and OB
    for i in range(50, len(df)):
        close = df['close'].iloc[i]
        prev_close = df['close'].iloc[i-1]
        z = df['momentumZ'].iloc[i]
        
        last_ph = df['lastPh'].iloc[i]
        last_pl = df['lastPl'].iloc[i]
        
        # Bullish MSB
        if pd.notna(last_ph) and close > last_ph and prev_close <= last_ph and z > z_score_thresh:
            for j in range(1, 11):
                idx = i - j
                if idx >= 0 and df['close'].iloc[idx] < df['open'].iloc[idx]:
                    order_blocks.append({
                        'type': 'BULLISH_OB',
                        'msb_time': df['time'].iloc[i],
                        'ob_time': df['time'].iloc[idx],
                        'top': df['high'].iloc[idx],
                        'bottom': df['low'].iloc[idx],
                    })
                    break
                    
        # Bearish MSB
        if pd.notna(last_pl) and close < last_pl and prev_close >= last_pl and z < -z_score_thresh:
            for j in range(1, 11):
                idx = i - j
                if idx >= 0 and df['close'].iloc[idx] > df['open'].iloc[idx]:
                    order_blocks.append({
                        'type': 'BEARISH_OB',
                        'msb_time': df['time'].iloc[i],
                        'ob_time': df['time'].iloc[idx],
                        'top': df['high'].iloc[idx],
                        'bottom': df['low'].iloc[idx],
                    })
                    break
                    
    return order_blocks
