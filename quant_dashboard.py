import time
import logging
import threading
import requests
import json
import websocket
from flask import Flask, jsonify, render_template_string, request
import yfinance as yf
import orderflow_api
import whale_tracker_api
import market_structure

log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)

nuclear_cache = {}
nuclear_lock = threading.Lock()

recent_liquidations = []
liq_lock = threading.Lock()

def liq_worker():
    def on_message(ws, message):
        try:
            data = json.loads(message)
            if 'o' in data:
                order = data['o']
                side = order['S']  
                qty = float(order['q'])
                price = float(order['p'])
                val = qty * price
                
                if val > 10000:  
                    with liq_lock:
                        recent_liquidations.insert(0, {
                            'side': side,
                            'price': price,
                            'value': val,
                            'time': time.time()
                        })
                        if len(recent_liquidations) > 3:
                            recent_liquidations.pop()
        except:
            pass
            
    def on_error(ws, error):
        pass
        
    def on_close(ws, *args):
        time.sleep(3)
        start_liq_ws()
        
    def start_liq_ws():
        ws = websocket.WebSocketApp("wss://fstream.binance.com/ws/btcusdt@forceOrder",
                                  on_message=on_message,
                                  on_error=on_error,
                                  on_close=on_close)
        ws.run_forever()
        
    start_liq_ws()

threading.Thread(target=liq_worker, daemon=True).start()

