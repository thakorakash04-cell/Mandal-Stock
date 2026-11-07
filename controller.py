"""Server-side actions and presentation data for the Samaan web interface.

The component is a view only: no client role flag can authorize a write.
"""
import base64
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo
from store import holding_message, return_message, whatsapp_link
from media import compress_photo


def is_admin(session):
    if not session.get('admin_ok'):
        return False
    now=time.time()
    if now-session.get('last_admin',0)>1800 or now-session.get('admin_started',0)>28800:
        session['admin_ok']=False
        return False
    session['last_admin']=now
    return True


def ist(value):
    try:
        return datetime.fromisoformat(value).astimezone(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p IST')
    except (ValueError,TypeError):
        return str(value)


def decode_photo(value):
    if not value:
        return None
    if not isinstance(value,str) or len(value)>14_000_000:
        raise ValueError('Choose a photo smaller than 10 MB.')
    try:
        raw=base64.b64decode(value,validate=True)
    except (ValueError,TypeError):
        raise ValueError('Please choose a valid image.') from None
    return compress_photo(raw)


def handle_event(db,event,session,config,load_photo,seed_photo):
    """Return (response, invalidate_metadata). All changes require server auth."""
    if not isinstance(event,dict) or not event.get('id'):
        return None,False
    event_id=str(event['id'])
    if session.get('processed_event')==event_id:
        return None,False
    session['processed_event']=event_id
    response={'id':event_id,'action':event.get('action'),'ok':False}
    action=event.get('action')
    try:
        if action=='ack':
            return None,False
        if not db:
            raise ValueError('The admin needs to configure the database and credentials in Streamlit Secrets first.')
        if action=='login':
            credential=config.get('ADMIN_PASSWORD_HASH') or config.get('ADMIN_PASSWORD')
            if not credential or not config.get('ADMIN_USERNAME'):
                raise ValueError('Admin credentials are not configured yet.')
            if not isinstance(event.get('username'),str) or not isinstance(event.get('password'),str):
                raise ValueError('Enter your admin username and password.')
            ok,message=db.authenticate(event['username'],event['password'],config['ADMIN_USERNAME'],credential)
            if not ok:
                raise ValueError(message)
            session.update(admin_ok=True,admin_started=time.time(),last_admin=time.time())
            response.update(ok=True,message='Admin signed in.')
            return response,True
        if action=='logout':
            session['admin_ok']=False
            session.pop('receipt',None)
            response.update(ok=True,message='Signed out.')
            return response,True
        if action=='refresh':
            response.update(ok=True,message='Register refreshed.')
            return response,True
        if action=='history':
            session['history_page']=max(1,int(event.get('page',1)))
            session['history_search']=str(event.get('query',''))[:200]
            session['history_kind']=event.get('kind') if event.get('kind') in ('issue','return') else 'all'
            session['history_rows']=db.history((session['history_page']-1)*20,session['history_search'],session['history_kind'])
            response['ok']=True
            return response,False
        if action=='photos':
            # Photo IDs/versions come from server metadata, never from a client URL.
            current=session.get('photo_index')
            if current is None:
                current={i['id']:i for i in db.snapshot()['items']}
            images=[]
            requested=event.get('items',[])
            if not isinstance(requested,list):
                raise ValueError('Invalid photo request.')
            for request in requested[:48]:
                if not isinstance(request,dict):
                    continue
                item=current.get(request.get('id'))
                if not item or not item['has_photo'] or item['photo_version']!=request.get('version'):
                    continue
                data=load_photo(item['id'],item['photo_version'])
                if data:
                    images.append({'id':item['id'],'version':item['photo_version'],'data':base64.b64encode(data).decode()})
            response.update(ok=True,images=images)
            return response,False
        # Everything below is a mutation. The browser cannot supply its own role.
        if not is_admin(session):
            raise PermissionError('Please sign in as admin to change records.')
        if action=='add_item':
            data=decode_photo(event.get('photo'))
            result=db.add_item(event.get('name'),event.get('category'),event.get('note',''),event.get('quantity'),data,admin=True)
            if data:
                seed_photo(result,data)
            response.update(ok=True,message='Item added to the collection.')
        elif action=='replace_photo':
            data=decode_photo(event.get('photo'))
            result=db.replace_photo(event.get('item_id'),data,admin=True)
            seed_photo(result,data)
            response.update(ok=True,message='Photo updated. Other cached photos are kept.')
        elif action=='member':
            db.save_member(event.get('name'),event.get('whatsapp',''),event.get('member_id'),bool(event.get('active',True)),admin=True)
            response.update(ok=True,message='Member saved.')
        elif action in ('issue','return'):
            uuid.UUID(event_id)
            db.record(event.get('item_id'),event.get('member_id'),action,event.get('quantity'),event.get('note',''),event_id,admin=True)
            session['receipt']={'kind':action,'item_id':event['item_id'],'member_id':event['member_id'],'quantity':event['quantity'],'note':event.get('note',''),'when':datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%d %b %Y, %I:%M %p IST')}
            response.update(ok=True,message='Handover recorded.' if action=='issue' else 'Return recorded. Gujarati confirmation is ready.')
        else:
            raise ValueError('Unknown action.')
        return response,True
    except (ValueError,PermissionError,TypeError) as exc:
        response['error']=str(exc)
    except Exception:
        # Never serialize connection errors or credential-bearing tracebacks.
        response['error']='Could not complete this action. Refresh the register and try again.'
    return response,False


def view_data(db,data,session,config):
    """Only this sanitized dictionary crosses the Streamlit component boundary."""
    admin=is_admin(session)
    members=[{k:v for k,v in m.items() if admin or k!='whatsapp'} for m in data['members']]
    items=data['items']
    session['photo_index']={i['id']:{'id':i['id'],'has_photo':i['has_photo'],'photo_version':i['photo_version']} for i in items}
    holdings=data['holdings']
    messages={}
    for member in members:
        message=holding_message(member['name'],[h for h in holdings if h['member_id']==member['id']])
        messages[member['id']]={'text':message}
        if admin and member.get('whatsapp'):
            messages[member['id']]['whatsapp']=whatsapp_link(member['whatsapp'],message)
    page=session.get('history_page',1)
    history=[dict(row) for row in session.get('history_rows',[])]
    has_more=len(history)>20
    history=history[:20]
    for tx in history:
        tx['date_label']=ist(tx['created_at'])
        if tx['kind']=='return':
            balance=next((h['quantity'] for h in holdings if h['item_id']==tx['item_id'] and h['member_id']==tx['member_id']),0)
            tx['message']=return_message(tx['holder'],tx['item'],tx['quantity'],tx['date_label'],tx['note'],balance)
            member=next((m for m in members if m['id']==tx['member_id']),None)
            if admin and member and member.get('whatsapp'):
                tx['whatsapp']=whatsapp_link(member['whatsapp'],tx['message'])
    receipt=None
    stored=session.get('receipt') if admin else None
    if stored:
        member=next((m for m in members if m['id']==stored['member_id']),None)
        item=next((i for i in items if i['id']==stored['item_id']),None)
        if member and item:
            balance=next((h['quantity'] for h in holdings if h['item_id']==item['id'] and h['member_id']==member['id']),0)
            message=return_message(member['name'],item['name'],stored['quantity'],stored['when'],stored['note'],balance) if stored['kind']=='return' else messages[member['id']]['text']
            receipt={'text':message,'title':'Return confirmation' if stored['kind']=='return' else 'Current holdings'}
            if member.get('whatsapp'):
                receipt['whatsapp']=whatsapp_link(member['whatsapp'],message)
    return {'admin':admin,'items':items,'members':members,'holdings':holdings,'history':history,'historyPage':page,'historyHasMore':has_more,'messages':messages,'receipt':receipt,'mandalName':config.get('MANDAL_NAME') or 'Our mandal','adminConfigured':bool(config.get('ADMIN_USERNAME') and (config.get('ADMIN_PASSWORD_HASH') or config.get('ADMIN_PASSWORD'))),'setupNeeded':db is None}
