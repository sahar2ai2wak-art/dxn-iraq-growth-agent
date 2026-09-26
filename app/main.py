import hashlib
import hmac
import json
import os
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import PlainTextResponse
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from .core import connect, dedupe, process_message, upsert, whatsapp_send, sheet_sync

bot = None


async def telegram_handler(update, context):
    if not update.effective_chat or not update.message or not update.message.text:
        return
    u = update.effective_user
    response = await process_message('telegram', str(update.effective_chat.id), update.message.text,
                                     name=u.full_name if u else '')
    await update.message.reply_text(response)


@asynccontextmanager
async def lifespan(app):
    global bot
    with connect():
        pass
    token = os.getenv('TELEGRAM_BOT_TOKEN')
    if token:
        bot = Application.builder().token(token).updater(None).build()
        bot.add_handler(CommandHandler('start', telegram_handler))
        bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, telegram_handler))
        await bot.initialize()
        await bot.start()
    yield
    if bot:
        await bot.stop()
        await bot.shutdown()


app = FastAPI(title='DXN Iraq Growth Agent', lifespan=lifespan)


@app.get('/health')
def health():
    return {'ok': True}


def verify_meta(body, signature):
    secret = os.getenv('META_APP_SECRET')
    if not secret or not signature or not hmac.compare_digest(
        'sha256=' + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest(), signature):
        raise HTTPException(403, 'Invalid Meta signature')


@app.get('/webhooks/meta')
def meta_challenge(request: Request):
    q = request.query_params
    if q.get('hub.mode') == 'subscribe' and os.getenv('META_VERIFY_TOKEN') and hmac.compare_digest(
        q.get('hub.verify_token', ''), os.getenv('META_VERIFY_TOKEN')):
        return PlainTextResponse(q.get('hub.challenge', ''))
    raise HTTPException(403)


async def retrieve_lead(lead_id):
    token = os.getenv('META_PAGE_ACCESS_TOKEN')
    if not token:
        raise RuntimeError('META_PAGE_ACCESS_TOKEN is required for Lead Ads')
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(f"https://graph.facebook.com/{os.getenv('META_GRAPH_VERSION','v23.0')}/{lead_id}",
                             params={'fields':'id,created_time,field_data,ad_id,form_id', 'access_token':token})
        r.raise_for_status()
        return r.json()


@app.post('/webhooks/meta')
async def meta_webhook(request: Request):
    body = await request.body()
    verify_meta(body, request.headers.get('X-Hub-Signature-256'))
    payload = json.loads(body)
    for entry in payload.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            if change.get('field') == 'leadgen' and value.get('leadgen_id'):
                lead_id = str(value['leadgen_id'])
                try:
                    record = await retrieve_lead(lead_id)
                except (httpx.HTTPError, RuntimeError):
                    raise HTTPException(503, 'Lead retrieval failed; retry webhook')
                fields = {f['name']: ', '.join(map(str, f.get('values', []))) for f in record.get('field_data', [])}
                if dedupe('leadgen:' + lead_id):
                    upsert('meta_form', lead_id, fields.get('full_name', ''), fields.get('phone_number', ''),
                           'lead_ad:' + str(value.get('ad_id', '')))
                # Form submissions are stored. A user-initiated WhatsApp/Telegram chat starts the questions.
        for change in entry.get('changes', []):
            value = change.get('value', {})
            if change.get('field') != 'messages':
                continue
            contacts = {c.get('wa_id'):c.get('profile', {}).get('name','') for c in value.get('contacts', [])}
            for message in value.get('messages', []):
                if message.get('type') != 'text' or not message.get('from'):
                    continue
                sender = message['from']
                if not dedupe('whatsapp:' + str(message.get('id', ''))):
                    continue
                reply = await process_message('whatsapp', sender, message['text'].get('body',''),
                                               contacts.get(sender,''), sender)
                try:
                    await whatsapp_send(sender, reply)
                except httpx.HTTPError:
                    raise HTTPException(503, 'WhatsApp send failed')
    return {'received': True}


@app.post('/webhooks/telegram')
async def telegram_webhook(request: Request):
    secret = os.getenv('TELEGRAM_WEBHOOK_SECRET')
    if not bot or not secret or not hmac.compare_digest(request.headers.get('X-Telegram-Bot-Api-Secret-Token',''), secret):
        raise HTTPException(403)
    data = await request.json()
    update = Update.de_json(data, bot.bot)
    await bot.process_update(update)
    return {'received': True}


@app.post('/admin/sync')
def sync(request: Request):
    token = os.getenv('ADMIN_TOKEN')
    if not token or not hmac.compare_digest(request.headers.get('X-Admin-Token',''),token):
        raise HTTPException(403)
    return {'synced': sheet_sync()}
