# main.py - RPD Telegram Alert Bot (Render Web Service Version - FINAL v2)
import telegram
import time
import yfinance as yf
import pandas as pd
import pandas_ta as ta
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
    # Added auto_adjust=True to handle modern yfinance data cleanly
    data = yf.download(tickers=ticker, period='7d', interval=timeframe, progress=False, auto_adjust=True)
    data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
    return data

def calculate_rsi(series, period=14):
    """Calculate RSI manually using standard pandas operations"""
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

def calculate_rpd_signals(df, config):
    if df.empty or len(df) < config['adaptivePeriod']: 
        return None, 0, None
    
    # Calculate base indicators using reliable methods
    try:
        # Calculate RSI manually
        df[f'RSI_{config["rsiLen"]}'] = calculate_rsi(df['close'], config['rsiLen'])
        
        # Calculate ATR manually
        df['tr1'] = df['high'] - df['low']
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['true_range'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['ATR_14'] = df['true_range'].rolling(window=14).mean()
        
        # Calculate volume SMA
        df['vol_sma'] = df['volume'].rolling(window=config['volLookback']).mean()
        
        # Clean up temporary columns
        df.drop(['tr1', 'tr2', 'tr3', 'true_range'], axis=1, inplace=True)
            
    except Exception as e:
        logging.error(f"Error calculating indicators: {e}")
        return None, 0, None
    
    # --- FIXED FRACTAL LOGIC ---
    n = config['fractalStrength']
    window_size = 2 * n + 1
    
    # Calculate fractals using proper boolean operations
    df['is_fractal_high'] = df['high'] == df['high'].rolling(window_size, center=True).max()
    df['is_fractal_low'] = df['low'] == df['low'].rolling(window_size, center=True).min()
    
    # Ensure we have enough data for the fractal analysis
    if len(df) < (n + 2):
        return None, 0, None
    
    # Get the most recent completed candle data that can form a fractal
    last_candle_idx = -(n + 1)
    if abs(last_candle_idx) > len(df):
        return None, 0, None
        
    last_candle = df.iloc[last_candle_idx]
    
    # Check if we have the required RSI column
    rsi_column = f'RSI_{config["rsiLen"]}'
    if rsi_column not in df.columns or df[rsi_column].isna().all():
        logging.warning(f"RSI column {rsi_column} not found or all NaN values in data")
        return None, 0, None
    
    # Get RSI value and handle potential NaN
    rsi_value = last_candle[rsi_column]
    if pd.isna(rsi_value):
        logging.warning("RSI value is NaN, skipping signal")
        return None, 0, None
    
    # Define Signal Conditions using proper boolean checks
    is_peak_condition = (last_candle['is_fractal_high'] == True) and (rsi_value > config['rsiTop'])
    is_valley_condition = (last_candle['is_fractal_low'] == True) and (rsi_value < config['rsiBot'])
    
    # Placeholder for the complex probability calculation
    probability = 85.0 
    
    if is_peak_condition and probability >= config['minProbThreshold']: 
        return 'peak', probability, last_candle
    elif is_valley_condition and probability >= config['minProbThreshold']: 
        return 'valley', probability, last_candle
    else: 
        return None, 0, None

def check_assets():
    for asset_name, config in ASSET_CONFIG.items():
        logging.info(f"--- Checking {asset_name} ({config['ticker']}) on {config['timeframe']} ---")
        try:
            df = get_yfinance_data(config['ticker'], config['timeframe'])
            if df.empty:
                logging.warning(f"No data returned for {asset_name}")
                continue
            
            signal_type, prob, candle_data = calculate_rpd_signals(df.copy(), config)
            
            # Use candle's name (timestamp) to check for uniqueness
            current_signal_id = candle_data.name if signal_type else None

            if signal_type and current_signal_id != last_signal_bar.get(asset_name):
                last_signal_bar[asset_name] = current_signal_id
                emoji = "🔴" if signal_type == 'peak' else "🟢"
                signal_text = "PEAK REVERSAL (SHORT)" if signal_type == 'peak' else "VALLEY REVERSAL (LONG)"
                price = candle_data['close']
                message = (f"{emoji} *RPD Signal Detected* {emoji}\n\n"
                           f"*Asset:* {asset_name} ({config['ticker']})\n*Timeframe:* {config['timeframe']}\n"
                           f"*Signal:* {signal_text}\n*Price:* `{price:.4f}`\n"
                           f"*Probability:* `{prob:.2f}%` (Simplified)\n\nCheck chart for confirmation.")
                send_telegram_alert(message)
            else: 
                logging.info(f"No new signal for {asset_name}.")
        except Exception as e: 
            logging.error(f"An error occurred while checking {asset_name}: {e}")
        time.sleep(3)

if __name__ == '__main__':
    keep_alive() # Starts the web server
    send_telegram_alert("✅ RPD Alert Bot is now LIVE and fully operational!")
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
            send_telegram_alert(f"🚨 BOT CRITICAL ERROR: {e}. Restarting loop in 60s.")
            time.sleep(60)