def update_nuclear_liquidity(symbol):
    try:
        df = yf.download(symbol, interval='1h', period='60d', progress=False)
        if str(type(df.columns)).find('MultiIndex') != -1: 
            df.columns = df.columns.get_level_values(0)
        df.reset_index(inplace=True)
        df.rename(columns={'Datetime':'time','Date':'time','Open':'open','High':'high','Low':'low','Close':'close','Volume':'volume'}, inplace=True)
        
        if df.empty: return
        
        curr_price = df['close'].iloc[-1]
        sh, sl = market_structure.get_structural_pivots(df, window=12)
        
        upside = [p['price'] for p in sh if p['is_nuclear'] and p['price'] > curr_price]
        downside = [p['price'] for p in sl if p['is_nuclear'] and p['price'] < curr_price]
        
        upside = sorted(upside)[:3]  
        downside = sorted(downside, reverse=True)[:3] 
        
        with nuclear_lock:
            nuclear_cache[symbol] = {
                'timestamp': time.time(),
                'upside': upside,
                'downside': downside
            }
    except Exception as e:
        pass

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>SMC Quant Dashboard</title>
    <style>
        body { font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; background-color: #0d1117; color: #c9d1d9; margin: 0; padding: 20px; }
        .container { max-width: 900px; margin: auto; }
        .header { text-align: center; border-bottom: 1px solid #30363d; padding-bottom: 20px; margin-bottom: 20px; position: relative; }
        .header h1 { color: #58a6ff; margin: 0; font-size: 28px; letter-spacing: 2px;}
        .header p { color: #8b949e; margin-top: 5px; margin-bottom: 15px;}
        
        .coin-selector { background-color: #161b22; color: #58a6ff; border: 1px solid #30363d; padding: 8px 15px; font-size: 16px; font-weight: bold; border-radius: 6px; cursor: pointer; outline: none; }
        .coin-selector:focus { border-color: #58a6ff; }
        
        .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 20px; text-align: center; box-shadow: 0 4px 6px rgba(0,0,0,0.3); transition: all 0.2s;}
        .card h3 { margin: 0 0 10px 0; color: #8b949e; font-size: 14px; text-transform: uppercase; letter-spacing: 1px;}
        .val { font-size: 36px; font-weight: bold; font-family: monospace; }
        .green { color: #3fb950; text-shadow: 0 0 10px rgba(63, 185, 80, 0.4); }
        .red { color: #f85149; text-shadow: 0 0 10px rgba(248, 81, 73, 0.4); }
        .neutral { color: #d2a8ff; }
        
        .advanced-grid { display: grid; grid-template-columns: 1fr 1fr 1fr 1fr; gap: 10px; margin-top: 15px;}
        .adv-box { background: rgba(0,0,0,0.2); padding: 10px; border-radius: 6px; border: 1px solid #30363d;}
        
        .verdict-card { grid-column: span 2; background: #21262d; border-color: #484f58; }
        .verdict-card .val { font-size: 26px; font-family: 'Segoe UI', sans-serif;}
        .breakout-text { font-size: 15px; color: #ffeb3b; margin-top: 10px; }
        
        .nuc-zone { margin-top: 15px; padding: 15px; background: rgba(255, 255, 255, 0.05); border-radius: 6px; display: flex; justify-content: space-around; }
        .nuc-target { font-family: monospace; font-size: 20px; font-weight: bold; margin-top: 5px; }
        .nuc-up { color: #f85149; }
        .nuc-down { color: #3fb950; }
        
        .liq-item { font-size: 12px; margin-top: 5px; padding: 5px; background: rgba(0,0,0,0.3); border-radius: 4px; border-left: 4px solid; font-family: monospace; }
        
        .footer { text-align: center; margin-top: 30px; font-size: 12px; color: #8b949e; }
        .blink { animation: blinker 1s linear infinite; font-size: 10px; color: #3fb950; vertical-align: middle;}
        @keyframes blinker { 50% { opacity: 0; } }
        
        .sound-btn { background-color: #238636; color: white; border: none; padding: 5px 10px; font-size: 12px; border-radius: 5px; cursor: pointer; margin-top: 10px; font-weight: bold; }
        .sound-btn.disabled { background-color: #f85149; }
    </style>
    <script>
        let currentSymbol = 'BTC-USD';
        let lastSetup = "WAIT";
        let audioEnabled = false;
        
        function enableAudio() {
            audioEnabled = true;
            let btn = document.getElementById('audio_btn');
            btn.innerText = "🔊 Setup Alerts ON";
            btn.className = "sound-btn";
            playAlertSound('TEST');
        }

        function playAlertSound(type) {
            if (!audioEnabled) return;
            try {
                const ctx = new (window.AudioContext || window.webkitAudioContext)();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                
                if (type === 'LONG') {
                    osc.frequency.setValueAtTime(600, ctx.currentTime);
                    osc.frequency.exponentialRampToValueAtTime(1200, ctx.currentTime + 0.1);
                    osc.type = 'sine';
                } else if (type === 'SHORT') {
                    osc.frequency.setValueAtTime(1200, ctx.currentTime);
                    osc.frequency.exponentialRampToValueAtTime(400, ctx.currentTime + 0.1);
                    osc.type = 'sawtooth';
                } else if (type === 'LIQ') {
                    osc.frequency.setValueAtTime(100, ctx.currentTime);
                    osc.frequency.exponentialRampToValueAtTime(50, ctx.currentTime + 0.1);
                    osc.type = 'square';
                } else {
                    osc.frequency.setValueAtTime(0, ctx.currentTime);
                }
                
                gain.gain.setValueAtTime(0, ctx.currentTime);
                if (type !== 'TEST') {
                    gain.gain.linearRampToValueAtTime(1, ctx.currentTime + 0.05);
                    gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.8);
                }
                
                osc.start(ctx.currentTime);
                osc.stop(ctx.currentTime + 0.8);
            } catch (e) {}
        }
        
        function changeCoin() {
            currentSymbol = document.getElementById('coin_selector').value;
            lastSetup = "WAIT"; 
            updateData(); 
        }
        
        function formatVal(val) {
            if(val >= 1000000) return (val/1000000).toFixed(2) + 'M';
            if(val >= 1000) return (val/1000).toFixed(1) + 'K';
            return val.toFixed(0);
        }

        let lastLiqTime = 0;

        const canvas = document.getElementById('customChart');
        const ctx = canvas ? canvas.getContext('2d') : null;
        
        function drawCustomChart(data) {
            if(!ctx || !data.candles || data.candles.length === 0) return;
            const w = canvas.width;
            const h = canvas.height;
            ctx.clearRect(0, 0, w, h);
            
            // Find Min/Max for Y Scale
            let minP = Math.min(...data.candles.map(c => c.low));
            let maxP = Math.max(...data.candles.map(c => c.high));
            
            if(data.lines) {
                data.lines.forEach(l => {
                    if(l.price < minP) minP = l.price;
                    if(l.price > maxP) maxP = l.price;
                });
            }
            
            const padding = (maxP - minP) * 0.05;
            minP -= padding;
            maxP += padding;
            
            const range = maxP - minP;
            const candleWidth = w / data.candles.length;
            
            function getY(price) {
                return h - ((price - minP) / range) * h;
            }
            
            // Draw grid lines
            ctx.strokeStyle = '#30363d';
            ctx.lineWidth = 1;
            for(let i=1; i<5; i++) {
                let y = (h/5) * i;
                ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
            }
            
            // Draw Candles
            data.candles.forEach((c, i) => {
                const x = i * candleWidth + (candleWidth/2);
                const isGreen = c.close >= c.open;
                const color = isGreen ? '#3fb950' : '#f85149';
                
                // Wick
                ctx.strokeStyle = color;
                ctx.lineWidth = 2;
                ctx.beginPath();
                ctx.moveTo(x, getY(c.high));
                ctx.lineTo(x, getY(c.low));
                ctx.stroke();
                
                // Body
                const yOpen = getY(c.open);
                const yClose = getY(c.close);
                const bodyY = Math.min(yOpen, yClose);
                const bodyH = Math.max(Math.abs(yOpen - yClose), 2);
                
                ctx.fillStyle = color;
                ctx.fillRect(x - candleWidth*0.35, bodyY, candleWidth*0.7, bodyH);
            });
            
            // Draw Liquidity Lines
            if(data.lines) {
                data.lines.forEach(l => {
                    const y = getY(l.price);
                    ctx.beginPath();
                    if (l.type === 'micro_up') {
                        ctx.setLineDash([3, 3]);
                        ctx.strokeStyle = '#ff9800';
                        ctx.lineWidth = 1.5;
                    } else if (l.type === 'micro_down') {
                        ctx.setLineDash([3, 3]);
                        ctx.strokeStyle = '#00bcd4';
                        ctx.lineWidth = 1.5;
                    } else if(l.mitigated) {
                        ctx.setLineDash([5, 5]);
                        ctx.strokeStyle = '#8b949e';
                        ctx.lineWidth = 2;
                    } else {
                        ctx.setLineDash([]);
                        ctx.strokeStyle = l.type === 'up' ? '#f85149' : '#3fb950';
                        ctx.lineWidth = 2;
                    }
                    ctx.moveTo(0, y);
                    ctx.lineTo(w, y);
                    ctx.stroke();
                    ctx.setLineDash([]);
                    
                    // Label
                    if (l.type === 'micro_up') ctx.fillStyle = '#ff9800';
                    else if (l.type === 'micro_down') ctx.fillStyle = '#00bcd4';
                    else ctx.fillStyle = l.mitigated ? '#8b949e' : (l.type === 'up' ? '#f85149' : '#3fb950');
                    ctx.font = '12px monospace';
                    let txt = 'LIQ';
                    if (l.type === 'up') txt = 'UP NUC';
                    else if (l.type === 'down') txt = 'DN NUC';
                    else if (l.type === 'micro_up') txt = 'MIC UP';
                    else if (l.type === 'micro_down') txt = 'MIC DN';
                    if(l.mitigated) txt += ' (SWEPT)';
                    ctx.fillText(txt + ' $' + l.price.toFixed(1), 10, y - 5);
                });
            }
        }
        
        function fetchChartData() {
            fetch('/api/chart_data?symbol=' + currentSymbol)
            .then(r => r.json())
            .then(data => {
                drawCustomChart(data);
            });
        }
        
        window.addEventListener('load', () => {
            fetchChartData();
            setInterval(fetchChartData, 3000);
        });


        


        function updateData() {
            fetch('/api/data?symbol=' + currentSymbol)
                .then(r => r.json())
                .then(data => {
                    let decimals = data.price < 1 ? 4 : 2;
                    if (data.price < 0.01) decimals = 5;
                    
                    document.getElementById('price').innerText = "$" + data.price.toLocaleString(undefined, {minimumFractionDigits: decimals, maximumFractionDigits: decimals});
                    
                    let buyPctCurr = document.getElementById('buy_pct_curr');
                    buyPctCurr.innerText = data.buy_pct_curr.toFixed(2) + "%";
                    document.getElementById('live_vol_btc').innerText = `Buy: ${data.live_buy_btc} BTC | Sell: ${data.live_sell_btc} BTC`;
                    buyPctCurr.className = "val " + (data.buy_pct_curr > 50 ? "green" : "red");
                    
                    let buyPct = document.getElementById('buy_pct_closed_15m');
                    buyPct.innerText = data.buy_pct_closed_15m.toFixed(2) + "%";
                    buyPct.className = "val " + (data.buy_pct_closed_15m > 50 ? "green" : "red");
                    let buyPct1h = document.getElementById('buy_pct_closed_1h');
                    if(buyPct1h && data.buy_pct_closed_1h) {
                        buyPct1h.innerText = data.buy_pct_closed_1h.toFixed(2) + "%";
                        buyPct1h.className = "val " + (data.buy_pct_closed_1h > 50 ? "green" : "red");
                    }

                    document.getElementById('whale_ls').innerText = data.whale_ls.toFixed(2);
                  
                  let retailLs = document.getElementById('retail_ls');
                  if (retailLs && data.retail_ls !== undefined) {
                      retailLs.innerText = data.retail_ls.toFixed(2);
                      retailLs.className = "val " + (data.retail_ls < 1.0 ? "green" : "red");
                  }

                    
                    // Advanced Metrics
                    let oiText = document.getElementById('oi_text');
                    oiText.innerText = data.oi_analysis;
                    oiText.style.color = data.oi_trend > 0 ? "#3fb950" : (data.oi_trend < 0 ? "#f85149" : "#8b949e");
                    
                    let ancText = document.getElementById('anc_text');
                    ancText.innerHTML = `${data.anc_status}<br><span style="font-size:11px; color:#8b949e;">(From last ${data.anc_type})</span>`;
                    
                    // Spoof Scanner & Attacking Force
                    let spoofText = document.getElementById('spoof_text');
                    spoofText.innerHTML = `
                        <span style="color:${data.spoof_color}">${data.spoof_status}</span><br>
                        <span style="font-size:11px; color:#8b949e;">${data.spoof_detail}</span><br>
                        <span style="font-size:11px; font-weight:bold; color:${data.force_color}; margin-top:3px; display:inline-block;">Force: ${data.attack_force}</span>
                    `;

                    // Liquidations
                    let liqHtml = "";
                    if (data.liquidations.length === 0) {
                        liqHtml = "<div style='color: #8b949e; font-size: 12px; margin-top: 10px;'>No liquidations...</div>";
                    } else {
                        let newLiqFound = false;
                        data.liquidations.forEach(liq => {
                            let isLongLiq = liq.side === "SELL"; 
                            let color = isLongLiq ? "#f85149" : "#3fb950";
                            let text = isLongLiq ? "📉 LONG LIQ" : "🚀 SHORT LIQ";
                            liqHtml += `<div class="liq-item" style="border-color: ${color}; color: ${color};">
                                ${text} | $${formatVal(liq.value)}
                            </div>`;
                            if (liq.time > lastLiqTime) {
                                newLiqFound = true;
                                lastLiqTime = liq.time;
                            }
                        });
                        if (newLiqFound) playAlertSound('LIQ');
                    }
                    document.getElementById('liq_container').innerHTML = liqHtml;
                    
                    let verdict = document.getElementById('verdict');
                    verdict.innerText = data.verdict;
                    if (data.action == "SHORT" || data.action == "DUMP") verdict.className = "val red";
                    else if (data.action == "LONG" || data.action == "PUMP") verdict.className = "val green";
                    else verdict.className = "val neutral";

                    document.getElementById('breakout_cond').innerText = data.breakout_cond;
                    
                    document.getElementById('nuc_up').innerHTML = data.nuc_upside.length > 0 ? "$" + data.nuc_upside.map(x => x.toFixed(decimals)).join('<br>$') : "None Found";
                    document.getElementById('nuc_down').innerHTML = data.nuc_downside.length > 0 ? "$" + data.nuc_downside.map(x => x.toFixed(decimals)).join('<br>$') : "None Found";
                    
                    document.getElementById('battle_status').innerText = data.battle_status;
                    let dirEl = document.getElementById('setup_dir');
                    dirEl.innerText = data.setup_dir;
                    dirEl.style.color = data.setup_dir.includes("LONG") ? "#3fb950" : (data.setup_dir.includes("SHORT") ? "#f85149" : "#d2a8ff");
                    
                    document.getElementById('entry_price').innerText = data.entry_price;
                    document.getElementById('sl_price').innerText = data.sl_price;
                    document.getElementById('tp_price').innerText = data.tp_price;
                    
                    // Sweep Detector Update
                    let sweepBox = document.getElementById('sweep_box');
                    let sweepText = document.getElementById('sweep_text');
                    sweepText.innerText = data.sweep_msg;
                    if(data.sweep_status === "UPSIDE_SWEEP") {
                        sweepBox.style.borderColor = "#f85149";
                        sweepBox.style.backgroundColor = "rgba(248, 81, 73, 0.1)";
                        sweepText.style.color = "#f85149";
                    } else if(data.sweep_status === "DOWNSIDE_SWEEP") {
                        sweepBox.style.borderColor = "#3fb950";
                        sweepBox.style.backgroundColor = "rgba(63, 185, 80, 0.1)";
                        sweepText.style.color = "#3fb950";
                    } else {
                        sweepBox.style.borderColor = "#30363d";
                        sweepBox.style.backgroundColor = "rgba(0,0,0,0.2)";
                        sweepText.style.color = "#8b949e";
                    }
                    
                    let currentSetup = data.setup_dir;
                    if ((currentSetup === "LONG" || currentSetup === "SHORT") && currentSetup !== lastSetup) {
                        playAlertSound(currentSetup);
                    }
                    lastSetup = currentSetup;
                })
                .catch(err => console.error("Error fetching data:", err));
        }
        
        setInterval(updateData, 3000);
        window.onload = updateData;
    </script>

    

</head>
<body>
    <div class="container">
        <div class="header">
            <h1>⚡ X-RAY QUANT DASHBOARD</h1>
            <p>🟢 Auto-Refreshing Live Data <span class="blink">● LIVE</span></p>
            
            <select id="coin_selector" class="coin-selector" onchange="changeCoin()">
                <option value="BTC-USD">Bitcoin (BTC)</option>
                <option value="ETH-USD">Ethereum (ETH)</option>
                <option value="SOL-USD">Solana (SOL)</option>
            </select>
            <br>
            <button id="audio_btn" class="sound-btn disabled" onclick="enableAudio()">🔇 Click to Enable Setup Sounds</button>
        </div>
        
        <div class="grid">
            <div class="card" id="sweep_box" style="grid-column: span 2; padding: 15px; border: 2px solid #30363d; border-radius: 8px; background: rgba(0,0,0,0.2); transition: all 0.3s;">
                <h3 style="color: #ffeb3b; font-size: 14px; margin-bottom: 5px;">🛡️ ANTI-STOP HUNT (SWEEP DETECTOR)</h3>
                <div id="sweep_text" style="font-weight: bold; font-size: 16px; color: #8b949e;">Scanning for Liquidity Sweeps...</div>
            </div>
            
            <div class="card">
                <h3>Current Price</h3>
                <div class="val neutral" id="price">Loading...</div>
            </div>
            <div class="card">
                <h3>Live Tape (1m Flow)</h3>
                <div class="val" id="buy_pct_curr">Loading...</div>
                <div id="live_vol_btc" style="font-size:11px; color:#8b949e; margin-top:5px; font-weight:normal;">Loading Volume...</div>
            </div>
            <div class="card">
                <h3>Last Closed 15m (Confirmation)</h3>
                <div class="val" id="buy_pct_closed_15m">Loading...</div>
            </div>
            <div class="card">
                <h3>Whale L/S Ratio</h3>
                <div class="val neutral" id="whale_ls">Loading...</div>
            </div>
            <div class="card">
                <h3>Last Closed 1h (Macro Flow)</h3>
                <div class="val" id="buy_pct_closed_1h">Loading...</div>
            </div>
            <div class="card">
                <h3>Retail L/S Ratio</h3>
                <div class="val neutral" id="retail_ls">Loading...</div>
            </div>
            
            <div class="card verdict-card">
                <h3 style="color: #ffeb3b; font-size: 16px;">🔍 ADVANCED MARKET INTERNALS</h3>
                <div class="advanced-grid">
                    <div class="adv-box">
                        <div style="color:#8b949e; font-size: 11px; margin-bottom: 5px; text-transform: uppercase;">⚓ Anchored Flow</div>
                        <div id="anc_text" style="font-weight: bold; font-size: 13px;">Loading...</div>
                    </div>
                    <div class="adv-box">
                        <div style="color:#8b949e; font-size: 11px; margin-bottom: 5px; text-transform: uppercase;">Open Interest (OI)</div>
                        <div id="oi_text" style="font-weight: bold; font-size: 13px;">Loading...</div>
                    </div>
                    <div class="adv-box">
                        <div style="color:#8b949e; font-size: 11px; margin-bottom: 5px; text-transform: uppercase;">Order Book (Spoof)</div>
                        <div id="spoof_text" style="font-weight: bold; font-size: 13px;">Loading...</div>
                    </div>
                    <div class="adv-box">
                        <div style="color:#8b949e; font-size: 11px; margin-bottom: 5px; text-transform: uppercase;">Live Liquidations</div>
                        <div id="liq_container">Loading...</div>
                    </div>
                </div>
            </div>
            
            <div class="card verdict-card">
                <h3>Live Market Verdict (The X-Ray)</h3>
                <div class="val" id="verdict">Analyzing...</div>
                <div class="breakout-text" id="breakout_cond"></div>
            </div>
            
            <div class="card verdict-card">
                <h3>🔥 NUCLEAR LIQUIDITY POOLS (THE MAGNETS)</h3>
                <div style="font-size: 13px; color: #8b949e;">Macro Targets where extreme liquidations reside. Smart money targets these zones.</div>
                <div class="nuc-zone">
                    <div>
                        <div style="color: #f85149; font-weight: bold; text-transform: uppercase; font-size: 12px; margin-bottom: 5px;">Shorts' Liquidation (Targets Above) 🚀</div>
                        <div class="nuc-target nuc-up" id="nuc_up">Loading...</div>
                    </div>
                    <div style="width: 1px; background: #30363d;"></div>
                    <div>
                        <div style="color: #3fb950; font-weight: bold; text-transform: uppercase; font-size: 12px; margin-bottom: 5px;">Longs' Liquidation (Targets Below) 🧲</div>
                        <div class="nuc-target nuc-down" id="nuc_down">Loading...</div>
                    </div>
                </div>
            </div>
            
            <div class="card verdict-card" style="border-color: #d2a8ff; margin-bottom: 20px;">
                <h3 style="color: #d2a8ff; font-size: 18px;">🤖 AI QUANT TRADE SETUP (Strict 15m Confirmed)</h3>
                <div style="font-size: 16px; margin-bottom: 10px;">Battle Status: <span id="battle_status" style="font-weight:bold; color: #ffeb3b;">Loading...</span></div>
                
                <div class="grid" style="grid-template-columns: 1fr 1fr 1fr; margin-top:15px; background: rgba(0,0,0,0.2); padding: 15px; border-radius: 8px;">
                    <div>
                        <div style="color: #8b949e; font-size: 12px; text-transform: uppercase; margin-bottom: 5px;">Setup / Entry</div>
                        <div id="setup_dir" style="font-size: 22px; font-weight: bold; font-family: monospace;">WAIT</div>
                        <div id="entry_price" style="font-size: 14px; font-family: monospace; color:#c9d1d9;">--</div>
                    </div>
                    <div style="border-left: 1px solid #30363d; border-right: 1px solid #30363d;">
                        <div style="color: #f85149; font-size: 12px; text-transform: uppercase; margin-bottom: 5px;">Stop Loss (SL)</div>
                        <div id="sl_price" style="font-size: 20px; font-weight: bold; font-family: monospace;">--</div>
                        <div style="font-size: 11px; color:#8b949e; margin-top:3px;">(Tight 15m Structure)</div>
                    </div>
                    <div>
                        <div style="color: #3fb950; font-size: 12px; text-transform: uppercase; margin-bottom: 5px;">Take Profit (TP)</div>
                        <div id="tp_price" style="font-size: 20px; font-weight: bold; font-family: monospace;">--</div>
                        <div style="font-size: 11px; color:#8b949e; margin-top:3px;">(Nuclear Liquidity)</div>
                    </div>
                </div>
            </div>
            
        </div>
        
        
        <div class="card verdict-card" style="margin-top: 20px;">
            <h3 style="color: #ffeb3b;">📊 NUCLEAR LIQUIDITY X-RAY CHART (15m)</h3>
            <canvas id="customChart" width="800" height="400" style="width: 100%; height: 400px; margin-top: 15px; border: 1px solid #30363d; background: #161b22;"></canvas>
        </div>

        <div class="footer">Engine: Python Quant Algorithm | Status: Auto-Updating Every 3 Seconds (Signal anchored to 15m Close)</div>
    </div>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/data')
def get_data():
    symbol = request.args.get('symbol', 'BTC-USD')
    binance_symbol = symbol.replace('-USD', 'USDT')
    
    needs_update = False
    with nuclear_lock:
        if symbol not in nuclear_cache or time.time() - nuclear_cache[symbol]['timestamp'] > 600:
            needs_update = True
    
    if needs_update:
        threading.Thread(target=update_nuclear_liquidity, args=(symbol,)).start()
        if symbol not in nuclear_cache:
            time.sleep(1.5)
            
    with nuclear_lock:
        nuc_data = nuclear_cache.get(symbol, {'upside': [], 'downside': []})
        nuc_upside = nuc_data['upside']
        nuc_downside = nuc_data['downside']
    
    try:
        url_15m = f"https://fapi.binance.com/fapi/v1/klines?symbol={binance_symbol}&interval=15m&limit=150"
        k_15m_data = requests.get(url_15m, timeout=3).json()
        
        # ANCHORED VOLUME LOGIC
        max_h = 0
        min_l = float('inf')
        idx_h = 0
        idx_l = 0
        for i, k in enumerate(k_15m_data):
            if float(k[2]) > max_h:
                max_h = float(k[2])
                idx_h = i
            if float(k[3]) < min_l:
                min_l = float(k[3])
                idx_l = i
                
        pivot_idx = max(idx_h, idx_l)
        pivot_type = "Swing Bottom" if pivot_idx == idx_l else "Swing Top"
        
        anc_vol = sum([float(k[5]) for k in k_15m_data[pivot_idx:]])
        anc_buy = sum([float(k[9]) for k in k_15m_data[pivot_idx:]])
        anc_buy_pct = (anc_buy / anc_vol * 100) if anc_vol > 0 else 50
        
        
        # Z-SCORE & VOL PERCENTILE LOGIC (From TradingView Indicator)
        import statistics
        closes = [float(k[4]) for k in k_15m_data]
        volumes = [float(k[5]) for k in k_15m_data]
        
        if len(closes) > 55:
            changes = [closes[i] - closes[i-1] for i in range(1, len(closes))]
            
            # Find the strongest momentum in the recent swing
            recent_changes = changes[pivot_idx-1:] if pivot_idx > 0 else changes[-5:]
            if not recent_changes: recent_changes = changes[-5:]
            max_recent_change = max(recent_changes, key=abs)
            
            # Mean & StdDev over 50 periods prior to current
            base_changes = changes[-55:-5]
            sma_change = statistics.mean(base_changes) if base_changes else 0
            std_change = statistics.stdev(base_changes) if len(base_changes) >= 2 else 1.0
            std_change = std_change if std_change > 0 else 1.0
            
            momentum_z = (max_recent_change - sma_change) / std_change
            
            # Volume Percentile
            recent_vol = max(volumes[pivot_idx:]) if pivot_idx < len(volumes) else volumes[-1]
            lookback_vols = volumes[-100:]
            count_below = sum(1 for v in lookback_vols if v < recent_vol)
            vol_percent = (count_below / len(lookback_vols)) * 100 if len(lookback_vols) > 0 else 50
            
            ob_score = min(100.0, (abs(momentum_z) * 20) + (vol_percent * 0.5))
        else:
            ob_score = 50.0
            
        if anc_buy_pct > 52:
            anc_status = f"🟢 Accumulation (HPZ: {ob_score:.0f}%)" if pivot_type == "Swing Bottom" else f"🟢 Continuation (HPZ: {ob_score:.0f}%)"
        elif anc_buy_pct < 48:
            anc_status = f"🔴 Distribution (HPZ: {ob_score:.0f}%)" if pivot_type == "Swing Bottom" else f"🔴 Sellers (HPZ: {ob_score:.0f}%)"
        else:
            anc_status = f"⚖️ Chopping (HPZ: {ob_score:.0f}%)"
        # Standard Logic
        closed_15m = k_15m_data[-2] 
        curr_15m = k_15m_data[-1]

        url_1h = f"https://fapi.binance.com/fapi/v1/klines?symbol={binance_symbol}&interval=1h&limit=2"
        try:
            k_1h_data = requests.get(url_1h, timeout=3).json()
            closed_1h = k_1h_data[-2]
            closed_1h_vol = float(closed_1h[5])
            closed_1h_taker = float(closed_1h[9])
            buy_pct_closed_1h = (closed_1h_taker / closed_1h_vol) * 100 if closed_1h_vol > 0 else 50.0
        except:
            buy_pct_closed_1h = 50.0

        
        closed_15m_high = float(closed_15m[2])
        closed_15m_low = float(closed_15m[3])
        closed_15m_vol = float(closed_15m[5])
        closed_15m_taker = float(closed_15m[9])
        buy_pct_closed_15m = (closed_15m_taker / closed_15m_vol) * 100 if closed_15m_vol > 0 else 50.0
        
        price_diff = float(curr_15m[4]) - float(closed_15m[4])
        
        url_1m = f"https://fapi.binance.com/fapi/v1/klines?symbol={binance_symbol}&interval=1m&limit=1"
        kline = requests.get(url_1m, timeout=3).json()[0]
        
        curr_price = float(kline[4])
        total_coin_vol = float(kline[5])
        taker_buy_coin = float(kline[9])
        taker_sell_coin = total_coin_vol - taker_buy_coin
        
        live_buy_btc = round(taker_buy_coin, 1)
        live_sell_btc = round(taker_sell_coin, 1)
        
        buy_pct_curr = (taker_buy_coin / total_coin_vol) * 100 if total_coin_vol > 0 else 50.0
            
        whale_data = whale_tracker_api.get_whale_data(symbol)
        whale_ls = float(whale_data.get('whale_ls_ratio', 1.0))
        try:
            url_retail = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={binance_symbol}&period=15m&limit=1"
            retail_ls = float(requests.get(url_retail, timeout=3).json()[0]['longShortRatio'])
        except:
            retail_ls = 1.0

        
        oi_trend = 0
        oi_analysis = "Neutral"
        try:
            url_oi = f"https://fapi.binance.com/futures/data/openInterestHist?symbol={binance_symbol}&period=15m&limit=2"
            oi_data = requests.get(url_oi, timeout=3).json()
            if len(oi_data) == 2:
                prev_oi = float(oi_data[0]['sumOpenInterestValue'])
                curr_oi = float(oi_data[1]['sumOpenInterestValue'])
                oi_delta = curr_oi - prev_oi
                
                if oi_delta > 0 and price_diff > 0:
                    oi_analysis = "Longs Building (New Money IN) 🚀"
                    oi_trend = 1
                elif oi_delta < 0 and price_diff > 0:
                    oi_analysis = "Shorts Covering (Fake Pump) ⚠️"
                    oi_trend = -1
                elif oi_delta > 0 and price_diff < 0:
                    oi_analysis = "Shorts Building (New Money IN) 📉"
                    oi_trend = -1
                elif oi_delta < 0 and price_diff < 0:
                    oi_analysis = "Longs Liquidating (Fake Dump) ⚠️"
                    oi_trend = 1
        except:
            pass
            
        # SPOOF SCANNER & ATTACKING FORCE LOGIC
        spoof_status = "Neutral (Balanced)"
        spoof_detail = "No major walls detected"
        spoof_color = "#8b949e"
        attack_force = "N/A"
        force_color = "#8b949e"
        
        try:
            depth_url = f"https://fapi.binance.com/fapi/v1/depth?symbol={binance_symbol}&limit=100"
            depth_data = requests.get(depth_url, timeout=3).json()
            
            # Find exact wall peaks
            max_bid = max(depth_data['bids'], key=lambda x: float(x[1]))
            max_ask = max(depth_data['asks'], key=lambda x: float(x[1]))
            
            bid_price, bid_qty = float(max_bid[0]), float(max_bid[1])
            ask_price, ask_qty = float(max_ask[0]), float(max_ask[1])
            
            bids_total = sum([float(b[1]) for b in depth_data['bids']])
            asks_total = sum([float(a[1]) for a in depth_data['asks']])
            
            if asks_total > bids_total * 1.5 or ask_qty > 50: # Major Sell Wall
                if anc_buy_pct > 52:
                    spoof_status = "Fake Sell Wall ⚠️"
                    spoof_color = "#d2a8ff"
                else:
                    spoof_status = "Defensive Wall 🧱"
                    spoof_color = "#f85149"
                spoof_detail = f"Loc: ${ask_price:,.0f} | Size: {ask_qty:.0f} BTC"
                
                # Attacking Force (Buyers hitting the Sell Wall)
                if buy_pct_curr > 65 and anc_buy_pct > 52 and oi_trend > 0:
                    attack_force = "HIGH (Breakout Likely 🚀)"
                    force_color = "#3fb950"
                elif buy_pct_curr < 50 or anc_buy_pct < 48:
                    attack_force = "LOW (Wall will HOLD 🧱)"
                    force_color = "#f85149"
                else:
                    attack_force = "MEDIUM (Testing...)"
                    force_color = "#ffeb3b"
                    
            elif bids_total > asks_total * 1.5 or bid_qty > 50: # Major Buy Wall
                if anc_buy_pct < 48:
                    spoof_status = "Fake Buy Wall ⚠️"
                    spoof_color = "#d2a8ff"
                else:
                    spoof_status = "Strong Support 🧱"
                    spoof_color = "#3fb950"
                spoof_detail = f"Loc: ${bid_price:,.0f} | Size: {bid_qty:.0f} BTC"
                
                # Attacking Force (Sellers hitting the Buy Wall)
                if buy_pct_curr < 35 and anc_buy_pct < 48 and oi_trend < 0:
                    attack_force = "HIGH (Breakout Likely 📉)"
                    force_color = "#f85149"
                elif buy_pct_curr > 50 or anc_buy_pct > 52:
                    attack_force = "LOW (Wall will HOLD 🧱)"
                    force_color = "#3fb950"
                else:
                    attack_force = "MEDIUM (Testing...)"
                    force_color = "#ffeb3b"
            else:
                spoof_status = "Balanced Book"
                spoof_detail = f"Bids: {bids_total:.0f} BTC | Asks: {asks_total:.0f} BTC"
                attack_force = "Neutral"
        except:
            pass
            
        with liq_lock:
            current_liqs = list(recent_liquidations)

        verdict = "Neutral / Chopping"
        action = "WAIT"
        breakout_cond = ""
        
        if buy_pct_closed_15m < 48:
            verdict = "Bearish Control (15m Confirmed) 📉"
            action = "DUMP"
            if buy_pct_curr < 43:
                breakout_cond = "⚠️ Radar: 1m selling confirms 15m downtrend."
            else:
                breakout_cond = "🛡️ Radar: Short-term pullback happening."
        elif buy_pct_closed_15m > 52:
            verdict = "Bullish Control (15m Confirmed) 📈"
            action = "PUMP"
            if buy_pct_curr > 57:
                breakout_cond = "🚀 Radar: 1m buying confirms 15m uptrend."
            else:
                breakout_cond = "🛡️ Radar: Short-term pullback happening."
        
        battle_status = "⏳ Waiting for next 15m Close..."
        setup_dir = "WAIT"
        entry_price = "Wait for strict signal"
        sl_price = "--"
        tp_price = "--"
        
        decimals = 2 if curr_price > 1 else 5
        up_targ = nuc_upside[0] if nuc_upside else curr_price * 1.02
        down_targ = nuc_downside[0] if nuc_downside else curr_price * 0.98
        
        if buy_pct_closed_15m > 55:
            battle_status = "🏆 Confirmed Buyers (15m Closed)"
            setup_dir = "LONG"
            entry_price = f"Entry: ${curr_price:,.{decimals}f}"
            sl_price = f"${(closed_15m_low - 15):,.{decimals}f}" 
            tp_price = f"${up_targ:,.{decimals}f}"
        elif buy_pct_closed_15m < 45:
            battle_status = "🏆 Confirmed Sellers (15m Closed)"
            setup_dir = "SHORT"
            entry_price = f"Entry: ${curr_price:,.{decimals}f}"
            sl_price = f"${(closed_15m_high + 15):,.{decimals}f}" 
            tp_price = f"${down_targ:,.{decimals}f}"
        else:
            battle_status = "⚔️ Active Battle in 15m Body (Chop)"
            setup_dir = "WAIT"
            
        # SWEEP DETECTOR LOGIC (Anti-Stop Hunt)
        sweep_status = "NONE"
        sweep_msg = "Scanning for Liquidity Sweeps..."
        
        try:
            # Get the highest high and lowest low of the last 15 candles (excluding current)
            recent_highs = [float(k[2]) for k in k_15m_data[-16:-1]]
            recent_lows = [float(k[3]) for k in k_15m_data[-16:-1]]
            local_sh = max(recent_highs)
            local_sl = min(recent_lows)
            
            if curr_price > local_sh and anc_buy_pct < 48 and buy_pct_curr < 50:
                sweep_status = "UPSIDE_SWEEP"
                sweep_msg = f"🚨 UPSIDE SWEEP DETECTED! Price broke ${local_sh:,.0f} but Sellers are absorbing! SAFE TO SHORT 📉"
            elif curr_price < local_sl and anc_buy_pct > 52 and buy_pct_curr > 50:
                sweep_status = "DOWNSIDE_SWEEP"
                sweep_msg = f"🚨 DOWNSIDE SWEEP DETECTED! Price broke ${local_sl:,.0f} but Buyers are absorbing! SAFE TO LONG 🚀"
        except:
            pass

        return jsonify({
            "price": curr_price, "buy_pct_closed_15m": buy_pct_closed_15m, "buy_pct_closed_1h": buy_pct_closed_1h, "retail_ls": retail_ls, "buy_pct_curr": buy_pct_curr,
            "live_buy_btc": live_buy_btc, "live_sell_btc": live_sell_btc,
            "whale_ls": whale_ls, "verdict": verdict, "action": action, "breakout_cond": breakout_cond,
            "nuc_upside": nuc_upside, "nuc_downside": nuc_downside,
            "battle_status": battle_status, "setup_dir": setup_dir, "entry_price": entry_price,
            "sl_price": sl_price, "tp_price": tp_price,
            "oi_analysis": oi_analysis, "oi_trend": oi_trend,
            "liquidations": current_liqs,
            "anc_status": anc_status, "anc_type": pivot_type,
            "spoof_status": spoof_status, "spoof_detail": spoof_detail, "spoof_color": spoof_color,
            "attack_force": attack_force, "force_color": force_color,
            "sweep_status": sweep_status, "sweep_msg": sweep_msg
        })
    except Exception as e:
        return jsonify({
            "price": 0, "buy_pct_closed_15m": 50, "buy_pct_closed_1h": 50, "retail_ls": 1.0, "buy_pct_curr": 50, 
            "live_buy_btc": 0, "live_sell_btc": 0, "whale_ls": 1, 
            "verdict": f"Error: {str(e)}", "action": "WAIT", "breakout_cond": "",
            "nuc_upside": [], "nuc_downside": [],
            "battle_status": "Error", "setup_dir": "WAIT", "entry_price": "--", "sl_price": "--", "tp_price": "--",
            "oi_analysis": "Error", "oi_trend": 0, "liquidations": [],
            "anc_status": "Error", "anc_type": "N/A",
            "spoof_status": "Error", "spoof_detail": "Error loading", "spoof_color": "#f85149",
            "attack_force": "N/A", "force_color": "#8b949e",
            "sweep_status": "NONE", "sweep_msg": "Error loading sweep data"
        })


@app.route('/api/chart_data')
def get_chart_data():
    symbol = request.args.get('symbol', 'BTC-USD')
    binance_symbol = symbol.replace('-USD', 'USDT')
    

    try:
        # Get candles
        url = f"https://fapi.binance.com/fapi/v1/klines?symbol={binance_symbol}&interval=15m&limit=100"
        data = requests.get(url, timeout=5).json()
        
        # Get Long/Short Ratio
        ls_url = f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={binance_symbol}&period=5m&limit=1"
        ls_data = requests.get(ls_url, timeout=5).json()
        ls_ratio = float(ls_data[0]['longShortRatio']) if ls_data else 1.0
        
        # Get Premium Index (Funding)
        fund_url = f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={binance_symbol}"
        fund_data = requests.get(fund_url, timeout=5).json()
        funding = float(fund_data.get('lastFundingRate', 0)) * 100 # In percentage
        
        # Retail Sentiment Logic
        if ls_ratio > 1.2:
            retail_sentiment = "HEAVILY LONG (FOMO) 🟢"
            retail_color = "#3fb950"
            whale_target = "Whales targeting DOWNSIDE ☢️"
        elif ls_ratio < 0.8:
            retail_sentiment = "HEAVILY SHORT (FEAR) 🔴"
            retail_color = "#f85149"
            whale_target = "Whales targeting UPSIDE ☢️"
        else:
            retail_sentiment = "MIXED (Neutral) ⚪"
            retail_color = "#8b949e"
            whale_target = "Whales accumulating..."
            
        funding_str = f"{funding:+.4f}%"
        if funding > 0.01:
            funding_str += " (Overheated)"
        
        candles = []
        for k in data:
            c = {
                'time': int(int(k[0])/1000),
                'open': float(k[1]),
                'high': float(k[2]),
                'low': float(k[3]),
                'close': float(k[4])
            }
            candles.append(c)
        
        recent_candles = data[-15:]
        max_high_recent = max([float(k[2]) for k in recent_candles])
        min_low_recent = min([float(k[3]) for k in recent_candles])
        
        # MICRO LIQUIDITY LOGIC
        micro_up = []
        micro_down = []
        for i in range(len(data)-50, len(data)-2):
            c_high = float(data[i][2])
            c_low = float(data[i][3])
            if c_high > float(data[i-1][2]) and c_high > float(data[i+1][2]):
                micro_up.append(c_high)
            if c_low < float(data[i-1][3]) and c_low < float(data[i+1][3]):
                micro_down.append(c_low)
        
        curr_price = float(data[-1][4])
        valid_m_up = sorted([p for p in micro_up if p > curr_price])[:1]
        valid_m_dn = sorted([p for p in micro_down if p < curr_price], reverse=True)[:1]

            
        with nuclear_lock:
            nuc_data = nuclear_cache.get(symbol, {'upside': [], 'downside': []})
            up = nuc_data.get('upside', [])
            down = nuc_data.get('downside', [])
            
        lines = []
        for p in up:
            mitigated = True if max_high_recent >= p else False
            lines.append({'price': p, 'type': 'up', 'mitigated': mitigated})
        for p in down:
            mitigated = True if min_low_recent <= p else False
            lines.append({'price': p, 'type': 'down', 'mitigated': mitigated})
            
        for p in valid_m_up:
            lines.append({'price': p, 'type': 'micro_up', 'mitigated': False})
        for p in valid_m_dn:
            lines.append({'price': p, 'type': 'micro_down', 'mitigated': False})

            
        return jsonify({
            'candles': candles, 
            'lines': lines,
            'retail': {
                'ls_ratio': ls_ratio,
                'sentiment': retail_sentiment,
                'color': retail_color,
                'whale_target': whale_target,
                'funding': funding_str
            }
        })
    except Exception as e:
        return jsonify({'candles': [], 'lines': [], 'retail': None})


CHART_HTML = r"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>☢ Nuclear Liquidity X-Ray Chart</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: #0d1117; color: #c9d1d9; font-family: 'Segoe UI', Arial, sans-serif; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }

  #topbar { background: #161b22; border-bottom: 1px solid #30363d; padding: 10px 18px; display: flex; align-items: center; justify-content: space-between; flex-shrink: 0; }
  #topbar h1 { font-size: 16px; color: #58a6ff; letter-spacing: 1px; }
  #live-badge { display: flex; align-items: center; gap: 6px; font-size: 12px; color: #3fb950; }
  .dot { width: 8px; height: 8px; background: #3fb950; border-radius: 50%; animation: blink 1.2s infinite; }
  @keyframes blink { 0%,100%{opacity:1} 50%{opacity:.2} }

  #infobar { background: #161b22; border-bottom: 1px solid #30363d; padding: 7px 18px; display: flex; gap: 28px; align-items: center; flex-shrink: 0; }
  .info-item { display: flex; flex-direction: column; gap: 1px; }
  .info-label { font-size: 9px; color: #8b949e; text-transform: uppercase; letter-spacing: .8px; }
  .info-val { font-size: 15px; font-weight: 700; font-family: monospace; }
  .info-val.price { color: #58a6ff; font-size: 20px; }
  .info-val.red { color: #f85149; }
  .info-val.green { color: #3fb950; }

  #chart-container { flex: 1; position: relative; min-height: 0; }
  #chart-canvas { display: block; width: 100%; height: 100%; }

  #legend { background: #161b22; border-top: 1px solid #30363d; padding: 6px 18px; display: flex; gap: 20px; flex-shrink: 0; }
  .leg-item { display: flex; align-items: center; gap: 6px; font-size: 11px; color: #8b949e; }
  .leg-line { width: 24px; height: 2px; }
  .leg-box { width: 10px; height: 10px; border-radius: 2px; }
</style>
</head>
<body>

<div id="topbar">
  <h1>☢ NUCLEAR LIQUIDITY X-RAY CHART &nbsp;|&nbsp; BTC/USDT Perpetual &nbsp;|&nbsp; 15m</h1>
  <div id="live-badge"><div class="dot"></div> LIVE — 3s refresh</div>
</div>


<div id="retail-radar" style="background: #0d1117; border-bottom: 1px solid #30363d; padding: 8px 18px; display: flex; gap: 30px; align-items: center; flex-shrink: 0; font-size: 12px;">
  <div style="color:#58a6ff; font-weight:bold;">🛡️ RETAIL TRAP RADAR</div>
  <div class="info-item"><div class="info-label">L/S Ratio</div><div class="info-val" id="rr-ls">—</div></div>
  <div class="info-item"><div class="info-label">Retail Sentiment</div><div class="info-val" id="rr-sent">—</div></div>
  <div class="info-item"><div class="info-label">Funding Rate</div><div class="info-val" id="rr-fund">—</div></div>
  <div class="info-item"><div class="info-label">Whale Target</div><div class="info-val" id="rr-target" style="color:#ffeb3b">—</div></div>
</div>

<div id="infobar">
  <div class="info-item"><div class="info-label">Last Price</div><div class="info-val price" id="ib-price">—</div></div>
  <div class="info-item"><div class="info-label">O</div><div class="info-val" id="ib-open" style="color:#c9d1d9">—</div></div>
  <div class="info-item"><div class="info-label">H</div><div class="info-val green" id="ib-high">—</div></div>
  <div class="info-item"><div class="info-label">L</div><div class="info-val red" id="ib-low">—</div></div>
  <div class="info-item"><div class="info-label">Change</div><div class="info-val" id="ib-chg">—</div></div>
  <div style="flex:1"></div>
  <div class="info-item"><div class="info-label">☢ Upside Liq</div><div class="info-val red" id="ib-up">—</div></div>
  <div class="info-item"><div class="info-label">☢ Downside Liq</div><div class="info-val green" id="ib-dn">—</div></div>
</div>

<div id="chart-container">
  <canvas id="chart-canvas"></canvas>
</div>

<div id="legend">
  <div class="leg-item"><div class="leg-box" style="background:#3fb950"></div>Bullish Candle</div>
  <div class="leg-item"><div class="leg-box" style="background:#f85149"></div>Bearish Candle</div>
  <div class="leg-item"><div class="leg-line" style="background:#f85149"></div>Upside Nuclear Liq (Active)</div>
  <div class="leg-item"><div class="leg-line" style="background:#3fb950"></div>Downside Nuclear Liq (Active)</div>
  <div class="leg-item"><div class="leg-line" style="background:#555e6a;border-top:2px dashed #555e6a;height:0"></div>Swept / Mitigated</div>
</div>

<script>
const canvas = document.getElementById('chart-canvas');
const ctx = canvas.getContext('2d');
let chartData = { candles: [], lines: [] };

// ── Responsive resize ──────────────────────────────────────────
function resize() {
  const container = document.getElementById('chart-container');
  const dpr = window.devicePixelRatio || 1;
  canvas.width  = container.clientWidth  * dpr;
  canvas.height = container.clientHeight * dpr;
  canvas.style.width  = container.clientWidth  + 'px';
  canvas.style.height = container.clientHeight + 'px';
  ctx.scale(dpr, dpr);
  render();
}
window.addEventListener('resize', resize);

// ── Tooltip on hover ──────────────────────────────────────────
let hoverIdx = -1;
canvas.addEventListener('mousemove', (e) => {
  const rect = canvas.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  if (!chartData.candles.length) return;
  const L = 60, R = document.getElementById('chart-container').clientWidth - 75;
  const slotW = (R - L) / chartData.candles.length;
  hoverIdx = Math.floor((mx - L) / slotW);
  if (hoverIdx < 0) hoverIdx = 0;
  if (hoverIdx >= chartData.candles.length) hoverIdx = chartData.candles.length - 1;
  render();
});
canvas.addEventListener('mouseleave', () => { hoverIdx = -1; render(); });

// ── Main draw function ─────────────────────────────────────────
function render() {
  const d = chartData;
  if (!d.candles || d.candles.length === 0) return;

  const W = canvas.width  / (window.devicePixelRatio || 1);
  const H = canvas.height / (window.devicePixelRatio || 1);
  ctx.clearRect(0, 0, W, H);

  // Layout margins
  const ML = 60;   // left  (time labels)
  const MR = 75;   // right (price scale)
  const MT = 16;
  const MB = 32;   // bottom (time labels)
  const CW = W - ML - MR;
  const CH = H - MT - MB;

  // Price range — include liq lines
  let lo = Math.min(...d.candles.map(c => c.low));
  let hi = Math.max(...d.candles.map(c => c.high));
  d.lines.forEach(l => {
    if (l.price < lo) lo = l.price;
    if (l.price > hi) hi = l.price;
  });
  const rng = hi - lo;
  lo -= rng * 0.05; hi += rng * 0.05;

  function cy(p) { return MT + CH - ((p - lo) / (hi - lo)) * CH; }

  // ── Background ──
  ctx.fillStyle = '#0d1117';
  ctx.fillRect(0, 0, W, H);
  ctx.fillStyle = '#161b22';
  ctx.fillRect(ML, MT, CW, CH);

  // ── Grid + Price Scale ──
  ctx.font = '10px monospace';
  const steps = 7;
  for (let i = 0; i <= steps; i++) {
    const p = lo + (hi - lo) * (i / steps);
    const y = cy(p);
    ctx.strokeStyle = '#21262d'; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(ML, y); ctx.lineTo(ML + CW, y); ctx.stroke();
    ctx.fillStyle = '#8b949e';
    ctx.fillText('$' + Math.round(p).toLocaleString(), ML + CW + 5, y + 3);
  }

  // ── Candles ──
  const n = d.candles.length;
  const slotW = CW / n;
  const bodyW = Math.max(1, slotW * 0.7);

  d.candles.forEach((c, i) => {
    const cx = ML + i * slotW + slotW / 2;
    const isGreen = c.close >= c.open;
    const col = isGreen ? '#3fb950' : '#f85149';
    const darkCol = isGreen ? '#215732' : '#6b1f1a';

    // Wick
    ctx.strokeStyle = col; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(cx, cy(c.high));
    ctx.lineTo(cx, cy(c.low));
    ctx.stroke();

    // Body
    const y1 = cy(Math.max(c.open, c.close));
    const y2 = cy(Math.min(c.open, c.close));
    const bh = Math.max(1, y2 - y1);

    // Hover highlight
    if (i === hoverIdx) {
      ctx.fillStyle = 'rgba(255,255,255,0.05)';
      ctx.fillRect(cx - slotW / 2, MT, slotW, CH);
    }

    ctx.fillStyle = col;
    ctx.fillRect(cx - bodyW / 2, y1, bodyW, bh);

    // Hollow body for green
    if (isGreen && bh > 3) {
      ctx.fillStyle = darkCol;
      ctx.fillRect(cx - bodyW / 2 + 1, y1 + 1, bodyW - 2, bh - 2);
      ctx.fillStyle = col;
    }
  });

  // ── Time Labels ──
  ctx.fillStyle = '#8b949e'; ctx.font = '10px monospace';
  const tStep = Math.max(1, Math.floor(n / 8));
  for (let i = 0; i < n; i += tStep) {
    const c = d.candles[i];
    const x = ML + i * slotW;
    const dt = new Date(c.time * 1000);
    const lbl = dt.toLocaleDateString('en-GB', {month:'2-digit', day:'2-digit'}) + ' ' +
                dt.toLocaleTimeString('en-GB', {hour:'2-digit', minute:'2-digit'});
    ctx.fillText(lbl, x, H - 10);
  }

  // ── Liquidity Lines ──
  d.lines.forEach(l => {
    const y = cy(l.price);
    if (y < MT || y > MT + CH) return; // out of view

    ctx.save();
    if (l.mitigated) {
      ctx.setLineDash([6, 5]);
      ctx.strokeStyle = '#3a4049';
      ctx.lineWidth = 1.5;
    } else {
      ctx.setLineDash([]);
      const liqCol = l.type === 'up' ? '#f85149' : '#3fb950';
      ctx.strokeStyle = liqCol;
      ctx.lineWidth = 2;
      ctx.shadowColor = liqCol;
      ctx.shadowBlur = 6;
    }

    ctx.beginPath();
    ctx.moveTo(ML, y);
    ctx.lineTo(ML + CW, y);
    ctx.stroke();
    ctx.restore();

    // Right-side price label badge
    const badgeCol = l.mitigated ? '#3a4049' : (l.type === 'up' ? '#f85149' : '#3fb950');
    const swept = l.mitigated;
    const label = (swept ? '✓ ' : '☢ ') + '$' + Math.round(l.price).toLocaleString();
    ctx.font = 'bold 10px monospace';
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = badgeCol;
    ctx.fillRect(ML + CW + 3, y - 8, tw + 8, 14);
    ctx.fillStyle = '#0d1117';
    ctx.fillText(label, ML + CW + 7, y + 2);

    // Left-side tag
    if (!swept) {
      const tag = l.type === 'up' ? 'UP LIQ' : 'DN LIQ';
      ctx.font = '10px monospace';
      ctx.fillStyle = badgeCol;
      ctx.fillText(tag, ML + 4, y - 4);
    }
  });

  // ── Crosshair / Tooltip ──
  if (hoverIdx >= 0 && hoverIdx < d.candles.length) {
    const c = d.candles[hoverIdx];
    const cx = ML + hoverIdx * slotW + slotW / 2;
    const chg = ((c.close - c.open) / c.open * 100);
    const chgTxt = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    const chgCol = chg >= 0 ? '#3fb950' : '#f85149';

    // Vertical crosshair
    ctx.strokeStyle = '#484f58'; ctx.lineWidth = 1; ctx.setLineDash([3,3]);
    ctx.beginPath(); ctx.moveTo(cx, MT); ctx.lineTo(cx, MT + CH); ctx.stroke();
    ctx.setLineDash([]);

    // Tooltip box
    const dt = new Date(c.time * 1000);
    const dtStr = dt.toLocaleString('en-GB', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'});
    const lines = [
      dtStr,
      'O: $' + c.open.toFixed(1),
      'H: $' + c.high.toFixed(1),
      'L: $' + c.low.toFixed(1),
      'C: $' + c.close.toFixed(1),
      chgTxt
    ];
    const bw = 120, bh = lines.length * 16 + 10;
    let bx = cx + 8;
    let by = MT + 10;
    if (bx + bw > W - MR) bx = cx - bw - 8;

    ctx.fillStyle = 'rgba(22,27,34,0.95)';
    ctx.strokeStyle = '#30363d'; ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.roundRect ? ctx.roundRect(bx, by, bw, bh, 6) : ctx.rect(bx, by, bw, bh);
    ctx.fill(); ctx.stroke();

    ctx.font = '11px monospace';
    lines.forEach((txt, i) => {
      ctx.fillStyle = i === 5 ? chgCol : (i === 0 ? '#8b949e' : '#c9d1d9');
      ctx.fillText(txt, bx + 8, by + 14 + i * 16);
    });
  }
}

// ── Fetch data and render ─────────────────────────────────────
async function fetchAndRender() {
  try {
    const resp = await fetch('/api/chart_data?symbol=BTC-USD');
    const data = await resp.json();
    if (!data || !data.candles) return;
    chartData = data;

    
    // Update Retail Radar
    if (data.retail) {
      document.getElementById('rr-ls').textContent = data.retail.ls_ratio.toFixed(2);
      const sentEl = document.getElementById('rr-sent');
      sentEl.textContent = data.retail.sentiment;
      sentEl.style.color = data.retail.color;
      document.getElementById('rr-fund').textContent = data.retail.funding;
      document.getElementById('rr-target').textContent = data.retail.whale_target;
    }
    
    // Update infobar

    const last = data.candles[data.candles.length - 1];
    const first = data.candles[0];
    const chg = ((last.close - first.open) / first.open * 100);
    const chgStr = (chg >= 0 ? '+' : '') + chg.toFixed(2) + '%';
    document.getElementById('ib-price').textContent = '$' + last.close.toLocaleString(undefined, {minimumFractionDigits:1});
    document.getElementById('ib-open').textContent  = '$' + last.open.toFixed(1);
    document.getElementById('ib-high').textContent  = '$' + last.high.toFixed(1);
    document.getElementById('ib-low').textContent   = '$' + last.low.toFixed(1);
    const chgEl = document.getElementById('ib-chg');
    chgEl.textContent = chgStr;
    chgEl.style.color = chg >= 0 ? '#3fb950' : '#f85149';

    const activeLines = data.lines || [];
    const ups = activeLines.filter(l => l.type==='up' && !l.mitigated).map(l => '$' + Math.round(l.price).toLocaleString());
    const dns = activeLines.filter(l => l.type==='down' && !l.mitigated).map(l => '$' + Math.round(l.price).toLocaleString());
    document.getElementById('ib-up').textContent = ups.join(' | ') || 'None';
    document.getElementById('ib-dn').textContent = dns.join(' | ') || 'None';

    render();
  } catch(e) { console.error('Fetch error:', e); }
}

window.addEventListener('load', () => {
  resize();
  fetchAndRender();
  setInterval(fetchAndRender, 3000);
});
</script>
</body>
</html>
"""

@app.route('/chart')
def chart_page():
    return CHART_HTML

if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000)
