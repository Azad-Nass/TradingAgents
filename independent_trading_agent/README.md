# Independent Trading Agent — میز هوشمندی بازار

برنامه‌ای مستقل در کنار TradingAgents برای دو کار:

1. **تحلیل حرفه‌ای نماد انتخابی** (Forex، سهام آمریکا و کانادا، رمزارز، طلا و…)
2. **پویش خودکار بازارها**، کشف فرصت و تحلیل عمیق بهترین نامزدها

خروجی‌ها شامل سابقه‌ی سیگنال‌ها در پایگاه داده‌ی جداگانه، ارزیابی عملکرد سیگنال‌های قبلی، **گزارش روزانه‌ی فارسی (HTML و PDF)** و یک **داشبورد محلی** است.

> فقط تحلیل و شبیه‌سازی انجام می‌شود. هیچ اتصالی به کارگزاری وجود ندارد و هیچ سفارش واقعی ثبت نمی‌شود. خروجی‌ها توصیه‌ی سرمایه‌گذاری یا تضمین سود نیستند.

ترتیب اولویت بازارها در همه‌جا ثابت است: **Forex ← NASDAQ ← NYSE ← Crypto ← TSX ← TSXV**.
این اولویت ترتیب پویش، بودجه‌ی تحلیل و ترتیب گزارش را تعیین می‌کند. اولویت بالاتر هیچ‌وقت آستانه‌ی کیفیت را پایین نمی‌آورد.

---

## ۱. نصب

پیش‌نیاز: Python 3.11 یا بالاتر. همه‌ی دستورها از **پوشه‌ی ریشه‌ی مخزن** اجرا می‌شوند (پوشه‌ای که `independent_trading_agent` داخل آن است).

```powershell
# Windows (PowerShell)
uv venv --python 3.12 .venv            # یا: python -m venv .venv
.venv\Scripts\activate
uv pip install -r independent_trading_agent\requirements.txt
# اختیاری، برای تحلیل عمیق با تیم LLM پروژه‌ی TradingAgents:
uv pip install -e .
```

```bash
# Linux / macOS
python3 -m venv .venv && source .venv/bin/activate
pip install -r independent_trading_agent/requirements.txt
```

تنظیمات:

```powershell
copy independent_trading_agent\.env.example independent_trading_agent\.env
copy independent_trading_agent\config\settings.example.toml independent_trading_agent\config\settings.toml   # اختیاری
python -m independent_trading_agent status
```

## ۲. دستورها

| کار | دستور |
|---|---|
| وضعیت، کلیدهای موجود و آمار پایگاه داده | `python -m independent_trading_agent status` |
| **تحلیل یک یا چند نماد** (حالت ۱) | `python -m independent_trading_agent analyze EURUSD AAPL BTC-USD RY.TO GC=F` |
| تحلیل همراه با تیم LLM پروژه‌ی TradingAgents | `python -m independent_trading_agent analyze EURUSD --deep` (نیازمند `INDEPENDENT_AGENT_TRADINGAGENTS_ENABLED=true`) |
| **پویش بازارها** و تحلیل نامزدها (حالت ۲) | `python -m independent_trading_agent scan --report` |
| فقط پویش، بدون تحلیل عمیق | `python -m independent_trading_agent scan --no-analysis` |
| **اجرای روزانه و گزارش فارسی** | `python -m independent_trading_agent daily` |
| ساخت دوباره‌ی گزارش از پایگاه داده (بدون دریافت داده) | `python -m independent_trading_agent report` |
| ارزیابی سیگنال‌های باز | `python -m independent_trading_agent evaluate` |
| بک‌تست تکنیکال (جدا از عملکرد زنده) | `python -m independent_trading_agent backtest EURUSD AAPL --period 5y --step 5` |
| داشبورد | `python -m independent_trading_agent serve` و سپس http://127.0.0.1:8765 |
| ممیزی عدم تداخل با پروژه‌ی اصلی | `python -m independent_trading_agent audit-isolation` |

نمادها: فارکس به شکل `EURUSD` یا `EUR/USD`، رمزارز به شکل `BTC-USD`، بورس تورنتو `RY.TO`، بورس ونچر `XYZ.V`، طلا `GC=F`.

## ۳. اجرای روزانه چه می‌کند

