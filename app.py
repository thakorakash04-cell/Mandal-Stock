"""Samaan's original web layout, hosted in Streamlit with server-only actions."""
import os
from pathlib import Path
import streamlit as st
import streamlit.components.v1 as components
from store import Store
from media import cached_photo
from controller import handle_event,view_data,is_admin

st.set_page_config(page_title='Samaan · Mandal Stock',page_icon='📦',layout='wide',initial_sidebar_state='collapsed')
# Remove the Streamlit frame; the website owns its sidebar, header and responsive
# scroll surface. No selectors target Streamlit's generated CSS class names.
st.markdown('<style>'+Path(__file__).with_name('style.css').read_text()+'</style>',unsafe_allow_html=True)

def setting(key,default=''):
    try:
        return st.secrets.get(key,os.environ.get(key,default))
    except FileNotFoundError:
        return os.environ.get(key,default)

config={k:setting(k) for k in ('DATABASE_URL','ADMIN_USERNAME','ADMIN_PASSWORD','ADMIN_PASSWORD_HASH','MANDAL_NAME')}
url=config['DATABASE_URL']
local_allowed=str(setting('ALLOW_LOCAL_SQLITE',False)).lower()=='true'

@st.cache_resource
def initialize(database_url):
    database=Store(database_url)
    database.initialize()
    return database

@st.cache_data(ttl=30,max_entries=4,show_spinner=False)
def snapshot(database_url,admin_view):
    return initialize(database_url).snapshot(admin=admin_view)

def load_photo(item_id,version):
    return cached_photo(url,item_id,version)

def seed_photo(result,image):
    if image is not None:
        cached_photo(url,result['id'],result['photo_version'],_uploaded=image)

try:
    if url.startswith('sqlite:///') and not local_allowed:
        raise ValueError('Local database disabled for cloud hosting.')
    db=initialize(url)
except Exception:
    db=None

admin=is_admin(st.session_state)
try:
    data=snapshot(url,admin) if db else {'items':[],'members':[],'holdings':[]}
    payload=view_data(db,data,st.session_state,config)
except Exception:
    payload={'admin':False,'items':[],'members':[],'holdings':[],'history':[],'historyPage':1,'historyHasMore':False,'messages':{},'receipt':None,'mandalName':config.get('MANDAL_NAME') or 'Our mandal','adminConfigured':False,'setupNeeded':True}

workspace=components.declare_component('samaan_workspace',path=str(Path(__file__).with_name('frontend')))
event=workspace(data=payload,response=st.session_state.get('web_response'),key='samaan_workspace',default=None)
response,changed=handle_event(db,event,st.session_state,config,load_photo,seed_photo)
if response is not None:
    st.session_state['web_response']=response
    if changed:
        snapshot.clear()
    st.rerun()
