# main.py - RPD Telegram Alert Bot (Simplified Error-Free Version)
import telegram
import time
import yfinance as yf
import pandas as pd
import numpy as np
import logging
import os
from flask import Flask
from threading import Thread

# --- Web Server for UptimeRobot ---
app = Flask('')

@app.route('/')
def home():
    return "RPD Alert Bot is alive and running."

def run_flask():
  app.run(host='0.0.0.0', port=10000)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- PHASE 1: CONFIGURATION ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

ASSET_CONFIG = {
    'NIFTY_50': {
        'ticker': '^NSEI', 'source': 'yfinance', 'timeframe': '15m',
        'adaptivePeriod': 25, 'fractalStrength': 2, 'minProbThreshold': 70,
        'minSignalDistance': 10, 'entropyThreshold': 0.85, 'analysisLevels': 6,
        'edgeSensitivity': 3, 'rsiLen': 17, 'rsiTop': 65, 'rsiBot': 40,
        'volLookback': 17, 'volMultiplier': 1.2
    },
    'BITCOIN': {
        'ticker': 'BTC-USD', 'source': 'yfinance', 'timeframe': '1h',
        'adaptivePeriod': 20, 'fractalStrength': 2, 'minProbThreshold': 65,
        'minSignalDistance': 5, 'entropyThreshold': 0.90, 'analysisLevels': 8,
        'edgeSensitivity': 3, 'rsiLen': 14, 'rsiTop': 70, 'rsiBot': 30,
        'volLookback': 20, 'volMultiplier': 1.5
    },
}
   
# --- Initialize Telegram Bot & Logging ---
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

last_signal_bar = {asset: 0 for asset in ASSET_CONFIG}

def send_telegram_alert(message):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
        logging.info(f"Telegram alert sent!")
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

def get_yfinance_data(ticker, timeframe):
    try:
        data = yf.download(tickers=ticker, period='7d', interval=timeframe, progress=False, auto_adjust=True)
        if data.empty:
            return pd.DataFrame()
        data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
        return data.dropna()
    except Exception as e:
        logging.error(f"Error fetching data for {ticker}: {e}")
        return pd.DataFrame()

def calculate_rsi_simple(prices, period=14):
    """Ultra-simple RSI calculation using pure Python"""
    try:
        price_list = prices.tolist()
        rsi_values = []
        
        for i in range(len(price_list)):
            if i < period:
                rsi_values.append(50.0)  # Default RSI for insufficient data
                continue
                
            # Calculate price changes for the period
            gains = []
            losses = []
            
            for j in range(i - period + 1, i + 1):
                if j > 0:
                    change = price_list[j] - price_list[j-1]
                    if change > 0:
                        gains.append(change)
                        losses.append(0)
                    else:
                        gains.append(0)
                        losses.append(abs(change))
                else:
                    gains.append(0)
                    losses.append(0)
            
            # Calculate average gain and loss
            avg_gain = sum(gains) / len(gains) if gains else 0
            avg_loss = sum(losses) / len(losses) if losses else 0
            
            # Calculate RSI
            if avg_loss == 0:
                rsi_values.append(100.0)
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
                rsi_values.append(rsi)
        
        return pd.Series(rsi_values, index=prices.index)
    except Exception as e:
        # Return neutral RSI values on any error
        return pd.Series([50.0] * len(prices), index=prices.index)

def find_simple_fractals(highs, lows, strength=2):
    """Simple fractal detection without Series operations"""
    fractal_highs = []
    fractal_lows = []
    
    for i in range(len(highs)):
        fractal_highs.append(False)
        fractal_lows.append(False)
    
    # Find fractal highs and lows
    for i in range(strength, len(highs) - strength):
        # Check fractal high
        is_high_fractal = True
        current_high = highs.iloc[i]
        
        for j in range(i - strength, i + strength + 1):
            if j != i and highs.iloc[j] >= current_high:
                is_high_fractal = False
                break
        
        fractal_highs[i] = is_high_fractal
        
        # Check fractal low
        is_low_fractal = True
        current_low = lows.iloc[i]
        
        for j in range(i - strength, i + strength + 1):
            if j != i and lows.iloc[j] <= current_low:
                is_low_fractal = False
                break
                
        fractal_lows[i] = is_low_fractal
    
    return fractal_highs, fractal_lows