1. سیگنال‌های بازی را که افقشان تمام شده ارزیابی می‌کند: ورود در اولین قیمت باز پس از صدور، با کسر هزینه و لغزش.
2. بازارهای فعال را به ترتیب اولویت پویش می‌کند. پیش از تحلیل، کیفیت داده را می‌سنجد (تازگی، کمبود کندل، قیمت نامعتبر، کندل ناتمام) و نقدشوندگی را بررسی می‌کند. نمادهای ردشده با ذکر دلیل ثبت می‌شوند.
3. نامزدهایی را که امتیاز جذابیتشان از `min_interest` بالاتر است، به اضافه‌ی فهرست ثابت (`watchlist`)، به تحلیل عمیق چندعاملی می‌فرستد.
4. هر تحلیل این مراحل را طی می‌کند: تحلیلگران (تکنیکال، بنیادی یا اقتصاد کلان، اخبار، احساسات، متخصص بازار)، سپس پژوهشگر صعودی و نزولی، سپس معامله‌گر ارشد (سناریوی فرضی)، سپس مدیر ریسک (رد یا تأیید و اندازه‌ی موقعیت)، و در پایان عامل هوشمندی ارشد که تصمیم نهایی را می‌گیرد.
5. همه‌چیز همراه با شواهد، منبع، زمان داده و تنظیمات در پایگاه داده ثبت می‌شود.
6. گزارش فارسی HTML و PDF در `reports/daily/YYYY/MM/` با نام تاریخ‌دار ساخته می‌شود. گزارش‌های قبلی هرگز بازنویسی نمی‌شوند.

برچسب‌های تصمیم: `STRONG BUY`، `BUY`، `HOLD`، `SELL`، `STRONG SELL`، `NO TRADE`.
در این حالت‌ها نتیجه `NO TRADE` است: داده‌ی نامعتبر یا کهنه، تعارض جدی میان عامل‌ها (۴۵٪ یا بیشتر از وزن شواهد خلاف جهت باشد)، یا رد سناریو توسط مدیر ریسک (مثلاً R:R کمتر از حداقل، نوسان غیرعادی یا نقدشوندگی ناکافی).

## ۴. APIها و کلیدها

| سرویس | کاربرد | کلید | وضعیت پیش‌فرض |
|---|---|---|---|
| Yahoo Finance (کتابخانه‌ی yfinance) | قیمت روزانه‌ی همه‌ی بازارها، خبر، خلاصه‌ی بنیادی، نرخ تبدیل ارز | ندارد | فعال؛ داده‌ی غیررسمی و با تأخیر |
| Google Gemini / OpenRouter / OpenAI | فقط طبقه‌بندی احساسات عنوان خبرها و نوشتن خلاصه‌ی فارسی؛ تصمیم را تغییر نمی‌دهد | `INDEPENDENT_AGENT_GEMINI_API_KEY` و… | اختیاری |
| FRED | نرخ بهره‌ی کوتاه‌مدت و تورم برای Forex (به‌صورت point-in-time) | `INDEPENDENT_AGENT_FRED_API_KEY` (رایگان) | اختیاری |
| TradingAgents (پروژه‌ی کناری) | نظر تیم LLM به‌عنوان یک عامل اضافه | کلیدهای `.env` خود TradingAgents | خاموش |

اگر مدل زبانی در دسترس نباشد، احساسات با روش ساده‌ی واژه‌محور سنجیده می‌شود و این موضوع در گزارش ذکر می‌شود. خلاصه هم با الگوی ثابت نوشته می‌شود.

## ۵. تنظیمات

همه‌ی متغیرها پیشوند `INDEPENDENT_AGENT_` دارند. فهرست کامل در [.env.example](.env.example) و [config/settings.example.toml](config/settings.example.toml) آمده است. مهم‌ترین‌ها:

