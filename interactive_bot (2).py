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


def build_report(config) -> str:
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"📊 *تحديث أسعار العملات*\n🕐 {now}\n"]

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
            f"*{info['label']}*\n"
            f"السعر: `${price:.6f}` {arrow} {change:.2f}%\n"
            f"قيمة {amount:,} {info['label']}: `${value:,.2f}`\n"
        )

    return "\n".join(lines)


# ================== الجدولة (الإرسال الدوري) ==================
async def scheduled_job(context: ContextTypes.DEFAULT_TYPE):
    config = load_config()
    text = build_report(config)
    await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")


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
            "`coingecko_id اسم_مختصر الكمية`\n\n"
            "مثال:\n`billions-network BILL 1350`\n\n"
            "(الـ coingecko_id تلاقيه في رابط العملة على coingecko.com)",
            parse_mode="Markdown",
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

    elif query.data == "send_now":
        await query.message.reply_text("جاري الإرسال...")
        config = load_config()
        text = build_report(config)
        await context.bot.send_message(chat_id=CHANNEL_ID, text=text, parse_mode="Markdown")
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

    print("البوت شغال... اضغط Ctrl+C للإيقاف")
    app.run_polling()


if __name__ == "__main__":
    main()