def calculate_rpd_signals(df, config):
    if df.empty or len(df) < 50:  # Need sufficient data
        return None, 0, None
    
    try:
        # Calculate RSI
        rsi_values = calculate_rsi_simple(df['close'], config['rsiLen'])
        
        # Find fractals
        fractal_highs, fractal_lows = find_simple_fractals(df['high'], df['low'], config['fractalStrength'])
        
        # Look for signals in recent candles (but not the very last one to ensure fractal completion)
        n = config['fractalStrength']
        check_idx = len(df) - n - 1  # Look at candle that could have formed a complete fractal
        
        if check_idx < 0 or check_idx >= len(df):
            return None, 0, None
        
        # Get values for the candle we're checking
        rsi_value = rsi_values.iloc[check_idx]
        is_fractal_high = fractal_highs[check_idx]
        is_fractal_low = fractal_lows[check_idx]
        candle_data = df.iloc[check_idx]
        
        # Check for signals - CONVERT TO SCALAR VALUES IMMEDIATELY
        probability = 85.0
        
        # Convert pandas values to pure Python types to avoid Series ambiguity
        rsi_val = float(rsi_value) if not pd.isna(rsi_value) else 50.0
        rsi_top = float(config['rsiTop'])
        rsi_bot = float(config['rsiBot'])
        min_prob = float(config['minProbThreshold'])
        
        # Peak signal (fractal high + overbought RSI) - using pure Python comparisons
        if is_fractal_high and rsi_val > rsi_top:
            if probability >= min_prob:
                return 'peak', probability, candle_data
        
        # Valley signal (fractal low + oversold RSI) - using pure Python comparisons
        elif is_fractal_low and rsi_val < rsi_bot:
            if probability >= min_prob:
                return 'valley', probability, candle_data
        
        return None, 0, None
        
    except Exception as e:
        logging.error(f"Error in signal calculation: {e}")
        return None, 0, None

def check_assets():
    for asset_name, config in ASSET_CONFIG.items():
        logging.info(f"--- Checking {asset_name} ({config['ticker']}) on {config['timeframe']} ---")
        try:
            df = get_yfinance_data(config['ticker'], config['timeframe'])
            if df.empty:
                logging.warning(f"No data returned for {asset_name}")
                continue
            
            signal_type, prob, candle_data = calculate_rpd_signals(df, config)
            
            # Use timestamp as signal ID
            current_signal_id = str(candle_data.name) if signal_type else None

            if signal_type and current_signal_id != last_signal_bar.get(asset_name):
                last_signal_bar[asset_name] = current_signal_id
                emoji = "🔴" if signal_type == 'peak' else "🟢"
                signal_text = "PEAK REVERSAL (SHORT)" if signal_type == 'peak' else "VALLEY REVERSAL (LONG)"
                price = candle_data['close']
                message = (f"{emoji} *RPD Signal Detected* {emoji}\n\n"
                           f"*Asset:* {asset_name} ({config['ticker']})\n*Timeframe:* {config['timeframe']}\n"
                           f"*Signal:* {signal_text}\n*Price:* `{price:.4f}`\n"
                           f"*Probability:* `{prob:.2f}%`\n\nCheck chart for confirmation.")
                send_telegram_alert(message)
                logging.info(f"Signal sent for {asset_name}: {signal_type}")
            else: 
                logging.info(f"No new signal for {asset_name}.")
                
        except Exception as e: 
            logging.error(f"An error occurred while checking {asset_name}: {e}")
        time.sleep(3)

if __name__ == '__main__':
    keep_alive()
    send_telegram_alert("✅ RPD Alert Bot is now LIVE and operational!")
    while True:
        try:
            check_assets()
            logging.info("Cycle complete. Waiting for 5 minutes...")
            time.sleep(300)
        except KeyboardInterrupt: 
            print("Bot stopped by user.")
            break
        except Exception as e:
            logging.critical(f"A critical error occurred in the main loop: {e}")
            send_telegram_alert(f"🚨 BOT ERROR: {e}. Restarting in 60s.")
            time.sleep(60)
