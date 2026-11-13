# Independent Trading Agent — میز هوشمندی بازار

برنامه‌ای مستقل در کنار TradingAgents برای دو کار:

1. **تحلیل حرفه‌ای نماد انتخابی** (Forex، سهام آمریکا و کانادا، رمزارز، طلا و…)
2. **پویش خودکار بازارها**، کشف فرصت و تحلیل عمیق بهترین نامزدها

موتور تحلیل، **تیم چندعاملی TradingAgents** است. FRED (اقتصاد کلان) و Gemini (احساسات خبر) مکمل آن‌اند. کیفیت داده و مدیریت ریسک کنترل نهایی را انجام می‌دهند.

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
| **تحلیل یک یا چند نماد با TradingAgents** (حالت ۱) | `python -m independent_trading_agent analyze XAUUSD EURUSD AAPL` |
| **پویش بازارها** و تحلیل نامزدها (حالت ۲) | `python -m independent_trading_agent scan --report` |
| فقط پویش، بدون TradingAgents (بدون مدل زبانی) | `python -m independent_trading_agent scan --no-analysis` |
| **اجرای روزانه و گزارش فارسی** | `python -m independent_trading_agent daily` |
| ساخت دوباره‌ی گزارش از پایگاه داده (بدون دریافت داده) | `python -m independent_trading_agent report` |
| ارزیابی سیگنال‌های باز | `python -m independent_trading_agent evaluate` |
| بک‌تست قواعد پیش‌پالایش پویشگر (جدا از عملکرد زنده) | `python -m independent_trading_agent backtest EURUSD AAPL --period 5y --step 5` |
| داشبورد | `python -m independent_trading_agent serve` و سپس http://127.0.0.1:8765 |
| ممیزی عدم تداخل با پروژه‌ی اصلی | `python -m independent_trading_agent audit-isolation` |

نمادها: فارکس به شکل `EURUSD` یا `EUR/USD`، رمزارز به شکل `BTC-USD`، بورس تورنتو `RY.TO`، بورس ونچر `XYZ.V`.

**طلا و نقره در بخش فارکس:** با `XAUUSD` و `XAGUSD` (یا دکمه‌ی «تحلیل طلا» در داشبورد). Yahoo برای آن‌ها جفت‌ارز نقدی ندارد، پس داده از قرارداد آتی COMEX (`GC=F` و `SI=F`) گرفته می‌شود و با قیمت نقدی بروکر به اندازه‌ی Basis فرق دارد. پیپ طلا ۰٫۱ دلار و هر لات ۱۰۰ اونس است. عامل کلان طلا بازده واقعی ۱۰ ساله‌ی آمریکاست (FRED: DFII10). خود `GC=F` اگر مستقیم وارد شود، در بازار «سایر» به‌عنوان قرارداد آتی تحلیل می‌شود.

## ۳. اجرای روزانه چه می‌کند

1. سیگنال‌های بازی را که افقشان تمام شده ارزیابی می‌کند: ورود در اولین قیمت باز پس از صدور، با کسر هزینه و لغزش.
2. بازارهای فعال را به ترتیب اولویت پویش می‌کند. پیش از تحلیل، کیفیت داده را می‌سنجد (تازگی، کمبود کندل، قیمت نامعتبر، کندل ناتمام) و نقدشوندگی را بررسی می‌کند. نمادهای ردشده با ذکر دلیل ثبت می‌شوند.
3. اول نمادهای فهرست ثابت شما (`watchlist`) و بعد نامزدهای پویش با امتیاز بالاتر از `min_interest` را برای تحلیل به **TradingAgents** می‌فرستد. سقف این تحلیل‌ها `TRADINGAGENTS_MAX_RUNS` است (پیش‌فرض ۴)، چون هر تحلیل ده‌ها درخواست مدل زبانی می‌فرستد.
4. **مرحله‌ی ۱، تحلیل با TradingAgents:** تحلیلگر بازار، تحلیلگر اخبار (همراه با داده‌ی FRED) و برای سهام تحلیلگر بنیادی (SEC EDGAR)، سپس مناظره‌ی صعودی و نزولی، معامله‌گر، تیم ریسک و مدیر پرتفوی. رتبه‌ی نهایی مدیر پرتفوی تعیین‌کننده‌ی جهت است.
5. **مکمل‌ها:** دیدگاه اقتصاد کلان از FRED (اختلاف نرخ بهره برای فارکس و بازده واقعی برای طلا)، و سنجش احساسات گزارش خبری TradingAgents با Gemini. این دو فقط می‌توانند نتیجه را یک درجه تضعیف کنند (مثلاً «خرید قوی» به «خرید»)، نه اینکه جهتش را عوض کنند.
6. **کنترل‌ها:** کیفیت داده‌ی قیمت و مدیر ریسک (نسبت ریسک به بازده، نوسان، نقدشوندگی، همبستگی، سقف سیگنال باز) می‌توانند معامله را متوقف کنند (`NO TRADE`). حد ضرر و هدف TradingAgents اگر معقول باشند (حد ضرر بین ۰٫۵ تا ۴ ATR) استفاده می‌شوند؛ در غیر این صورت حد ضرر بر اساس ATR محاسبه می‌شود. اگر تریدر TradingAgents قیمت ورود بهتری از بازار پیشنهاد کند (فروش بالاتر یا خرید پایین‌تر، تا فاصله‌ی ۲ ATR)، سناریو **ورود شرطی (Limit)** می‌شود: معامله فقط وقتی انجام‌شده حساب می‌شود که قیمت تا پایان افق به آن برسد؛ در غیر این صورت «پر نشد» ثبت می‌شود و در آمار سود و زیان حساب نمی‌شود.
7. همه‌چیز، از جمله گزارش‌های کامل TradingAgents، همراه با منبع، زمان داده و تنظیمات در پایگاه داده ثبت می‌شود.
8. گزارش فارسی HTML و PDF در `reports/daily/YYYY/MM/` با نام تاریخ‌دار ساخته می‌شود. گزارش‌های قبلی هرگز بازنویسی نمی‌شوند.

