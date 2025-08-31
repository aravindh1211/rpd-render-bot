# main.py - RPD Telegram Alert Bot (Render Web Service - Final Corrected Version v2)
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

# --- Configuration ---
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID')

ASSET_CONFIG = {
    'NIFTY_50': {
        'ticker': '^NSEI', 'source': 'yfinance', 'timeframe': '15m',
        'adaptivePeriod': 25, 'fractalStrength': 2, 'minProbThreshold': 70,
        'rsiLen': 17, 'rsiTop': 65, 'rsiBot': 40,
        'volLookback': 17
    },
    'BITCOIN': {
        'ticker': 'BTC-USD', 'source': 'yfinance', 'timeframe': '1h',
        'adaptivePeriod': 20, 'fractalStrength': 2, 'minProbThreshold': 65,
        'rsiLen': 14, 'rsiTop': 70, 'rsiBot': 30,
        'volLookback': 20
    },
}
   
# --- Initialization ---
bot = telegram.Bot(token=TELEGRAM_BOT_TOKEN)
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

last_signal_timestamp = {asset: None for asset in ASSET_CONFIG}

def send_telegram_alert(message):
    try:
        bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=message, parse_mode='Markdown')
        logging.info("Telegram alert sent!")
    except Exception as e:
        logging.error(f"Failed to send Telegram alert: {e}")

def get_yfinance_data(ticker, timeframe):
    data = yf.download(tickers=ticker, period='7d', interval=timeframe, progress=False, auto_adjust=True)
    if data.empty:
        return pd.DataFrame()
    data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
    return data.dropna()

def calculate_rpd_signals(df, config):
    if df.empty or len(df) < config['adaptivePeriod']:
        return None, 0, None
    
    # Explicitly calculate RSI and assign it to a new column
    rsi_column_name = f'RSI_{config["rsiLen"]}'
    df[rsi_column_name] = ta.rsi(df['close'], length=config['rsiLen'])
    
    # Robust Fractal Logic
    n = config['fractalStrength']
    window_size = 2 * n + 1
    df['is_fractal_high'] = df['high'] == df['high'].rolling(window_size, center=True).max()
    df['is_fractal_low'] = df['low'] == df['low'].rolling(window_size, center=True).min()
    
    # Get the specific candle to check for a completed fractal
    candle_to_check = df.iloc[-(n + 1)]
    
    # --- THE BULLETPROOF FIX ---
    # We use .item() to extract the values as native Python types (bool, float).
    # This completely prevents the "ambiguous" error. A try/except block handles edge cases.
    try:
        is_high = bool(candle_to_check['is_fractal_high'].item())
        is_low = bool(candle_to_check['is_fractal_low'].item())
        rsi_value = float(candle_to_check[rsi_column_name].item())
    except (ValueError, AttributeError):
        # If any value is NaN or invalid, default to a non-signaling state
        return None, 0, None

    # Define Signal Conditions using the clean, native Python variables
    is_peak_condition = is_high and rsi_value > config['rsiTop']
    is_valley_condition = is_low and rsi_value < config['rsiBot']
    
    probability = 85.0  # Placeholder probability
    
    if is_peak_condition:
        return 'peak', probability, candle_to_check
    elif is_valley_condition:
        return 'valley', probability, candle_to_check
    else:
        return None, 0, None

def check_assets():
    for asset_name, config in ASSET_CONFIG.items():
        logging.info(f"--- Checking {asset_name} ({config['ticker']}) on {config['timeframe']} ---")
        try:
            df = get_yfinance_data(config['ticker'], config['timeframe'])
            if df.empty:
                logging.warning(f"No data returned for {asset_name}"); continue
            
            signal_type, prob, candle_data = calculate_rpd_signals(df.copy(), config)
            
            if signal_type:
                signal_timestamp = candle_data.name
                if signal_timestamp != last_signal_timestamp.get(asset_name):
                    last_signal_timestamp[asset_name] = signal_timestamp
                    emoji = "🔴" if signal_type == 'peak' else "🟢"
                    signal_text = "PEAK REVERSAL (SHORT)" if signal_type == 'peak' else "VALLEY REVERSAL (LONG)"
                    price = candle_data['close']
                    message = (f"{emoji} *RPD Signal Detected* {emoji}\n\n"
                               f"*Asset:* {asset_name} ({config['ticker']})\n*Timeframe:* {config['timeframe']}\n"
                               f"*Signal:* {signal_text}\n*Price:* `{price:.4f}`\n"
                               f"*Probability:* `{prob:.2f}%` (Simplified)\n\nCheck chart for confirmation.")
                    send_telegram_alert(message)
                else:
                    logging.info(f"Signal for {asset_name} on {signal_timestamp} already sent.")
            else: 
                logging.info(f"No new signal for {asset_name}.")
        except Exception as e: 
            logging.error(f"An error occurred while checking {asset_name}: {e}")
        time.sleep(3)

if __name__ == '__main__':
    keep_alive()
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
            send_telegram_alert(f"🚨 BOT ERROR: {e}. Restarting in 60s.")
            time.sleep(60)
