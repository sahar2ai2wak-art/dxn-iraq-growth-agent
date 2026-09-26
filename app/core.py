import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import httpx
from google.oauth2 import service_account
from googleapiclient.discovery import build
from openai import AsyncOpenAI

DB = Path(os.getenv('DATABASE_PATH', 'data/leads.sqlite3'))
LOCK = Lock()
QUESTIONS = [
    'ما الذي يهمك أكثر؟ 1 بناء مشروع تدريجياً  2 معرفة المنتجات فقط  3 أبحث عن دخل سريع بلا جهد',
    'كم وقتاً تستطيع تخصيصه للتعلم والعمل أسبوعياً؟ 1 أقل من ساعتين  2 من ساعتين إلى خمس  3 أكثر من خمس',
    'إذا واجهت تحدياً في البداية، ماذا تفعل؟ 1 أتعلم وأجرب  2 أحتاج من يوجهني  3 أتوقف فوراً',
    'هل لديك ميزانية اختيارية لشراء منتجات للاستخدام الشخصي بعد الاطلاع على الأسعار؟ 1 نعم، ضمن ميزانية مناسبة  2 أفضل البدء دون شراء  3 لا أستطيع حالياً',
]
POINTS = [{1: 2, 2: 1, 3: 0}, {1: 0, 2: 1, 3: 2}, {1: 2, 2: 1, 3: 0}, {1: 1, 2: 1, 3: 0}]


def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA journal_mode=WAL')
    con.execute('''CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY, channel TEXT NOT NULL, external_id TEXT NOT NULL,
        name TEXT DEFAULT '', phone TEXT DEFAULT '', source TEXT DEFAULT '',
        answers TEXT DEFAULT '[]', score INTEGER DEFAULT 0, status TEXT DEFAULT 'جديد',
        consent INTEGER DEFAULT 0, sheet_synced INTEGER DEFAULT 0,
        updated_at TEXT NOT NULL, UNIQUE(channel, external_id))''')
    con.execute('CREATE TABLE IF NOT EXISTS events (key TEXT PRIMARY KEY, created_at TEXT NOT NULL)')
    return con


def now():
    return datetime.now(timezone.utc).isoformat()


def dedupe(key):
    with LOCK, connect() as con:
        try:
            con.execute('INSERT INTO events VALUES (?,?)', (key, now()))
            return True
        except sqlite3.IntegrityError:
            return False


def upsert(channel, external_id, name='', phone='', source='', consent=False):
    with LOCK, connect() as con:
        con.execute('''INSERT INTO leads(channel,external_id,name,phone,source,consent,updated_at)
            VALUES (?,?,?,?,?,?,?) ON CONFLICT(channel,external_id) DO UPDATE SET
            name=COALESCE(NULLIF(excluded.name,''),leads.name),
            phone=COALESCE(NULLIF(excluded.phone,''),leads.phone),
            source=COALESCE(NULLIF(excluded.source,''),leads.source),
            consent=MAX(leads.consent,excluded.consent),updated_at=excluded.updated_at''',
            (channel, str(external_id), name, phone, source, int(consent), now()))
        return dict(con.execute('SELECT * FROM leads WHERE channel=? AND external_id=?', (channel, str(external_id))).fetchone())


def get(channel, external_id):
    with connect() as con:
        row = con.execute('SELECT * FROM leads WHERE channel=? AND external_id=?', (channel, str(external_id))).fetchone()
        return dict(row) if row else None


def answer(channel, external_id, choice):
    with LOCK, connect() as con:
        row = con.execute('SELECT * FROM leads WHERE channel=? AND external_id=?', (channel, str(external_id))).fetchone()
        if not row:
            return None
        answers = json.loads(row['answers'])
        if len(answers) >= 4:
            return dict(row)
        answers.append(choice)
        score = sum(POINTS[i][v] for i, v in enumerate(answers))
        status = 'مؤهل' if score >= 4 else 'غير مؤهل' if len(answers) == 4 else 'قيد التأهيل'
        con.execute('UPDATE leads SET answers=?,score=?,status=?,sheet_synced=0,updated_at=? WHERE id=?',
                    (json.dumps(answers), score, status, now(), row['id']))
        return dict(con.execute('SELECT * FROM leads WHERE id=?', (row['id'],)).fetchone())


