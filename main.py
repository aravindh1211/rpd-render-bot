# main.py - RPD Telegram Alert Bot (Render - The Final Version)
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
        'ticker': '^NSEI', 'timeframe': '15m',
        'fractalStrength': 2, 'rsiLen': 17, 'rsiTop': 65, 'rsiBot': 40
    },
    'BITCOIN': {
        'ticker': 'BTC-USD', 'timeframe': '1h',
        'fractalStrength': 2, 'rsiLen': 14, 'rsiTop': 70, 'rsiBot': 30
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
    if data.empty: return pd.DataFrame()
    data.rename(columns={"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}, inplace=True)
    return data.dropna()

def calculate_rpd_signals(df, config):
    if df.empty or len(df) < 50: return None, 0, None
    
    # Calculate Indicators
    rsi_col = f"RSI_{config['rsiLen']}"
    df[rsi_col] = ta.rsi(df['close'], length=config['rsiLen'])
    
    n = config['fractalStrength']
    win = 2 * n + 1
    df['is_fractal_high'] = df['high'] == df['high'].rolling(win, center=True).max()
    df['is_fractal_low'] = df['low'] == df['low'].rolling(win, center=True).min()
    
    # --- THIS IS THE DEFINITIVE FIX ---
    # We will look at the last fully formed candle directly.
    # .iloc[-N] accesses the Nth-to-last item. This returns a single, unambiguous value.
    try:
        candle_pos = -(n + 1)
        
        rsi_value = df[rsi_col].iloc[candle_pos]
        is_high = df['is_fractal_high'].iloc[candle_pos]
        is_low = df['is_fractal_low'].iloc[candle_pos]
        candle_data = df.iloc[candle_pos]

        # Check for NaN (Not a Number) which happens at the start of calculations
        if pd.isna(rsi_value):
            return None, 0, None

    except IndexError:
        # This happens if the dataframe is too small, a safe exit.
        return None, 0, None

    # Now we have simple Python types, so there is no ambiguity.
    is_peak_condition = is_high and rsi_value > config['rsiTop']
    is_valley_condition = is_low and rsi_value < config['rsiBot']
    
    probability = 85.0
    
    if is_peak_condition: return 'peak', probability, candle_data
    elif is_valley_condition: return 'valley', probability, candle_data
    else: return None, 0, None

def check_assets():
    for asset_name, config in ASSET_CONFIG.items():
        logging.info(f"--- Checking {asset_name} ({config['ticker']}) on {config['timeframe']} ---")
        try:
            df = get_yfinance_data(config['ticker'], config['timeframe'])
            if df.empty:
                logging.warning(f"No data for {asset_name}"); continue
            
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
                               f"*Probability:* `{prob:.2f}%` (Simplified)")
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
            print("Bot stopped by user."); break
        except Exception as e:
            logging.critical(f"A critical error occurred in the main loop: {e}")
            send_telegram_alert(f"🚨 BOT ERROR: {e}. Restarting in 60s.")
            time.sleep(60)
