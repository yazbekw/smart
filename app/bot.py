import os
import ccxt
import numpy as np
import pandas as pd
from datetime import datetime
from tensorflow.keras.models import load_model
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

# === إعدادات التداول ===
TRADING_SYMBOL = os.getenv('TRADING_SYMBOL', 'BTC/USDT')
INVESTMENT_AMOUNT = float(os.getenv('INVESTMENT_AMOUNT', 10))

# === إعدادات API ===
exchange = ccxt.coinex({
    'apiKey': os.getenv('COINEX_API_KEY'),
    'secret': os.getenv('COINEX_API_SECRET'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
    }
})

# === حالة البوت ===
bot_status = {
    'running': os.getenv('BOT_START_RUNNING', 'true').lower() == 'true',
    'last_check': None,
    'active_trade': None,
    'trade_history': [],
    'error': None,
    'model_loaded': False,
    'settings': {
        'stop_loss': 0.95,     # 5% خسارة
        'take_profit': 1.05   # 5% ربح
    }
}

# === تحميل النموذج ===
MODEL_PATH = os.path.join("..", "models", "yazbekw.keras")
try:
    model = load_model(MODEL_PATH)
    print("✅ تم تحميل النموذج بنجاح")
    bot_status['model_loaded'] = True
except Exception as e:
    model = None
    bot_status['error'] = f"خطأ في تحميل النموذج: {str(e)}"
    print(f"❌ خطأ في تحميل النموذج: {str(e)}")

# === جلب بيانات السوق ===
def get_live_data(limit=100):
    """جلب بيانات الشموع (OHLC) من Coinex"""
    try:
        ohlcv = exchange.fetch_ohlcv(TRADING_SYMBOL, timeframe='1h', limit=limit)
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        return df
    except Exception as e:
        bot_status['error'] = f"فشل في جلب البيانات: {str(e)}"
        print(f"❌ فشل في جلب البيانات: {str(e)}")
        return None

# === إعداد البيانات للتنبؤ ===
def prepare_features(df):
    """تحويل البيانات إلى شكل يفهمه النموذج"""
    try:
        features = df[['open', 'high', 'low', 'close', 'volume']].values[-1:]
        X = features.reshape((1, 1, features.shape[1]))
        return X
    except Exception as e:
        bot_status['error'] = f"فشل في معالجة البيانات: {str(e)}"
        return None

# === التنبؤ بالإشارة ===
def predict_signal():
    if not bot_status['model_loaded']:
        return None

    df = get_live_data()
    if df is None:
        return None

    X = prepare_features(df)
    if X is None:
        return None

    try:
        prediction = model.predict(X, verbose=0)
        signal = int((prediction > 0.5).astype(int)[0][0])
        bot_status['error'] = None
        return signal
    except Exception as e:
        bot_status['error'] = f"خطأ في التنبؤ: {str(e)}"
        return None

# === تنفيذ أمر التداول ===
def execute_auto_trade(signal):
    if signal is None:
        return

    try:
        current_price = exchange.fetch_ticker(TRADING_SYMBOL)['last']
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if signal == 1:  # شراء
            if bot_status['active_trade'] is None:
                amount = INVESTMENT_AMOUNT / current_price
                order = exchange.create_market_buy_order(TRADING_SYMBOL, amount)

                trade_record = {
                    'type': 'BUY',
                    'amount': amount,
                    'price': current_price,
                    'timestamp': timestamp,
                    'order': order
                }

                bot_status['active_trade'] = trade_record
                bot_status['trade_history'].append(trade_record)
                print(f"[BUY] {amount:.8f} BTC at ${current_price:.2f}")

        elif signal == 0:  # بيع
            if bot_status['active_trade'] and bot_status['active_trade']['amount'] > 0:
                amount = bot_status['active_trade']['amount']
                order = exchange.create_market_sell_order(TRADING_SYMBOL, amount)

                profit = (current_price - bot_status['active_trade']['price']) * amount

                trade_record = {
                    'type': 'SELL',
                    'amount': amount,
                    'price': current_price,
                    'timestamp': timestamp,
                    'order': order,
                    'buy_price': bot_status['active_trade']['price'],
                    'profit': profit
                }

                bot_status['trade_history'].append(trade_record)
                bot_status['active_trade'] = None
                print(f"[SELL] {amount:.8f} BTC at ${current_price:.2f}, Profit: ${profit:.2f}")

        bot_status['last_check'] = timestamp

    except Exception as e:
        bot_status['error'] = f"خطأ في تنفيذ الأمر: {str(e)}"
        print(f"❌ خطأ في تنفيذ الأمر: {str(e)}")
