import os, time, uuid, io, html
from datetime import datetime
from zoneinfo import ZoneInfo
from pathlib import Path
import streamlit as st
from PIL import Image, ImageOps
from store import Store, holding_message, return_message, whatsapp_link
from media import compress_photo, cached_photo

st.set_page_config(page_title='Samaan · Mandal Stock',page_icon='📦',layout='wide')
st.markdown('<style>'+Path(__file__).with_name('style.css').read_text()+'</style>',unsafe_allow_html=True)
def setting(key,default=''):
    try:return st.secrets.get(key,os.environ.get(key,default))
    except FileNotFoundError:return os.environ.get(key,default)

def authorized():
    if not st.session_state.get('admin_ok'):return False
    if time.time()-st.session_state.get('last_admin',0)>1800 or time.time()-st.session_state.get('admin_started',0)>28800:
        st.session_state.admin_ok=False;return False
    st.session_state.last_admin=time.time();return True

def require_admin():
    if not authorized():raise PermissionError('Please sign in as admin.')
    return True

def ist(value):
    try:return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p IST')
    except ValueError:return value

url=setting('DATABASE_URL')
local_allowed=setting('ALLOW_LOCAL_SQLITE',False) is True or str(setting('ALLOW_LOCAL_SQLITE')).lower()=='true'
if url.startswith('sqlite:///') and not local_allowed:
    st.error('SQLite is for local testing only. Configure a durable PostgreSQL DATABASE_URL in Streamlit Secrets.');st.stop()

@st.cache_resource
def initialize(database_url):
    database=Store(database_url);database.initialize();return database
try:db=initialize(url)
except Exception:
    st.title('Samaan · Mandal Stock')
    st.info('One-time setup is needed: add DATABASE_URL, ADMIN_USERNAME and ADMIN_PASSWORD_HASH in Streamlit Secrets. See the repository README for the exact setup.');st.stop()

admin=authorized()
# Separate cache entries prevent admin phone numbers from reaching public sessions.
@st.cache_data(ttl=30,max_entries=4,show_spinner=False)
def snapshot(database_url,admin_view):return db.snapshot(admin=admin_view)

def refresh():snapshot.clear();st.rerun()
def notify(message):st.session_state.notice=message;refresh()
def share_block(message,number='',key='message'):
    st.code(message,language=None,wrap_lines=True)
    st.caption('Use the copy icon above, then paste into WhatsApp. Sending is always your choice.')
    if admin and number:st.link_button('Open in WhatsApp',whatsapp_link(number,message),icon=':material/chat:')

def compressed_photo(upload):
    return compress_photo(upload.getvalue()) if upload is not None else None

def seed_photo(result,image):
    if image is not None:cached_photo(url,result['id'],result['photo_version'],_uploaded=image)

@st.dialog('Change item photo')
def replace_photo_dialog(item_id):
    require_admin()
    with st.form('replace_photo'):
        image=st.file_uploader('New item photo',type=['jpg','jpeg','png','webp'])
        st.caption('Automatically resized to 720 px or smaller and under 60 KB.')
        if st.form_submit_button('Save photo',type='primary',use_container_width=True):
            try:
                payload=compressed_photo(image)
                result=db.replace_photo(item_id,payload,admin=require_admin())
                seed_photo(result,payload);notify('Photo updated. Other cached photos are kept.')
            except (ValueError,PermissionError) as e:st.error(str(e))
            except Exception:st.error('Could not update this photo. Please try another image.')

@st.dialog('Add an item')
def add_item_dialog():
    require_admin()
    with st.form('add_item'):
        name=st.text_input('Item name',max_chars=120,placeholder='e.g. Steel dinner plates')
        category=st.selectbox('Category',['General','Utensils','Furniture','Decorations','Sound & lights'])
        qty=st.number_input('Quantity we have',min_value=1,max_value=100000,step=1)
        image=st.file_uploader('Item photo (optional)',type=['jpg','jpeg','png','webp'])
        st.caption('Photos are automatically reduced to 720 px or smaller and under 60 KB.')
        note=st.text_area('Storage location / notes',max_chars=500)
        if st.form_submit_button('Add to inventory',type='primary',use_container_width=True):
            try:
                payload=compressed_photo(image)
                result=db.add_item(name,category,note,int(qty),payload,admin=require_admin())
                seed_photo(result,payload);notify('Item added to the collection.')
            except (ValueError,PermissionError,Image.DecompressionBombError):st.error('Please check the name, quantity and photo. Photo must be a supported image under 10 MB.')
            except Exception:st.error('Could not save the item. Please try again.')