def sheet_sync():
    path, sheet_id = os.getenv('GOOGLE_SERVICE_ACCOUNT_FILE'), os.getenv('GOOGLE_SHEET_ID')
    if not path or not sheet_id:
        return 0
    creds = service_account.Credentials.from_service_account_file(path, scopes=['https://www.googleapis.com/auth/spreadsheets'])
    service = build('sheets', 'v4', credentials=creds, cache_discovery=False)
    tab = os.getenv('GOOGLE_SHEET_TAB', 'Leads')
    with LOCK, connect() as con:
        rows = con.execute('SELECT * FROM leads WHERE sheet_synced=0 AND status IN (\'مؤهل\',\'غير مؤهل\')').fetchall()
        if not rows:
            return 0
        # One row per completed questionnaire; corrections appear as newer rows.
        values = [[str(r['id']), r['updated_at'], r['channel'], r['name'], r['phone'], r['source'],
                   *json.loads(r['answers']), r['score'], r['status']] for r in rows]
        service.spreadsheets().values().append(spreadsheetId=sheet_id, range=f'{tab}!A:K',
            valueInputOption='RAW', insertDataOption='INSERT_ROWS', body={'values': values}).execute()
        con.executemany('UPDATE leads SET sheet_synced=1 WHERE id=?', [(r['id'],) for r in rows])
        return len(rows)


async def ai_reply(message):
    key = os.getenv('OPENAI_API_KEY')
    if not key:
        return 'المشروع يعتمد على التعلم وتقديم المنتجات وبناء فريق بشكل تدريجي. هل تود معرفة خطوات البداية؟'
    client = AsyncOpenAI(api_key=key)
    response = await client.responses.create(model=os.getenv('OPENAI_MODEL', 'gpt-4.1-mini'),
        instructions=('أنت مساعد DXN Iraq Growth Agent. أجب بالعربية البيضاء باختصار. '
                      'اشرح المنتجات باعتبارها أغذية أو منتجات عناية من دون علاج أو وقاية من مرض. '
                      'لا تقدم وعود دخل أو أرقام أرباح، ولا تصف الدخل بأنه مضمون. '
                      'العضوية مجانية والعمل والشراء اختياريان. لا تطلب بيانات حساسة.'),
        input=message[:2000], max_output_tokens=180)
    return response.output_text.strip()


async def whatsapp_send(to, text):
    token, number_id = os.getenv('META_ACCESS_TOKEN'), os.getenv('WHATSAPP_PHONE_NUMBER_ID')
    if not token or not number_id:
        return False
    version = os.getenv('META_GRAPH_VERSION', 'v23.0')
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.post(f'https://graph.facebook.com/{version}/{number_id}/messages',
            headers={'Authorization': f'Bearer {token}'}, json={'messaging_product':'whatsapp',
            'to':to, 'type':'text', 'text':{'body':text}})
        response.raise_for_status()
    return True


async def process_message(channel, external_id, text, name='', phone='', source='message'):
    lead = upsert(channel, external_id, name, phone, source, consent=True)
    if text.strip().lower() in ('توقف', 'stop', 'إلغاء'):
        with LOCK, connect() as con:
            con.execute('UPDATE leads SET consent=0 WHERE id=?', (lead['id'],))
        return 'تم إيقاف المحادثة. يمكنك البدء مجدداً بكتابة ابدأ.'
    if text.strip().lower() in ('ابدأ', 'start', '/start') and lead['status'] in ('مؤهل','غير مؤهل'):
        return 'أهلاً بك. اكتمل الاستبيان. اكتب سؤالك عن المشروع أو المنتجات.'
    answers = json.loads(lead['answers'])
    if len(answers) < 4:
        choice = text.strip().translate(str.maketrans('١٢٣۱۲۳', '123123'))
        if choice not in ('1', '2', '3'):
            return ('أهلاً بك! لنتعرف على اهتماماتك بأربعة أسئلة قصيرة. الإجابة اختيارية، '
                    'وتُحفظ للمتابعة فقط. اكتب 1 أو 2 أو 3.\n\n' if not answers else 'اختر رقماً: 1 أو 2 أو 3.\n\n') + QUESTIONS[len(answers)]
        updated = answer(channel, external_id, int(choice))
        count = len(json.loads(updated['answers']))
        if count < 4:
            return QUESTIONS[count]
        try:
            sheet_sync()
        except Exception:
            pass  # Remains marked for later retry via /admin/sync.
        return ('شكراً لإجاباتك. يمكننا شرح طريقة بناء المشروع ونظام العمولات والمنتجات، '
                'من دون التزام بالشراء. ما الذي تود معرفته أولاً؟')
    return await ai_reply(text)
