import os
import ccxt
import pandas as pd
import time
import schedule
import threading
import numpy as np
from datetime import datetime
from tensorflow.keras.models import load_model
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv

# تحميل المتغيرات البيئية
load_dotenv()

app = Flask(__name__)

# === إعدادات التداول ===
symbol = os.getenv('TRADING_SYMBOL', 'BTC/USDT')
investment_usdt = float(os.getenv('INVESTMENT_AMOUNT', 9))

# === إعدادات API ===
exchange = ccxt.coinex({
    'apiKey': os.getenv('COINEX_API_KEY'),
    'secret': os.getenv('COINEX_API_SECRET'),
    'enableRateLimit': True,
    'options': {
        'defaultType': 'spot',
    }
})

# === تحميل النموذج ===
try:
    model = load_model('yazbek.keras')
    print("✅ تم تحميل النموذج بنجاح")
    bot_status['model_loaded'] = True
except Exception as e:
    print(f"❌ خطأ في تحميل النموذج: {str(e)}")
    bot_status['error'] = f"خطأ في تحميل النموذج: {str(e)}"
    bot_status['model_loaded'] = False
    model = None

# === حالة البوت ===
bot_status = {
    'running': os.getenv('BOT_START_RUNNING', 'true').lower() == 'true',
    'last_check': None,
    'active_trade': None,
    'trade_history': [],
    'balances': {'total': {currency: 0.0 for currency in ['USDT', 'BTC', 'ETH', 'BNB', 'XRP', 'DOT']}},
    'prices': {symbol: {'ask': 0.0, 'bid': 0.0, 'last': 0.0} for symbol in SYMBOLS},
    'open_orders': [],
    'error': None,
    'settings': {
        'max_active_trades': int(os.getenv('MAX_ACTIVE_TRADES', 1)),
        'trade_timeout': int(os.getenv('TRADE_TIMEOUT_HOURS', 24)),
        'stop_loss': float(os.getenv('STOP_LOSS_PERCENT', 0.95)),
        'take_profit': float(os.getenv('TAKE_PROFIT_PERCENT', 1.05))
    },
    'model_loaded': False
}

# === تحديث البيانات في الخلفية ===
def update_data():
    while True:
        try:
            # تحديث الأرصدة
            new_balances = exchange.fetch_balance()
            if new_balances and 'total' in new_balances:
                bot_status['balances']['total'] = {k: float(v) for k, v in new_balances['total'].items() if k in ['USDT', 'BTC', 'ETH', 'BNB', 'XRP', 'DOT']}
            
            # تحديث الأسعار
            for symbol in SYMBOLS:
                ticker = exchange.fetch_ticker(symbol)
                if ticker:
                    bot_status['prices'][symbol] = {
                        'ask': float(ticker.get('ask', 0.0)) if ticker.get('ask') is not None else 0.0,
                        'bid': float(ticker.get('bid', 0.0)) if ticker.get('bid') is not None else 0.0,
                        'last': float(ticker.get('last', 0.0)) if ticker.get('last') is not None else 0.0
                    }
            
            # تحديث الأوامر المفتوحة
            bot_status['open_orders'] = exchange.fetch_open_orders()
            
        except Exception as e:
            bot_status['error'] = f"Error updating data: {str(e)}"
            print(f"Error updating data: {e}")
        
        time.sleep(20)  # تحديث كل 20 ثانية

# بدء تحديث البيانات
data_thread = threading.Thread(target=update_data)
data_thread.daemon = True
data_thread.start()

# === التنبؤ والتداول الآلي ===
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

def trading_job():
    if not bot_status['running']:
        return
        
    bot_status['last_check'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("جارٍ التحقق من السوق...")
    signal = predict_signal()
    execute_auto_trade(signal)

def execute_auto_trade(signal):
    if signal is None:
        return
        
    try:
        current_price = bot_status['prices'][symbol]['last']
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if bot_status['active_trade'] is not None:
            return
            
        if signal == 1:  # شراء
            if bot_status['balances']['total']['USDT'] >= investment_usdt:
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
            if bot_status['active_trade'] is not None:
                coin = symbol.split('/')[0]
                if bot_status['balances']['total'][coin] > 0:
                    amount = bot_status['balances']['total'][coin]
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

# === جدولة المهام ===
schedule.every().hour.at(":00").do(trading_job)

# === واجهة الويب ===
@app.route('/')
def home():
    return render_template('dashboard.html', 
                         status=bot_status, 
                         symbol=symbol,
                         investment=investment_usdt,
                         SYMBOLS=SYMBOLS,
                         prices=bot_status['prices'],
                         open_orders=bot_status['open_orders'],
                         balances=bot_status['balances'])

@app.route('/execute_trade', methods=['POST'])
def execute_manual_trade():
    try:
        symbol = request.form.get('symbol')
        action = request.form.get('action')
        order_type = request.form.get('order_type')
        amount = float(request.form.get('amount'))
        
        if amount <= 0:
            return jsonify({'status': 'error', 'message': 'الكمية يجب أن تكون أكبر من الصفر'})
        
        if order_type == 'market':
            if action == 'buy':
                order = exchange.create_market_buy_order(symbol, amount)
            else:
                order = exchange.create_market_sell_order(symbol, amount)
        else:
            price = float(request.form.get('price'))
            if action == 'buy':
                order = exchange.create_limit_buy_order(symbol, amount, price)
            else:
                order = exchange.create_limit_sell_order(symbol, amount, price)
        
        bot_status['trade_history'].append({
            'time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'symbol': symbol,
            'type': action,
            'amount': amount,
            'price': order.get('price', 0),
            'total': amount * order.get('price', 0),
            'status': 'تم التنفيذ'
        })
        
        return jsonify({'status': 'success', 'message': 'تم تنفيذ الأمر بنجاح'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/cancel_order/<order_id>', methods=['POST'])
def cancel_order(order_id):
    try:
        order_to_cancel = None
        for order in bot_status['open_orders']:
            if order['id'] == order_id:
                order_to_cancel = order
                break
        
        if not order_to_cancel:
            return jsonify({'status': 'error', 'message': 'Order not found'})
        
        exchange.cancel_order(order_id, order_to_cancel['symbol'])
        return jsonify({'status': 'success', 'message': 'تم إلغاء الأمر بنجاح'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})

@app.route('/start')
def start_bot():
    bot_status['running'] = True
    bot_status['error'] = None
    return jsonify({'status': 'success', 'message': 'تم تشغيل البوت'})

@app.route('/stop')
def stop_bot():
    bot_status['running'] = False
    return jsonify({'status': 'success', 'message': 'تم إيقاف البوت'})

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == '__main__':
    # التحقق الأولي
    try:
        exchange.load_markets()
        update_data()  # تحديث البيانات أول مرة
        
        if bot_status['model_loaded']:
            print("🟢 البوت يعمل الآن. سيتم التحقق كل ساعة.")
            scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
            scheduler_thread.start()
            app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
        else:
            print("❌ لا يمكن بدء البوت بسبب مشكلة في النموذج")
    except Exception as e:
        print(f"❌ خطأ في بدء التشغيل: {str(e)}")
