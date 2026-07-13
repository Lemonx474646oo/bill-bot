# -*- coding: utf-8 -*-
"""
بوت تليجرام تفاعلي لمتابعة أسعار العملات
=========================================
- بيبعت تحديث دوري لسعر عملة (أو أكتر) في القناة
- بيحسب قيمة كمية معينة من العملة (مثلاً 1350 عملة)
- بيديك أزرار تضيف بيها عملة جديدة أو تظبط مدة التنبيه
- بيحفظ الإعدادات في ملف config.json عشان متضيعش

المكتبة المطلوبة: python-telegram-bot (الإصدار 21+)
تثبيت: pip install python-telegram-bot
"""

import json
import os
from datetime import datetime

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ================== إعدادات ثابتة - عدّل دول ==================
BOT_TOKEN = "8843754239:AAEjs_OCSoSNfVOUUrUJ6zQfUAeLiwDm_m0"
CHANNEL_ID = "@N_F_4_G"
CONFIG_FILE = "config.json"

# الإعدادات الافتراضية أول مرة يشتغل فيها البوت
DEFAULT_CONFIG = {
    "interval_minutes": 60,
    "coins": {
        # مفتاح: coingecko id | value: {اسم للعرض, الكمية اللي هنحسب قيمتها}
        "billions-network": {"label": "BILL", "amount": 1350}
    },
}

# ================== إدارة الإعدادات ==================
def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return DEFAULT_CONFIG.copy()


def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


# ================== جلب الأسعار ==================
def get_news(label: str, max_items: int = 5):
    """
    بيجيب آخر أخبار الكريبتو العامة، وبيحاول يفلتر الأخبار اللي بتذكر اسم العملة.
    لو مفيش أخبار خاصة بالعملة، بيرجع أهم الأخبار العامة في السوق بدلها.
    """
    url = "https://min-api.cryptocompare.com/data/v2/news/?lang=EN"
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json().get("Data", [])

    label_lower = label.lower()
    specific = [
        item for item in data
        if label_lower in item.get("title", "").lower()
        or label_lower in item.get("body", "").lower()
    ]

    chosen = specific if specific else data
    chosen = chosen[:max_items]

    return [
        {
            "title": item.get("title", ""),
            "url": item.get("url", ""),
            "source": item.get("source", ""),
        }
        for item in chosen
    ], bool(specific)


def build_news_report(config) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📰 آخر الأخبار\n🕐 {now}\n"]

    seen_labels = set()
    for coin_id, info in config["coins"].items():
        label = info["label"]
        if label in seen_labels:
            continue
        seen_labels.add(label)

        try:
            news_items, is_specific = get_news(label)
        except Exception as e:
            lines.append(f"⚠️ تعذر جلب أخبار {label}: {e}")
            continue

        header = (
            f"أخبار خاصة بـ {label}:" if is_specific
            else f"مفيش أخبار خاصة بـ {label} حاليًا، دي أهم أخبار السوق العام:"
        )
        lines.append(header)

        if not news_items:
            lines.append("لا توجد أخبار متاحة حاليًا.\n")
            continue

        for item in news_items:
            lines.append(f"- {item['title']} ({item['source']})\n  {item['url']}")
        lines.append("")

    return "\n".join(lines)


def get_price(coingecko_id: str):
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={coingecko_id}&vs_currencies=usd&include_24hr_change=true"
    )
    r = requests.get(url, timeout=15)
    r.raise_for_status()
    data = r.json()
    if coingecko_id not in data:
        return None
    return {
        "price": data[coingecko_id]["usd"],
        "change_24h": data[coingecko_id].get("usd_24h_change", 0),
    }


