# DXN Iraq Growth Agent

مشروع Python يستقبل رسائل تيليجرام وواتساب وليدات نماذج Meta Lead Ads، ويطرح أربعة أسئلة، ويحفظ نتائجها محلياً وفي Google Sheets، ويعرض لوحة Streamlit. واجهة OpenAI API تجيب عن الأسئلة الحرة بعد الاستبيان. النصوص التسويقية في `content/` للمراجعة البشرية قبل النشر.

## التشغيل

يتطلب Python 3.11+ وخادماً عاماً HTTPS لاستقبال Webhooks. من مجلد المشروع:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

املأ `.env` بقيمك. حمّل المتغيرات قبل التشغيل (`set -a; source .env; set +a` على Linux/macOS، وتأكد أن قيم الملف لا تحتوي صياغة shell غير آمنة). شغّل العمليتين من **المجلد نفسه** مع قرص دائم مشترك لقاعدة SQLite:

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
streamlit run app/dashboard.py --server.port 8501
```

احمِ لوحة Streamlit على مستوى الشبكة أو بوابة دخول HTTPS أيضاً؛ كلمة المرور البسيطة في التطبيق مناسبة لبداية داخلية وليست نظام حسابات متعدد المستخدمين. لا ترفع `.env` أو ملف حساب Google الخدمي إلى المستودع.

## Google Sheets

1. أنشئ مشروع Google Cloud وفعّل Google Sheets API، ثم أنشئ Service Account ونزّل JSON إلى `credentials/service-account.json`.
2. أنشئ جدول Google Sheets بورقة اسمها `Leads`، وشاركه مع بريد الـService Account بصلاحية محرر.
3. ضع معرف الجدول في `GOOGLE_SHEET_ID`. الأعمدة A:K هي: ID، وقت التحديث، القناة، الاسم، الهاتف، المصدر، إجابة 1–4، النقاط، التصنيف. يمكن كتابة العناوين يدوياً في الصف الأول.
4. النتائج المكتملة تضاف تلقائياً. عند تعثر Google تبقى معلّمة للمزامنة؛ أعد المحاولة بـ`POST /admin/sync` وترويسة `X-Admin-Token`. قد تحدث صفوف مكررة إذا نجحت الإضافة وفشل الرد؛ اعتمد عمود ID ووقت التحديث للمراجعة.

## تيليجرام

1. أنشئ بوتاً عبر BotFather وضع الرمز في `TELEGRAM_BOT_TOKEN`، وأنشئ قيمة سرية عشوائية لـ`TELEGRAM_WEBHOOK_SECRET`.
2. بعد نشر الخادم على HTTPS سجل عنوان `https://YOUR_DOMAIN/webhooks/telegram` باستخدام Bot API `setWebhook` مع `secret_token` المطابق؛ مثال (استبدل القيم محلياً ولا تنشر الرمز):

```bash
curl -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook" \
  -d "url=${PUBLIC_BASE_URL}/webhooks/telegram" \
  -d "secret_token=${TELEGRAM_WEBHOOK_SECRET}"
```

3. ضع رابط `https://t.me/YOUR_BOT?start=ad1` في الإعلان ليبدأ الشخص المحادثة بنفسه. يستخدم الكود `python-telegram-bot` ضمن دورة حياة FastAPI.

## Meta Lead Ads (فيسبوك وإنستغرام)

1. أنشئ Meta App ووصله بصفحتك وإعلان نموذج فوري Lead Ads، واضبط الصلاحيات والوصول للّيدات في Leads Access Manager وفق إعدادات حسابك.
2. ضع App Secret في `META_APP_SECRET`، وقيمة تحقق تختارها في `META_VERIFY_TOKEN`، ورمز وصول الصفحة المناسب لقراءة الليدات في `META_PAGE_ACCESS_TOKEN`.
3. في إعدادات Webhooks للتطبيق، اختر كائن **Page** واشترك في حقل **leadgen**. Callback URL هو `https://YOUR_DOMAIN/webhooks/meta`، وVerify Token هو نفس القيمة في `.env`. اشترك بالصفحة المطلوبة واختبر عبر أدوات Meta.
4. حدث `META_GRAPH_VERSION` إلى إصدار Graph API المدعوم في حسابك. Webhook يرسل `leadgen_id` فقط، فيسترجع الخادم التفاصيل ثم يحفظ الاسم والهاتف والمصدر. **تسجيل النموذج لا يرسل أسئلة واتساب تلقائياً**: أضف في رسالة الشكر رابط البوت أو زر بدء محادثة واتساب، أو استخدم قالب رسالة معتمد وإذن تواصل ملائم إذا رغبت بالتواصل الاستباقي لاحقاً.

## WhatsApp Cloud API

1. جهز WhatsApp Business Platform ورقم الهاتف، وخذ `WHATSAPP_PHONE_NUMBER_ID` ورمز وصول مناسباً في `META_ACCESS_TOKEN`.
2. اشترك في Webhooks لكائن **WhatsApp Business Account** وحقل **messages** على عنوان `/webhooks/meta` نفسه، مع App Secret وVerify Token. اربط رقمك أو WABA بالتطبيق بحسب إعدادات Meta.
3. اجعل الإعلان من نوع Click to WhatsApp أو ضع رابط بدء محادثة في صفحة الشكر. عندما يرسل الشخص رسالة نصية، يطرح البوت الأسئلة. الردود النصية الحرة هنا للمحادثات التي بدأها المستخدم ضمن نافذة خدمة العملاء؛ خارجها يلزم قالب معتمد وسياسة موافقة مناسبة. رسائل الحالة ووسائط الصور تُتجاهل في هذا الإصدار.

## التأهيل والخصوصية

الإجابات 1 أو 2 أو 3. النقاط: الاهتمام بالمشروع (0–2)، الوقت المتاح (0–2)، الاستعداد للتعلم (0–2)، والميزانية الاختيارية (0–1). `مؤهل` تعني 4 نقاط أو أكثر، لكنها **إشارة للمتابعة وليست حكماً على الشخص**. الشراء ليس شرطاً للتحدث أو التعلم؛ عدم توفر ميزانية لا يستبعد الشخص وحده. لا تطلب تفاصيل الدخل أو معلومات مالية حساسة. `توقف` يوقف الموافقة للمحادثة؛ احذف السجلات بطلب صاحبها وفق إجراءاتك المحلية. ضع إشعار خصوصية واضحاً في النموذج، واضبط الوصول للجدول والقاعدة.

لا ينشر التطبيق تلقائياً إلى فيسبوك أو إنستغرام أو تيك توك. راجع المحتوى وسياسات الإعلان وخطة DXN الرسمية قبل النشر. لا تستخدم وعود دخل أو ادعاءات علاجية.

## الاختبار

```bash
pytest -q
```

لا توجد مفاتيح حقيقية ضمن المشروع؛ الربط الحي يحتاج بيانات Meta وTelegram وGoogle وOpenAI الخاصة بك وخادماً عاماً.
