import os
import time
import threading
import schedule
from flask import Flask
from app.bot import bot_status, predict_signal, execute_auto_trade

# === تحميل المتغيرات البيئية ===
from dotenv import load_dotenv
load_dotenv()

# === إعداد Flask ===
app = Flask(__name__)

# استيراد المسارات (يجب أن يكون بعد تعريف app)
from app.routes import app as routes_app
app.register_blueprint(routes_app)

# === وظيفة التنبؤ الدوري ===
def run_trading_job():
    if not bot_status['running']:
        return

    print("🔄 جارٍ التحقق من السوق...")
    signal = predict_signal()
    if signal is not None:
        print(f"📈 الإشارة الحالية: {'شراء' if signal == 1 else 'بيع'}")
        execute_auto_trade(signal)
    else:
        print("❌ لم يتم الحصول على إشارة")

# === جدولة المهام ===
schedule.every().hour.at(":00").do(run_trading_job)  # كل ساعة

# === تشغيل الجدولة في الخلفية ===
def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# === البدء التلقائي عند التشغيل ===
if __name__ == '__main__':
    print("🟢 بوت التداول يعمل الآن...")

    # بدء المهمة الزمنية في خيط منفصل
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

    # بدء خادم Flask
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
