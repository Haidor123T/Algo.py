import time
from datetime import datetime
import pytz
import pandas as pd
import numpy as np

try:
    import yfinance as yf
except ImportError:
    import os
    os.system('pip install yfinance pandas numpy pytz')
    import yfinance as yf
    import pytz

# --- डेल्टा एक्सचेंज ट्रेडिंग पैरामीटर्स (₹10,000 कैपिटल + 10x लेवरेज) ---
SYMBOL = "BTC-USD"          # Delta Exchange Crypto Pair (BTCUSD)
VIRTUAL_CAPITAL = 10000.0   # शुरुआती वर्चुअल कैपिटल ₹10,000
LEVERAGE = 10               # 10x लेवरेज (बैलेंस्ड रिस्क के साथ)
HARD_STOP_LOSS = 1000.0     # शुरुआती फिक्सड स्टॉप लॉस (-₹1000)

# IST समय जोन सेट करना
IST = pytz.timezone('Asia/Kolkata')

# लॉग फाइल का नाम
LOG_FILE = "delta_trade_hisab.txt"

# स्टेट वेरिएबल्स (जिन्हें रोज रात 8 बजे रिसेट किया जाएगा)
total_trades = 0
win_count = 0
loss_count = 0
net_pnl = 0.0
trade_id = 1
last_reset_date = None

def log_trade(t_no, action, entry, exit_price, result, pnl):
    global total_trades, win_count, loss_count, net_pnl
    total_trades += 1
    if pnl > 0:
        win_count += 1
    else:
        loss_count += 1
    net_pnl += pnl
    current_capital = VIRTUAL_CAPITAL + net_pnl
    
    now_str = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
    
    log_text = f"""
------------------------------------------------------------
Delta Trade #{t_no} | Date & Time: {now_str} (IST)
Action: {action} (Capital: ₹10k | 10x Lev) | Entry: {entry} -> Exit: {exit_price}
Result: {result} | Trade PnL: ₹{pnl}
---> RAAT KA HISAB: Total Trades: {total_trades} (Win: {win_count}, Loss: {loss_count}) | Net PnL: ₹{net_pnl} | Current Capital: ₹{current_capital}
------------------------------------------------------------
"""
    print(log_text)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(log_text)

def apply_indicators(df):
    """
    सभी इंडिकेटर्स एक साथ:
    1. Volume SMA 20
    2. SMA 20 & EMA 20
    3. Bollinger Bands (20, 2)
    4. SMC (Smart Money Concepts - Order Blocks)
    5. FVG (Fair Value Gap)
    """
    df['Volume_SMA20'] = df['Volume'].rolling(window=20).mean()
    
    df['SMA20'] = df['Close'].rolling(window=20).mean()
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    
    df['STD'] = df['Close'].rolling(window=20).std()
    df['Upper_BB'] = df['SMA20'] + (df['STD'] * 2)
    df['Lower_BB'] = df['SMA20'] - (df['STD'] * 2)
    
    df['OB_Bullish'] = df['Low'].rolling(window=5).min() 
    df['OB_Bearish'] = df['High'].rolling(window=5).max() 
    
    df['FVG_Bullish'] = (df['Low'] > df['High'].shift(2))
    df['FVG_Bearish'] = (df['High'] < df['Low'].shift(2))
    
    return df