def get_stats(coingecko_id: str):
    """
    بيرجع نسبة التغيير خلال يوم / أسبوع / شهر باستخدام بيانات آخر 30 يوم
    """
    url = (
        f"https://api.coingecko.com/api/v3/coins/{coingecko_id}/market_chart"
        "?vs_currency=usd&days=30&interval=daily"
    )
    r = requests.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    prices = data.get("prices", [])
    if not prices:
        return None

    current_price = prices[-1][1]

    def price_before(days_ago):
        idx = max(0, len(prices) - 1 - days_ago)
        return prices[idx][1]

    price_1d = price_before(1)
    price_7d = price_before(7)
    price_30d = price_before(30)

    def pct_change(old, new):
        if old == 0:
            return 0
        return ((new - old) / old) * 100

    return {
        "current_price": current_price,
        "change_1d": pct_change(price_1d, current_price),
        "change_7d": pct_change(price_7d, current_price),
        "change_30d": pct_change(price_30d, current_price),
    }


def build_stats_report(config) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📈 إحصائيات الأداء\n🕐 {now}\n"]

    for coin_id, info in config["coins"].items():
        stats = get_stats(coin_id)
        if not stats:
            lines.append(f"⚠️ تعذر جلب إحصائيات {info['label']}")
            continue

        def arrow(v):
            return "🟢⬆️" if v >= 0 else "🔴⬇️"

        lines.append(
            f"{info['label']} — السعر الحالي: ${stats['current_price']:.6f}\n"
            f"يومي: {arrow(stats['change_1d'])} {stats['change_1d']:.2f}%\n"
            f"أسبوعي: {arrow(stats['change_7d'])} {stats['change_7d']:.2f}%\n"
            f"شهري: {arrow(stats['change_30d'])} {stats['change_30d']:.2f}%\n"
        )

    return "\n".join(lines)


def build_report(config) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 تحديث أسعار العملات\n🕐 {now}\n"]

    for coin_id, info in config["coins"].items():
        data = get_price(coin_id)
        if not data:
            lines.append(f"⚠️ تعذر جلب سعر {info['label']}")
            continue

        price = data["price"]
        change = data["change_24h"]
        arrow = "🟢⬆️" if change >= 0 else "🔴⬇️"
        amount = info.get("amount", 0)
        value = price * amount

        lines.append(
            f"{info['label']}\n"
            f"السعر: ${price:.6f} {arrow} {change:.2f}%\n"
            f"قيمة {amount:,} {info['label']}: ${value:,.2f}\n"
        )

    return "\n".join(lines)


# ================== الجدولة (الإرسال الدوري) ==================
async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    text = build_report(config)
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text)


async def daily_news_job(context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    try:
        news_text = build_news_report(config)
        for i in range(0, len(news_text), 3500):
            await context.bot.send_message(chat_id=CHANNEL_ID, text=news_text[i:i + 3500])
    except Exception as e:
        print(f"تحذير: فشل جلب الأخبار اليومية: {e}")


def reschedule(app: Application, minutes: int):
    # إلغاء أي job قديم قبل ما نضيف الجديد
    for job in app.job_queue.get_jobs_by_name("price_update"):
        job.schedule_removal()
    app.job_queue.run_repeating(
        scheduled_job, interval=minutes * 60, first=5, name="price_update"
    )


# ================== قائمة الأزرار الرئيسية ==================
def main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة عملة جديدة", callback_data="add_coin")],
        [InlineKeyboardButton("⏱ تغيير مدة التنبيه", callback_data="set_interval")],
        [InlineKeyboardButton("📋 عرض الإعدادات الحالية", callback_data="show_config")],
        [InlineKeyboardButton("🚀 إرسال تحديث الآن", callback_data="send_now")],
        [InlineKeyboardButton("📈 إحصائيات يومي/أسبوعي/شهري", callback_data="show_stats")],
        [InlineKeyboardButton("📰 آخر الأخبار", callback_data="show_news")],
    ]
    return InlineKeyboardMarkup(keyboard)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "أهلاً! اختار من الأزرار اللي تحت:", reply_markup=main_menu()
    )


