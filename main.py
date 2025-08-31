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

def calculate_rpd_signals(df, config):
    if df.empty or len(df) < config['adaptivePeriod']: return None, 0, None
    
    # Calculate base indicators
    df.ta.rsi(length=config['rsiLen'], append=True)
    df.ta.atr(length=14, append=True)
    df.ta.sma(close='volume', length=config['volLookback'], col_names=('vol_sma',), append=True)
    
    # --- THIS IS THE CORRECTED FRACTAL LOGIC ---
    # This is a much cleaner and more reliable way to find local peaks and valleys.
    n = config['fractalStrength']
    window_size = 2 * n + 1
    df['is_fractal_high'] = df['high'] == df['high'].rolling(window_size, center=True).max()
    df['is_fractal_low'] = df['low'] == df['low'].rolling(window_size, center=True).min()
    
    # Get the most recent completed candle data
    # We look at the candle from n+1 bars ago to allow the fractal to form completely
    last_candle = df.iloc[-(n + 1)]
    
    # Define Signal Conditions
    is_peak_condition = last_candle['is_fractal_high'] and last_candle[f'RSI_{config["rsiLen"]}'] > config['rsiTop']
    is_valley_condition = last_candle['is_fractal_low'] and last_candle[f'RSI_{config["rsiLen"]}'] < config['rsiBot']
    
    # Placeholder for the complex probability calculation
    probability = 85.0 
    
    if is_peak_condition and probability >= config['minProbThreshold']: return 'peak', probability, last_candle
    elif is_valley_condition and probability >= config['minProbThreshold']: return 'valley', probability, last_candle
    else: return None, 0, None

def check_assets():
    for asset_name, config in ASSET_CONFIG.items():
        logging.info(f"--- Checking {asset_name} ({config['ticker']}) on {config['timeframe']} ---")
        try:
            df = get_yfinance_data(config['ticker'], config['timeframe'])
            if df.empty:
                logging.warning(f"No data returned for {asset_name}"); continue
            
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
            else: logging.info(f"No new signal for {asset_name}.")
        except Exception as e: logging.error(f"An error occurred while checking {asset_name}: {e}")
        time.sleep(3)

if __name__ == '__main__':
    keep_alive() # Starts the web server
    send_telegram_alert("✅ RPD Alert Bot is now LIVE and fully operational!")
    while True:
        try:
            check_assets()
            logging.info("Cycle complete. Waiting for 5 minutes...")
            time.sleep(300)
        except KeyboardInterrupt: print("Bot stopped by user."); break
        except Exception as e:
            logging.critical(f"A critical error occurred in the main loop: {e}")
            send_telegram_alert(f"🚨 BOT CRITICAL ERROR: {e}. Restarting loop in 60s.")
            time.sleep(60)