@st.dialog('Record handover / return')
def transaction_dialog(item_id,kind='issue',member_id=None):
    require_admin();fresh=db.snapshot(admin=True)
    item=next(i for i in fresh['items'] if i['id']==item_id)
    st.markdown(f'### {html.escape(item["name"])}')
    eligible=[m for m in fresh['members'] if m['active']] if kind=='issue' else [m for m in fresh['members'] if any(h['member_id']==m['id'] and h['item_id']==item_id for h in fresh['holdings'])]
    if not eligible:st.info('Add a member in Admin first.' if kind=='issue' else 'No outstanding holdings for this item.');return
    selected=st.selectbox('Tag the member',eligible,index=next((n for n,m in enumerate(eligible) if m['id']==member_id),0),format_func=lambda m:m['name'])
    held=next((int(h['quantity']) for h in fresh['holdings'] if h['item_id']==item_id and h['member_id']==selected['id']),0)
    max_qty=int(item['available']) if kind=='issue' else held
    if max_qty<1:st.info('No quantity available for this action.');return
    st.caption(f'{max_qty} pieces '+('available' if kind=='issue' else 'currently held'))
    operation_key=f'op:{item_id}:{selected["id"]}:{kind}'
    if operation_key not in st.session_state:st.session_state[operation_key]=str(uuid.uuid4())
    with st.form('record_transaction'):
        qty=st.number_input('Quantity handed over' if kind=='issue' else 'Quantity returned',min_value=1,max_value=max_qty,step=1)
        note=st.text_area('Note / event / condition',max_chars=500)
        if st.form_submit_button('Confirm handover' if kind=='issue' else 'Confirm return',type='primary',use_container_width=True):
            try:
                db.record(item_id,selected['id'],kind,int(qty),note,st.session_state[operation_key],admin=require_admin())
                if kind=='return':
                    st.session_state.return_receipt={'member_id':selected['id'],'item_id':item_id,'quantity':int(qty),'note':note,'when':datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p IST')}
                del st.session_state[operation_key];notify('Handover recorded.' if kind=='issue' else 'Return recorded. Confirmation message is ready below.')
            except (ValueError,PermissionError) as e:st.error(str(e))
            except Exception:st.error('Could not confirm the transaction. Refresh to check the register before retrying.')

@st.dialog('Member details')
def member_dialog(member=None):
    require_admin()
    with st.form('member_details'):
        name=st.text_input('Member name',value=member['name'] if member else '',max_chars=80)
        number=st.text_input('WhatsApp number',value=member['whatsapp'] if member else '',placeholder='+91 9876543210',max_chars=25)
        active=st.checkbox('Active member',value=bool(member['active']) if member else True)
        st.caption('10-digit Indian numbers get +91 automatically. Numbers are visible only to admin.')
        if st.form_submit_button('Save member',type='primary',use_container_width=True):
            try:db.save_member(name,number,member['id'] if member else None,active,admin=require_admin());notify('Member saved.')
            except (ValueError,PermissionError) as e:st.error(str(e))
            except Exception:st.error('Could not save member.')

with st.sidebar:
    st.markdown('<div class="brand">📦 Samaan</div><div class="brand-sub">THE MANDAL REGISTER</div>',unsafe_allow_html=True)
    st.caption('OUR SHARED SPACE')
    pages=['Inventory','Current holders','Share my list','History','Admin']
    page=st.radio('Navigation',pages,label_visibility='collapsed')
    st.divider();st.markdown('### Shared with care.')
    st.caption('A little organisation. More time together.')
    st.caption('View without login · Admin records changes')
    if admin:
        st.success('Admin signed in')
        if st.button('Sign out',use_container_width=True):
            st.session_state.admin_ok=False;snapshot.clear();st.rerun()

st.caption(f'{setting("MANDAL_NAME","Our Mandal")} / {page}')
a,b=st.columns([5,1])
with a:
    st.markdown('<div class="eyebrow">A PLACE FOR EVERYTHING</div>',unsafe_allow_html=True)
    st.title({'Inventory':'Our inventory.','Current holders':'In good hands.','Share my list':'With me.','History':'Every handover, recorded.','Admin':'A little housekeeping.'}[page])
    st.caption({'Inventory':'Know what we have. Know where it is.','Current holders':'See who has what, and bring things back into circulation.','Share my list':'Choose your name and copy your current item list.','History':'A clear trail of items taken and returned.','Admin':'Only the admin can change the register.'}[page])
with b:
    if st.button('↻ Refresh',use_container_width=True):refresh()
    if admin and st.button('＋ Add item',type='primary',use_container_width=True):add_item_dialog()
if st.session_state.get('notice'):st.success(st.session_state.pop('notice'))
try:data=snapshot(url,admin)
except Exception:st.error('Could not read the register. Please try Refresh.');st.stop()
items,members,holdings=data['items'],data['members'],data['holdings']
metrics=st.columns(3)
for col,label,value,desc in zip(metrics,['Item types','Available now','With members'],[len(items),sum(i['available'] for i in items),sum(i['total_qty']-i['available'] for i in items)],['In our collection','Ready for the next occasion','Pieces currently in use']):
    with col:st.metric(label,int(value));st.caption(desc)
st.divider()
if admin and st.session_state.get('return_receipt'):
    r=st.session_state.return_receipt;m=next(x for x in members if x['id']==r['member_id']);i=next(x for x in items if x['id']==r['item_id']);held=next((h['quantity'] for h in holdings if h['member_id']==m['id'] and h['item_id']==i['id']),0)
    with st.expander('Return confirmation — copy or send',expanded=True):
        share_block(return_message(m['name'],i['name'],r['quantity'],r['when'],r['note'],held),m.get('whatsapp',''))
        if st.button('Dismiss confirmation'):del st.session_state.return_receipt;st.rerun()

if page=='Inventory':
    left,middle,right=st.columns([3,1,1])
    query=left.text_input('Search inventory',placeholder='Search items, categories, notes…',label_visibility='collapsed')
    category=middle.selectbox('Category',['All categories']+sorted({i['category'] for i in items}),label_visibility='collapsed')
    availability=right.selectbox('Availability',['All availability','Available','All with members'],label_visibility='collapsed')
    found=[i for i in items if query.lower() in (i['name']+' '+i['category']+' '+i['note']).lower() and (category=='All categories' or i['category']==category) and (availability=='All availability' or (i['available']>0 if availability=='Available' else i['available']==0))]
    if not items:
        st.markdown('<div class="empty"><div class="empty-icon">📦</div><div class="eyebrow">GOOD THINGS START HERE</div><h2>Your collection starts with one item.</h2><p>Add the things your mandal shares — chairs, utensils, decorations,<br>or anything that brings everyone together.</p></div>',unsafe_allow_html=True)
        if admin and st.button('＋ Add your first item',type='primary'):add_item_dialog()
    elif not found:st.info('No matching items. Try another search or filter.')
    for start in range(0,len(found),3):
        for col,item in zip(st.columns(3),found[start:start+3]):
            with col,st.container(border=True):
                payload=cached_photo(url,item['id'],item['photo_version']) if item['has_photo'] else None
                if payload:st.image(payload,use_container_width=True)
                else:st.markdown('<div class="photo-placeholder">📦</div>',unsafe_allow_html=True)
                st.caption(item['category'].upper());st.subheader(item['name'])
                st.markdown(f'**{int(item["available"])}** available · **{int(item["total_qty"]-item["available"])}** with members')
                if item['note']:st.caption(item['note'])
                with st.expander('Current holders'):
                    ih=[h for h in holdings if h['item_id']==item['id']]
                    for h in ih:st.write(f'@{h["member_name"]} — {int(h["quantity"])} pcs')
                    if not ih:st.caption('All pieces are with the mandal.')
                if admin:
                    a,b=st.columns(2)
                    if a.button('Hand over',key='issue'+item['id'],disabled=item['available']<1,use_container_width=True):transaction_dialog(item['id'])
                    if b.button('Return',key='return'+item['id'],disabled=not any(h['item_id']==item['id'] for h in holdings),use_container_width=True):transaction_dialog(item['id'],'return')
                    if st.button('Change photo',key='photo'+item['id'],use_container_width=True):replace_photo_dialog(item['id'])

elif page in ('Current holders','Share my list'):
    if not members:st.info('No members have been added yet.')
    else:
        chosen=st.selectbox('Choose a member',members,index=None if page=='Share my list' else 0,placeholder='Select your name…',format_func=lambda m:m['name'])
        if chosen:
            my=[h for h in holdings if h['member_id']==chosen['id']]
            st.subheader(chosen['name'])
            if not my:st.info('No items currently recorded with this member.')
            for h in my:
                with st.container(border=True):
                    a,b=st.columns([4,1]);a.write(f'**{h["item_name"]}**');a.caption(f'Current holder: @{chosen["name"]}');b.write(f'**× {int(h["quantity"])}**')
                    if admin and st.button('Record return',key='heldreturn'+h['item_id']+h['member_id']):transaction_dialog(h['item_id'],'return',chosen['id'])
            st.markdown('#### Share current holdings')
            share_block(holding_message(chosen['name'],my),chosen.get('whatsapp',''))
    if not admin:st.caption('To correct a quantity or confirm a return, contact the mandal admin.')

elif page=='History':
    a,b=st.columns([3,1]);search=a.text_input('Search transactions',placeholder='Item, member or note');kind=b.selectbox('Action',['all','issue','return'],format_func=lambda k:{'all':'All actions','issue':'Handovers','return':'Returns'}[k])
    page_no=st.number_input('Page',min_value=1,value=1,step=1)
    rows=db.history((page_no-1)*20,search,kind)
    if not rows:st.info('No matching transactions.')
    for tx in rows[:20]:
        with st.container(border=True):
            st.markdown(f'**{"↗ Handed over" if tx["kind"]=="issue" else "↙ Returned"} · {int(tx["quantity"])} × {html.escape(tx["item"])}**')
            st.caption(f'@{tx["holder"]} · {ist(tx["created_at"])}');st.write(tx['note'] or '—')
            if tx['kind']=='return':
                with st.expander('Copy return confirmation'):
                    held=next((h['quantity'] for h in holdings if h['item_id']==tx.get('item_id') and h['member_id']==tx.get('member_id')),None)
                    # IDs in the paginated history avoid confusing same-name members/items.
                    member=next((m for m in members if m['id']==tx['member_id']),None)
                    share_block(return_message(tx['holder'],tx['item'],tx['quantity'],ist(tx['created_at']),tx['note'],held or 0),member.get('whatsapp','') if member else '')
    st.caption('More records are available on the next page.' if len(rows)>20 else 'End of these results.')
    if rows:
        import csv
        out=io.StringIO();writer=csv.writer(out);writer.writerow(['Action','Item','Holder','Quantity','Date IST','Note'])
        for tx in rows[:20]:writer.writerow([("'"+str(v)) if str(v).startswith(('=','+','-','@')) else v for v in [tx['kind'],tx['item'],tx['holder'],tx['quantity'],ist(tx['created_at']),tx['note']]])
        st.download_button('Download this page (CSV)',out.getvalue(),'mandal-history.csv','text/csv')

elif page=='Admin':
    if not admin:
        st.subheader('Admin sign in')
        st.caption('Members can view the register and copy messages without signing in.')
        credential=setting('ADMIN_PASSWORD_HASH') or setting('ADMIN_PASSWORD')
        configured=bool(credential and setting('ADMIN_USERNAME'))
        if not configured:st.info('Set ADMIN_USERNAME and ADMIN_PASSWORD (at least 12 characters) in Streamlit Secrets to enable admin sign-in.')
        else:
            with st.form('admin_login',clear_on_submit=True):
                username=st.text_input('Admin username');password=st.text_input('Password',type='password')
                if st.form_submit_button('Sign in',type='primary'):
                    ok,message=db.authenticate(username,password,setting('ADMIN_USERNAME'),credential)
                    if ok:
                        st.session_state.admin_ok=True;st.session_state.last_admin=time.time();st.session_state.admin_started=time.time();st.rerun()
                    else:st.error(message)
    else:
        st.subheader('Our members')
        st.caption('Store names and WhatsApp numbers here. Viewing never requires member accounts.')
        if st.button('＋ Add member',type='primary'):member_dialog()
        for m in members:
            with st.container(border=True):
                a,b=st.columns([4,1]);a.write(f'**{m["name"]}** · {"Active" if m["active"] else "Paused"}');a.caption('WhatsApp: +'+m['whatsapp'] if m['whatsapp'] else 'WhatsApp not added')
                if b.button('Edit',key='edit'+m['id']):member_dialog(m)
        st.caption('Admin session ends after 30 minutes of inactivity or 8 hours. Transactions are kept as history; returns restore stock.')
        st.info('This Streamlit version allows anyone who can open the app to read inventory, holder names and history. WhatsApp numbers and all editing remain admin-only.')
st.markdown('<div class="footer">📦 Samaan <span>Our things. Our responsibility.</span></div>',unsafe_allow_html=True)