- `MARKETS`، `UNIVERSE_<MARKET>` و `WATCHLIST`: بازارهای فعال، فهرست نمادها و فهرست ثابت
- `MAX_SYMBOLS_PER_MARKET`، `MAX_TOTAL_SYMBOLS`، `MAX_DATA_REQUESTS`، `MAX_LLM_CALLS`: سقف هزینه و تعداد درخواست
- `TOP_N`، `DEEP_TOP_K`، `MIN_INTEREST`: تعداد فرصت‌ها و آستانه‌ی ورود به تحلیل عمیق
- `TIMEFRAME`، `HORIZON_BARS`، `REPORT_TIMEZONE`، `RUN_TIME`
- `PORTFOLIO_VALUE`، `ACCOUNT_CURRENCY`، `RISK_PER_TRADE_PCT` (پیش‌فرض ۱٪)، `MIN_REWARD_RISK` (پیش‌فرض ۱٫۵)
- هزینه‌های شبیه‌سازی: `FOREX_SPREAD_PIPS`، `STOCK_SPREAD_BPS`، `CRYPTO_SPREAD_BPS`، `COMMISSION_BPS`، `SLIPPAGE_BPS`

## ۵٫۵. آیکون دسکتاپ

```powershell
powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\create_shortcut.ps1          # ساخت آیکون «میز هوشمندی بازار»
powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\create_shortcut.ps1 -Remove  # حذف آیکون
powershell -ExecutionPolicy Bypass -File independent_trading_agent\desktop\stop_dashboard.ps1           # خاموش کردن سرور داشبورد
```

دوبار کلیک روی آیکون، اگر سرور داشبورد روشن نباشد آن را بی‌صدا و بدون پنجره‌ی کنسول روشن می‌کند و داشبورد را در یک پنجره‌ی جدای Edge باز می‌کند. با بستن پنجره، سرور خاموش نمی‌شود؛ تا خاموش کردن سیستم یا اجرای `stop_dashboard.ps1` روشن می‌ماند. آیکون را `desktop/make_icon.py` می‌سازد.

## ۶. زمان‌بندی روزانه (اختیاری؛ به‌طور پیش‌فرض فعال نیست)

ویندوز، روزهای کاری ساعت ۱۸:۳۰:

```powershell
powershell -ExecutionPolicy Bypass -File independent_trading_agent\scheduler\windows_task.ps1 -Time 18:30
# حذف:
powershell -ExecutionPolicy Bypass -File independent_trading_agent\scheduler\windows_task.ps1 -Remove
```

نمونه‌ی cron برای لینوکس و launchd برای مک در [scheduler/examples.md](scheduler/examples.md) آمده است.

## ۷. تست‌ها

```powershell
.venv\Scripts\python.exe -m pytest independent_trading_agent/tests -q
```

همه‌ی تست‌ها با داده‌ی **ساختگی و برچسب‌دار** (`SYNTHETIC TEST DATA`) و بدون اینترنت اجرا می‌شوند. موارد پوشش‌داده‌شده: درستی اندیکاتورها و علّی بودن آن‌ها، تقویم بازارها، کیفیت داده، اندازه‌ی موقعیت فارکس (ارزش پیپ و جفت‌های JPY)، قواعد ارزیابی، نبود look-ahead در بک‌تست، قواعد NO TRADE، پویش با بودجه و اولویت، گزارش RTL، و ایزوله بودن از پروژه‌ی اصلی.

## ۸. محدودیت‌های شناخته‌شده

- داده‌ی Yahoo **غیررسمی و با تأخیر** است. Forex حجم متمرکز ندارد، پس VWAP و تحلیل حجم برای آن ممکن نیست.
- ارقام بنیادی سهام، خلاصه‌ی **فعلی** Yahoo است و point-in-time نیست. به همین دلیل فقط در تحلیل زنده استفاده می‌شود، نه در بک‌تست. مقایسه با همتایان هم پیاده نشده است.
- تقویم تعطیلات قاعده‌محور است. تعطیلی‌های غیرمنتظره را نمی‌شناسد، ولی بررسی کهنگی داده این را جبران می‌کند.
- «اطمینان» تا وقتی دست‌کم ۳۰ سیگنال ارزیابی نشده باشد **کالیبره‌نشده** است و این در گزارش ذکر می‌شود.
- بک‌تست فقط تکنیکال است و روی فهرست امروز نمادها اجرا می‌شود، پس **سوگیری بقا** دارد.
- TSXV به‌طور پیش‌فرض فهرست نماد ندارد. نمادها را خودتان اضافه کنید.
- تقویم اقتصادی (زمان انتشار داده‌های مهم) منبع رایگان معتبری نداشت و پیاده نشده است.

مستندات بیشتر: [docs/AUDIT.md](docs/AUDIT.md) و [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