# ================== التعامل مع ضغط الأزرار ==================
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    try:
        await query.answer()
    except Exception as e:
        print(f"تحذير: فشل query.answer() بسبب: {e} - هنكمل عادي")

    if query.data == "add_coin":
        context.user_data["awaiting"] = "add_coin"
        await query.message.reply_text(
            "ابعتلي بيانات العملة بالشكل ده في رسالة واحدة:\n\n"
            "coingecko_id اسم_مختصر الكمية\n\n"
            "مثال:\nbillions-network BILL 1350\n\n"
            "(الـ coingecko_id تلاقيه في رابط العملة على coingecko.com)"
        )

    elif query.data == "set_interval":
        context.user_data["awaiting"] = "set_interval"
        await query.message.reply_text("ابعتلي عدد الدقايق بين كل تحديث والتاني (مثلاً 10):")

    elif query.data == "show_config":
        config = load_config()
        coins_text = "\n".join(
            f"- {info['label']} ({cid}) — الكمية: {info['amount']:,}"
            for cid, info in config["coins"].items()
        )
        text = (
            f"⏱ مدة التنبيه: كل {config['interval_minutes']} دقيقة\n\n"
            f"العملات المتابَعة:\n{coins_text}"
        )
        await query.message.reply_text(text)

    elif query.data == "show_stats":
        await query.message.reply_text("بيحسب الإحصائيات دلوقتي... ثواني")
        config = load_config()
        text = build_stats_report(config)
        await query.message.reply_text(text)

    elif query.data == "show_news":
        await query.message.reply_text("بيجيب آخر الأخبار دلوقتي... ثواني")
        config = load_config()
        text = build_news_report(config)
        # تليجرام بيرفض الرسائل الأطول من 4096 حرف، فهنقسمها لو طويلة
        for i in range(0, len(text), 3500):
            await query.message.reply_text(text[i:i + 3500])

    elif query.data == "send_now":
        await query.message.reply_text("جاري الإرسال...")
        config = load_config()
        text = build_report(config)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text)
        await query.message.reply_text("تم الإرسال للقناة ✅")


# ================== استقبال الرسائل بعد الضغط على زرار ==================
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")

    if awaiting == "add_coin":
        parts = update.message.text.strip().split()
        if len(parts) != 3:
            await update.message.reply_text(
                "الصيغة غلط. ابعت بالشكل: coingecko_id اسم_مختصر الكمية\n"
                "مثال: billions-network BILL 1350"
            )
            return
        coin_id, label, amount_str = parts
        try:
            amount = float(amount_str)
        except ValueError:
            await update.message.reply_text("الكمية لازم تكون رقم.")
            return

        # تأكيد إن العملة موجودة فعلاً على CoinGecko
        test = get_price(coin_id)
        if not test:
            await update.message.reply_text(
                f"مش لاقي عملة بالـ id ده ({coin_id}) على CoinGecko. تأكد من الـ id وجرب تاني."
            )
            return

        config = load_config()
        config["coins"][coin_id] = {"label": label, "amount": amount}
        save_config(config)
        context.user_data["awaiting"] = None
        await update.message.reply_text(f"تمت إضافة {label} ✅", reply_markup=main_menu())

    elif awaiting == "set_interval":
        try:
            minutes = int(update.message.text.strip())
            if minutes < 1:
                raise ValueError
        except ValueError:
            await update.message.reply_text("ابعت رقم صحيح أكبر من صفر (بالدقايق).")
            return

        config = load_config()
        config["interval_minutes"] = minutes
        save_config(config)
        reschedule(context.application, minutes)
        context.user_data["awaiting"] = None
        await update.message.reply_text(
            f"تم ضبط التنبيه كل {minutes} دقيقة ✅", reply_markup=main_menu()
        )

    else:
        await update.message.reply_text("استخدم /start عشان تشوف الأزرار.")


# ================== تشغيل البوت ==================
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    print(f"حصل خطأ: {context.error}")


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .connect_timeout(30)
        .read_timeout(30)
        .write_timeout(30)
        .pool_timeout(30)
        .build()
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    app.add_error_handler(error_handler)

    config = load_config()
    reschedule(app, config["interval_minutes"])

    # إرسال الأخبار مرة واحدة يوميًا (كل 24 ساعة من وقت التشغيل)
    app.job_queue.run_repeating(
        daily_news_job, interval=24 * 60 * 60, first=60, name="daily_news"
    )

    print("البوت شغال... اضغط Ctrl+C للإيقاف")
    app.run_polling()


if __name__ == "__main__":
    main()
