import asyncio
import re
import json
from google import genai
from telethon import TelegramClient, events
from metaapi_cloud_sdk import MetaApi

# --- ۱. تنظیمات دسترسی ---
from dotenv import load_dotenv
load_dotenv()
TELEGRAM_API_ID = int(os.getenv('TELEGRAM_API_ID', '0'))
TELEGRAM_API_HASH = os.getenv('TELEGRAM_API_HASH', 'YOUR_TELEGRAM_API_HASH')
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY', 'YOUR_GEMINI_API_KEY')
META_API_TOKEN = os.getenv('META_API_TOKEN', 'YOUR_META_API_TOKEN')
META_ACCOUNT_ID = os.getenv('META_ACCOUNT_ID', 'YOUR_META_ACCOUNT_ID')
CHANNEL_ID = int(os.getenv('CHANNEL_ID', '0'))

RISK_USD = 50.0
RR_RATIO = 6.0
active_ticket = None

ai_client = genai.Client(api_key=GEMINI_API_KEY)
tg_client = TelegramClient('london_bot_session', TELEGRAM_API_ID, TELEGRAM_API_HASH)

# --- ۲. تشخیص و تحلیل هوشمند (بدون فیلتر دستی) ---
async def ai_parse_and_filter(text):
    try:
        # پرامپت رو طوری نوشتم که هوش مصنوعی خودش فیلتر نویز رو انجام بده
        prompt = f"""
        Analyze the following text from a Telegram trading channel.
        
        TASK:
        1. Determine if this is a valid GOLD (XAUUSD) trading signal containing ENTRY and SL.
        2. If it is a valid signal, extract: entry, sl, and side (BUY or SELL) as JSON.
        3. If it is NOT a signal (e.g., chat, general news, analysis without levels, or unrelated noise), respond with exactly: "NOISE".
        
        TEXT TO ANALYZE:
        {text}
        
        RESPONSE FORMAT:
        Return only raw JSON like {{"entry": 2400.5, "sl": 2390, "side": "BUY"}} OR the word "NOISE".
        """

        response = ai_client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=prompt
        )

        output = response.text.strip()

        # اگر هوش مصنوعی بگه نویز هست، بیخیال میشیم
        if "NOISE" in output.upper():
            return None

        # استخراج JSON از پاسخ
        match = re.search(r"\{.*\}", output, re.DOTALL)
        if match:
            return json.loads(match.group(0))

    except Exception as e:
        print(f"⚠️ خطای تحلیل هوش مصنوعی: {e}")
    return None

# --- ۳. اجرای معامله در لندن ---
async def execute_trade(data, is_update=False):
    global active_ticket
    api = MetaApi(META_API_TOKEN)
    try:
        account = await api.metatrader_account_api.get_account(META_ACCOUNT_ID)
        await account.wait_connected()
        connection = account.get_rpc_connection()
        await connection.connect()

        symbol = "XAUUSD"
        entry, sl, side = float(data['entry']), float(data['sl']), data['side'].upper()

        if is_update and active_ticket:
            print(f"🔄 لغو تیکت قبلی برای آپدیت: {active_ticket}")
            await connection.cancel_order(active_ticket)

        distance = abs(entry - sl)
        if distance == 0: return
        lot = max(0.01, min(round(RISK_USD / (distance * 100), 2), 0.50))
        tp = round(entry + (distance * RR_RATIO) if side == "BUY" else entry - (distance * RR_RATIO), 2)

        price_info = await connection.get_symbol_price(symbol)
        market_price = price_info['ask'] if side == "BUY" else price_info['bid']

        if side == "BUY":
            method = connection.create_stop_buy_order if entry > market_price else connection.create_limit_buy_order
        else:
            method = connection.create_stop_sell_order if entry < market_price else connection.create_limit_sell_order

        result = await method(symbol, lot, entry, sl, tp)
        active_ticket = result['orderId']
        print(f"✅ اردر ثبت شد! تیکت: {active_ticket} | لات: {lot} | هدف (1:6): {tp}")

    except Exception as e:
        print(f"❌ خطای متاتریدر: {e}")

# --- ۴. شنونده تلگرام ---
@tg_client.on(events.NewMessage(chats=CHANNEL_ID))
async def handler(event):
    msg = event.raw_text
    print(f"\n📩 پیام جدید دریافت شد. در حال بررسی با Gemini 3.1...")

    # تشخیص هوشمند نویز یا سیگنال
    data = await ai_parse_and_filter(msg)

    if data:
        print(f"🧠 سیگنال تایید شد: {data}")
        await execute_trade(data, "UPDATE" in msg.upper())
    else:
        print("⏭ هوش مصنوعی این پیام را نویز یا غیرسیگنال تشخیص داد.")

async def main():
    print("-----------------------------------------")
    print("🛰 ربات تریدر لندن (نسخه تمام هوشمند Gemini 3.1)")
    print("📍 فیلتر نویز: بر عهده هوش مصنوعی")

    await tg_client.start()

    # اسکن ۱۰ پیام آخر برای پیدا کردن آخرین سیگنال واقعی (بدون توجه به نویزها)
    print("🔍 در حال جستجوی آخرین سیگنال معتبر در کانال...")
    async for message in tg_client.iter_messages(CHANNEL_ID, limit=10):
        if message.text:
            data = await ai_parse_and_filter(message.text)
            if data:
                print(f"✅ آخرین سیگنال واقعی پیدا شد: {message.text[:40]}...")
                await execute_trade(data, "UPDATE" in message.text.upper())
                break

    print("\n📍 وضعیت: ربات آنلاین. آماده پردازش هوشمند...")
    print("-----------------------------------------")
    await tg_client.run_until_disconnected()

if __name__ == '__main__':
    asyncio.run(main())
