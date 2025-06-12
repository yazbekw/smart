from flask import Flask, render_template, request, jsonify
from app.bot import bot_status, execute_auto_trade, predict_signal

app = Flask(__name__)

# === الصفحة الرئيسية ===
@app.route('/')
def home():
    return render_template('dashboard.html', status=bot_status)

# === تشغيل التنبؤ يدويًا ===
@app.route('/predict')
def predict():
    signal = predict_signal()
    return jsonify({
        'signal': signal,
        'message': 'BUY' if signal == 1 else 'SELL' if signal == 0 else 'No prediction'
    })

# === بدء البوت ===
@app.route('/start')
def start_bot():
    bot_status['running'] = True
    bot_status['error'] = None
    return jsonify({'status': 'success', 'message': 'تم تشغيل البوت'})

# === إيقاف البوت ===
@app.route('/stop')
def stop_bot():
    bot_status['running'] = False
    return jsonify({'status': 'success', 'message': 'تم إيقاف البوت'})

# === تنفيذ أمر يدوي (شراء أو بيع) ===
@app.route('/manual-trade', methods=['POST'])
def manual_trade():
    try:
        data = request.get_json()
        action = data.get('action')  # buy or sell
        amount = float(data.get('amount'))

        if amount <= 0:
            return jsonify({'status': 'error', 'message': 'الكمية يجب أن تكون أكبر من الصفر'})

        current_price = exchange.fetch_ticker(TRADING_SYMBOL)['last']

        if action == 'buy':
            order = exchange.create_market_buy_order(TRADING_SYMBOL, amount)
        elif action == 'sell':
            order = exchange.create_market_sell_order(TRADING_SYMBOL, amount)
        else:
            return jsonify({'status': 'error', 'message': 'الإجراء غير معروف'})

        trade_record = {
            'type': action.upper(),
            'amount': amount,
            'price': current_price,
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            'order': order
        }

        if action == 'buy':
            bot_status['active_trade'] = trade_record
        else:
            bot_status['active_trade'] = None

        bot_status['trade_history'].append(trade_record)

        return jsonify({'status': 'success', 'message': f'تم تنفيذ الأمر: {action.upper()} {amount} BTC'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)})