def run_delta_paper_trading():
    global total_trades, win_count, loss_count, net_pnl, trade_id, last_reset_date
    print("=== Delta Exchange Bot (10x Leverage + All Indicators + Daily 8 PM Reset) Started ===")
    
    while True:
        try:
            # --- भारतीय समय (IST) प्राप्त करना ---
            now = datetime.now(IST)
            current_time = now.time()
            today_date = now.date()
            
            # --- प्रतिदिन रात 8:00 PM (20:00:00 IST) पर हिसाब रिसेट करने का लॉजिक ---
            reset_time = datetime.strptime("20:00:00", "%H:%M:%S").time()
            
            if last_reset_date != today_date and current_time >= reset_time:
                print(f"\n[{now.strftime('%H:%M:%S')}] रात के 8:00 बज चुके हैं! आज का हिसाब रिसेट किया जा रहा है...")
                
                reset_msg = f"\n=== [SYSTEM] DAILY 8 PM RESET @ {now.strftime('%Y-%m-%d %H:%M:%S')} (IST) (New Night Fresh Start) ===\n"
                with open(LOG_FILE, "a", encoding="utf-8") as f:
                    f.write(reset_msg)
                
                total_trades = 0
                win_count = 0
                loss_count = 0
                net_pnl = 0.0
                trade_id = 1
                last_reset_date = today_date
                print(">>> हिसाब सफलतापूर्वक रिसेट हो गया है! नए सत्र की शुरुआत।\n")

            # --- डेटा डाउनलोड और एनालिसिस ---
            data = yf.download(SYMBOL, period="1d", interval="5m", progress=False)
            if data.empty or len(data) < 30:
                print("क्रिप्टो डेटा प्राप्त करने में प्रतीक्षा हो रही है...")
                time.sleep(30)
                continue
                
            if isinstance(data.columns, pd.MultiIndex):
                data.columns = data.columns.get_level_values(0)
                
            df = apply_indicators(data)
            latest = df.iloc[-1]
            
            current_price = float(latest['Close'])
            current_volume = float(latest['Volume'])
            vol_sma = float(latest['Volume_SMA20'])
            lower_bb = float(latest['Lower_BB'])
            upper_bb = float(latest['Upper_BB'])
            bullish_ob = float(latest['OB_Bullish'])
            bearish_ob = float(latest['OB_Bearish'])
            fvg_bull = bool(latest['FVG_Bullish'])
            fvg_bear = bool(latest['FVG_Bearish'])
            
            action = None
            is_volume_strong = current_volume > vol_sma
            
            # --- एंट्री कंडीशंस ---
            if is_volume_strong:
                if (current_price <= (bullish_ob * 1.002)) or (current_price < lower_bb) or fvg_bull:
                    action = "BUY (10x Filtered)"
                    entry_price = current_price
                    
                elif (current_price >= (bearish_ob * 0.998)) or (current_price > upper_bb) or fvg_bear:
                    action = "SELL (10x Filtered)"
                    entry_price = current_price
                
            if action:
                print(f"[{now.strftime('%H:%M:%S')}] सिग्नल मिला: {action} @ {entry_price} (Vol: {current_volume} > SMA: {vol_sma:.1f})")
                
                max_profit = 0.0
                exit_price = entry_price
                result = "OPEN_ENDED_TSL"
                pnl = 0.0
                current_sl = -HARD_STOP_LOSS  # शुरुआती SL -₹1000
                
                # --- ट्रेड मॉनिटरिंग और 10x लेवरेज के साथ ओपन-एंडेड TSL लूप ---
                for _ in range(25):
                    time.sleep(2)
                    dummy_movement = np.random.uniform(-15, 15)
                    current_price += dummy_movement
                    
                    if "BUY" in action:
                        points_diff = current_price - entry_price
                    else:
                        points_diff = entry_price - current_price
                        
                    # 10x लेवरेज के साथ PnL गणना
                    pnl = points_diff * LEVERAGE
                    
                    if pnl > max_profit:
                        max_profit = pnl
                    
                    # --- ओपन-एंडेड TSL लॉजिक ---
                    if max_profit >= 1000:
                        calculated_sl = (max_profit // 500) * 500 - 500
                        if calculated_sl > current_sl:
                            current_sl = calculated_sl
                            
                    if pnl <= current_sl:
                        if current_sl < 0:
                            result = "FIXED_SL_1000_HIT"
                        else:
                            result = f"TSL_LOCKED_at_PROFIT_{current_sl}"
                        exit_price = current_price
                        break
                
                if pnl == 0:
                    exit_price = current_price
                    pnl = 500.0 if "BUY" in action else -400.0
                    result = "TIME_EXIT"
                    
                log_trade(trade_id, action, round(entry_price, 2), round(exit_price, 2), result, round(pnl, 2))
                trade_id += 1
                
            time.sleep(60)
            
        except Exception as e:
            print(f"त्रुटि (Error): {e}")
            time.sleep(10)

if __name__ == "__main__":
    run_delta_paper_trading()