برچسب‌های تصمیم و نگاشت رتبه‌ی TradingAgents: `Buy` ← `STRONG BUY`، `Overweight` ← `BUY`، `Hold` ← `HOLD`، `Underweight` ← `SELL`، `Sell` ← `STRONG SELL`.
در این حالت‌ها نتیجه `NO TRADE` است: داده‌ی قیمت نامعتبر یا کهنه، اجرا نشدن یا شکست TradingAgents، پر شدن سقف اجرای TradingAgents، یا رد سناریو توسط مدیر ریسک.

## ۴. APIها و کلیدها

| سرویس | کاربرد | کلید | وضعیت پیش‌فرض |
|---|---|---|---|
| **TradingAgents** (پروژه‌ی کناری) | **موتور تحلیل:** تحلیلگرها، مناظره، معامله‌گر، تیم ریسک و مدیر پرتفوی؛ صورت‌های مالی از SEC EDGAR | کلیدهای `.env` خود TradingAgents (Gemini/OpenRouter، FRED) | فعال |
| FRED | نرخ بهره و تورم برای فارکس و بازده واقعی ۱۰ ساله برای طلا (به‌صورت point-in-time) | `INDEPENDENT_AGENT_FRED_API_KEY` (رایگان) | فعال |
| Google Gemini (و زنجیره‌ی پشتیبان) | سنجش احساسات گزارش خبری TradingAgents، یک درخواست برای هر نماد | `INDEPENDENT_AGENT_GEMINI_API_KEY` و… | فعال |
| Yahoo Finance (کتابخانه‌ی yfinance) | **فقط قیمت روزانه:** کنترل کیفیت، پویش اولیه، مدیر ریسک، ارزیابی سیگنال‌ها و نمودار. خود TradingAgents هم قیمت را از همین‌جا می‌گیرد | ندارد | فعال؛ داده‌ی غیررسمی و با تأخیر |

خبر و خلاصه‌ی بنیادی دیگر مستقیم از Yahoo خوانده نمی‌شود. اخبار را تحلیلگر اخبار TradingAgents جمع می‌کند.

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

- **هزینه و زمان:** هر تحلیل TradingAgents ده‌ها درخواست مدل زبانی می‌فرستد و چند دقیقه طول می‌کشد. با سهمیه‌ی رایگان، چند تحلیل در روز ممکن است.
- خروجی TradingAgents متن مدل زبانی است و ممکن است خطا یا ادعای بی‌پشتوانه داشته باشد. گزارش کامل آن در داشبورد و گزارش روزانه آمده تا قابل بررسی باشد.
- قیمت‌ها (چه در این برنامه و چه در خود TradingAgents) از Yahoo می‌آیند، که **غیررسمی و با تأخیر** است. طلا از قرارداد آتی گرفته می‌شود و با قیمت نقدی فرق دارد.
- تقویم تعطیلات قاعده‌محور است. تعطیلی‌های غیرمنتظره را نمی‌شناسد، ولی بررسی کهنگی داده این را جبران می‌کند.
- «اطمینان» تا وقتی دست‌کم ۳۰ سیگنال ارزیابی نشده باشد **کالیبره‌نشده** است و این در گزارش ذکر می‌شود.
- بک‌تست فقط قواعد تکنیکال پیش‌پالایش پویشگر را می‌سنجد، نه تصمیم‌های TradingAgents را. روی فهرست امروز نمادها اجرا می‌شود، پس **سوگیری بقا** دارد.
- TSXV به‌طور پیش‌فرض فهرست نماد ندارد. نمادها را خودتان اضافه کنید.
- تقویم اقتصادی (زمان انتشار داده‌های مهم) منبع رایگان معتبری نداشت و پیاده نشده است.

مستندات بیشتر: [docs/AUDIT.md](docs/AUDIT.md) و [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
