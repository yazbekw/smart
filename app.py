import os
import ccxt
import pandas as pd
import time
import schedule
import threading
import numpy as np
from datetime import datetime
from tensorflow.keras.models import load_model
from flask import Flask, render_template

app = Flask(__name__)

# === إعدادات التداول ===
symbol = os.getenv('TRADING_SYMBOL', 'BTC/USDT')
investment_usdt = float(os.getenv('INVESTMENT_AMOUNT', 9))

# === إعدادات API ===
exchange = ccxt.coinex({
    'apiKey': os.getenv('COINEX_API_KEY'),
    'secret': os.getenv('COINEX_API_SECRET'),
})

# === حالة البوت ===
bot_status = {
    'running': os.getenv('BOT_START_RUNNING', 'true').lower() == 'true',
    'last_check': None,
    'active_trade': None,
    'trade_history': [],
    'balance': None,
    'error': None,
    'settings': {
        'max_active_trades': int(os.getenv('MAX_ACTIVE_TRADES', 1)),
        'trade_timeout': int(os.getenv('TRADE_TIMEOUT_HOURS', 24)),
        'stop_loss': float(os.getenv('STOP_LOSS_PERCENT', 0.95)),
        'take_profit': float(os.getenv('TAKE_PROFIT_PERCENT', 1.05))
    }
}

# === تحميل النموذج ===
try:
    model = load_model('yazbekw.keras')
    print("✅ تم تحميل النموذج بنجاح")
    bot_status['model_loaded'] = True
except Exception as e:
    print(f"❌ خطأ في تحميل النموذج: {str(e)}")
    bot_status['error'] = f"خطأ في تحميل النموذج: {str(e)}"
    bot_status['model_loaded'] = False
    model = None

# === التحقق من صحة النموذج ===
def validate_model():
    if model is None:
        bot_status['error'] = "النموذج غير محمل"
        return False
    
    try:
        test_data = np.random.rand(1, 50)
        prediction = model.predict(test_data, verbose=0)
        return True
    except Exception as e:
        bot_status['error'] = f"النموذج غير صالح: {str(e)}"
        return False

# === الحصول على الرصيد ===
def get_balance():
    try:
        balance = exchange.fetch_balance()
        bot_status['balance'] = {
            'USDT': balance['USDT']['free'],
            'coin': balance[symbol.split('/')[0]]['free']
        }
        bot_status['error'] = None
        return True
    except Exception as e:
        bot_status['error'] = f"Error fetching balance: {str(e)}"
        return False

# === الحصول على البيانات التاريخية ===
def get_live_data():
    try:
        bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        bot_status['error'] = None
        return df
    except Exception as e:
        bot_status['error'] = f"Error fetching data: {str(e)}"
        return None

# === تحضير البيانات ===
def prepare_features(df):
    if df is None:
        return None
        
    features = df['close'].values[-50:]
    features = features.reshape(1, -1)
    return features

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
        signal = (prediction > 0.5).astype(int)[0][0]
        bot_status['error'] = None
        return signal
    except Exception as e:
        bot_status['error'] = f"Prediction error: {str(e)}"
        return None

# === تنفيذ الصفقة ===
def execute_trade(signal):
    if signal is None:
        return
        
    try:
        current_price = exchange.fetch_ticker(symbol)['last']
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if bot_status['active_trade'] is not None:
            return
            
        if signal == 1:  # شراء
            if not get_balance():
                return
                
            if bot_status['balance']['USDT'] >= investment_usdt:
                amount = investment_usdt / current_price
                order = exchange.create_market_buy_order(symbol, amount)
                
                trade_record = {
                    'type': 'BUY',
                    'amount': amount,
                    'price': current_price,
                    'timestamp': timestamp,
                    'order': order
                }
                
                bot_status['active_trade'] = trade_record
                bot_status['trade_history'].append(trade_record)
                print(f"[BUY] {amount:.8f} {symbol.split('/')[0]} at ${current_price:.2f}")
        
        elif signal == 0:  # بيع
            if bot_status['active_trade'] is None:
                return
                
            if not get_balance():
                return
                
            coin = symbol.split('/')[0]
            if bot_status['balance'][coin] > 0:
                amount = bot_status['balance'][coin]
                order = exchange.create_market_sell_order(symbol, amount)
                
                trade_record = {
                    'type': 'SELL',
                    'amount': amount,
                    'price': current_price,
                    'timestamp': timestamp,
                    'order': order,
                    'buy_price': bot_status['active_trade']['price'],
                    'profit': (current_price - bot_status['active_trade']['price']) * amount
                }
                
                bot_status['trade_history'].append(trade_record)
                bot_status['active_trade'] = None
                print(f"[SELL] Sold {amount:.8f} {coin} at ${current_price:.2f}")

    except Exception as e:
        bot_status['error'] = f"Trade execution error: {str(e)}"

# === المهمة الدورية ===
def trading_job():
    if not bot_status['running']:
        return
        
    bot_status['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("جارٍ التحقق من السوق...")
    signal = predict_signal()
    execute_trade(signal)
    get_balance()

# === جدولة المهام ===
schedule.every().hour.at(":00").do(trading_job)

# === واجهة الويب ===
@app.route('/')
def home():
    return "🟢 البوت يعمل على Render"

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html', 
                         status=bot_status, 
                         symbol=symbol,
                         investment=investment_usdt)

@app.route('/start')
def start_bot():
    bot_status['running'] = True
    bot_status['error'] = None
    return "Bot started"

@app.route('/stop')
def stop_bot():
    bot_status['running'] = False
    return "Bot stopped"

@app.route('/force_buy')
def force_buy():
    if bot_status['active_trade'] is None:
        execute_trade(1)
    return "Force buy executed" if bot_status['active_trade'] else "Cannot execute buy - active trade exists"

@app.route('/force_sell')
def force_sell():
    if bot_status['active_trade'] is not None:
        execute_trade(0)
    return "Force sell executed" if bot_status['active_trade'] is None else "Cannot execute sell - no active trade"

@app.route('/debug')
def debug_info():
    return {
        'status': {
            'running': bot_status['running'],
            'model_loaded': bot_status.get('model_loaded', False),
            'last_error': bot_status.get('error', None)
        },
        'environment': {
            'api_key_set': os.getenv('COINEX_API_KEY') is not None,
            'symbol': symbol,
            'investment': investment_usdt
        }
    }

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# === تشغيل التطبيق ===
if __name__ == '__main__':
    # التحقق الأولي
    get_balance()
    
    if bot_status['model_loaded'] and validate_model():
        print("🟢 البوت يعمل الآن. سيتم التحقق كل ساعة.")
        scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        scheduler_thread.start()
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
    else:
        print("❌ لا يمكن بدء البوت بسبب مشكلة في النموذج أو الاتصال")
