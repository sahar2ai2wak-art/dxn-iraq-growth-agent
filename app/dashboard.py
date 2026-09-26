import json
import os
import sqlite3
from pathlib import Path
import streamlit as st

st.set_page_config(page_title='DXN Iraq Growth Agent', layout='wide')
st.title('DXN Iraq Growth Agent')
password = os.getenv('DASHBOARD_PASSWORD')
if not password:
    st.error('اضبط DASHBOARD_PASSWORD قبل فتح اللوحة.')
    st.stop()
entered = st.text_input('كلمة مرور اللوحة', type='password')
if entered != password:
    st.stop()
path = Path(os.getenv('DATABASE_PATH','data/leads.sqlite3'))
if not path.exists():
    st.info('لا توجد بيانات بعد.')
    st.stop()
with sqlite3.connect(path) as con:
    con.row_factory = sqlite3.Row
    rows = [dict(r) for r in con.execute('SELECT * FROM leads ORDER BY updated_at DESC')]
a,b,c = st.columns(3)
a.metric('إجمالي الليدات',len(rows))
b.metric('المؤهلون',sum(r['status']=='مؤهل' for r in rows))
c.metric('غير المؤهلين',sum(r['status']=='غير مؤهل' for r in rows))
st.dataframe([{k:r[k] for k in ('updated_at','channel','name','phone','source','score','status','sheet_synced')} for r in rows], use_container_width=True)
