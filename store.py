"""Durable records; PostgreSQL in hosting, explicit SQLite for local development."""
import sqlite3, uuid, re, time, hmac, hashlib
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote

class Store:
    def __init__(self, url):
        if not url: raise ValueError('Configure DATABASE_URL in Streamlit Secrets before using the register.')
        self.url=url; self.local=url.startswith('sqlite:///')
        if not self.local and not url.startswith(('postgresql://','postgres://')): raise ValueError('Use a PostgreSQL connection URL.')
    @contextmanager
    def connect(self, write=False):
        if self.local:
            c=sqlite3.connect(self.url.removeprefix('sqlite:///'),timeout=15);c.row_factory=sqlite3.Row;c.execute('PRAGMA foreign_keys=ON')
            if write:c.execute('BEGIN IMMEDIATE')
        else:
            import psycopg
            from psycopg.rows import dict_row
            c=psycopg.connect(self.url,row_factory=dict_row,connect_timeout=10)
        try:
            yield c;c.commit()
        except Exception:
            c.rollback();raise
        finally:c.close()
    def execute(self,c,sql,args=()):return c.execute(sql.replace('?', '%s') if not self.local else sql,args)
    def initialize(self):
        with self.connect(True) as c:
            for statement in Path(__file__).with_name('schema.sql').read_text().split(';'):
                if statement.strip():self.execute(c,statement)
    def _admin(self,admin):
        if admin is not True:raise PermissionError('Admin sign-in is required to change records.')
    def snapshot(self,admin=False):
        with self.connect() as c:
            items=[dict(r) for r in self.execute(c,"SELECT i.id,i.name,i.category,i.note,i.total_qty,i.created_at,CASE WHEN i.photo IS NULL THEN 0 ELSE 1 END AS has_photo,i.total_qty-COALESCE(SUM(CASE WHEN t.kind='issue' THEN t.quantity ELSE -t.quantity END),0) AS available FROM mandal_items i LEFT JOIN mandal_transactions t ON t.item_id=i.id GROUP BY i.id ORDER BY i.name").fetchall()]
            fields='id,name,active'+(',whatsapp' if admin else '')
            members=[dict(r) for r in self.execute(c,f'SELECT {fields} FROM mandal_members ORDER BY name').fetchall()]
            holdings=[dict(r) for r in self.execute(c,"SELECT t.item_id,t.member_id,i.name AS item_name,m.name AS member_name,SUM(CASE WHEN t.kind='issue' THEN t.quantity ELSE -t.quantity END) AS quantity FROM mandal_transactions t JOIN mandal_items i ON i.id=t.item_id JOIN mandal_members m ON m.id=t.member_id GROUP BY t.item_id,t.member_id,i.name,m.name HAVING SUM(CASE WHEN t.kind='issue' THEN t.quantity ELSE -t.quantity END)>0 ORDER BY m.name,i.name").fetchall()]
            return dict(items=items,members=members,holdings=holdings)
    def history(self,offset=0,search='',kind='all'):
        pattern='%'+search.lower()+'%'
        with self.connect() as c:
            return [dict(r) for r in self.execute(c,"SELECT t.id,t.item_id,t.member_id,t.kind,t.quantity,t.note,t.created_at,i.name AS item,m.name AS holder FROM mandal_transactions t JOIN mandal_items i ON i.id=t.item_id JOIN mandal_members m ON m.id=t.member_id WHERE (LOWER(i.name) LIKE ? OR LOWER(m.name) LIKE ? OR LOWER(t.note) LIKE ?) AND (?='all' OR t.kind=?) ORDER BY t.created_at DESC,t.id DESC LIMIT 21 OFFSET ?",(pattern,pattern,pattern,kind,kind,offset)).fetchall()]
    def photo(self,item_id):
        with self.connect() as c:
            row=self.execute(c,'SELECT photo FROM mandal_items WHERE id=?',(item_id,)).fetchone()
            return bytes(row['photo']) if row and row['photo'] else None
    def add_item(self,name,category,note,quantity,photo=None,admin=False):
        self._admin(admin);name=clean(name,120);quantity=whole(quantity)
        if photo and len(photo)>200_000:raise ValueError('Photo must be under 200 KB after compression.')
        with self.connect(True) as c:self.execute(c,'INSERT INTO mandal_items(id,name,category,note,total_qty,photo,created_at) VALUES(?,?,?,?,?,?,?)',(str(uuid.uuid4()),name,clean(category,50),str(note).strip()[:500],quantity,photo,now()))
    def save_member(self,name,whatsapp,member_id=None,active=True,admin=False):
        self._admin(admin);name=clean(name,80);phone=phone_number(whatsapp)
        with self.connect(True) as c:
            if member_id:
                self.execute(c,'UPDATE mandal_members SET name=?,whatsapp=?,active=? WHERE id=?',(name,phone,int(active),member_id))
            else:
                if self.execute(c,'SELECT COUNT(*) AS n FROM mandal_members').fetchone()['n']>=25:raise ValueError('This register supports 25 members.')
                self.execute(c,'INSERT INTO mandal_members(id,name,whatsapp,active) VALUES(?,?,?,1)',(str(uuid.uuid4()),name,phone))
    def record(self,item_id,member_id,kind,quantity,note,request_id,admin=False):
        self._admin(admin);quantity=whole(quantity)
        if kind not in ('issue','return'):raise ValueError('Choose handover or return.')
        uuid.UUID(request_id)
        with self.connect(True) as c:
            lock='' if self.local else ' FOR UPDATE'
            item=self.execute(c,'SELECT total_qty FROM mandal_items WHERE id=?'+lock,(item_id,)).fetchone()
            if not item:raise ValueError('Item no longer exists.')
            old=self.execute(c,'SELECT item_id,member_id,kind,quantity FROM mandal_transactions WHERE id=?',(request_id,)).fetchone()
            if old:
                if (old['item_id'],old['member_id'],old['kind'],old['quantity'])!=(item_id,member_id,kind,quantity):raise ValueError('This request ID has already been used.')
                return
            member=self.execute(c,'SELECT active FROM mandal_members WHERE id=?',(member_id,)).fetchone()
            if not member:raise ValueError('Choose an existing member.')
            sums=self.execute(c,"SELECT COALESCE(SUM(CASE WHEN kind='issue' THEN quantity ELSE -quantity END),0) AS outstanding,COALESCE(SUM(CASE WHEN member_id=? THEN CASE WHEN kind='issue' THEN quantity ELSE -quantity END ELSE 0 END),0) AS held FROM mandal_transactions WHERE item_id=?",(member_id,item_id)).fetchone()
            if kind=='issue' and not member['active']:raise ValueError('This member is paused.')
            if kind=='issue' and quantity>item['total_qty']-sums['outstanding']:raise ValueError('Not enough stock available. Refresh the register.')
            if kind=='return' and quantity>sums['held']:raise ValueError('Return exceeds what this member holds.')
            self.execute(c,'INSERT INTO mandal_transactions(id,item_id,member_id,kind,quantity,note,created_at) VALUES(?,?,?,?,?,?,?)',(request_id,item_id,member_id,kind,quantity,str(note).strip()[:500],now()))
    def authenticate(self,username,password,expected_user,encoded):
        """Persistent global throttling protects the single admin credential across sessions."""
        with self.connect(True) as c:
            self.execute(c,"INSERT INTO mandal_login_guard(id,failures,blocked_until) VALUES(1,0,0) ON CONFLICT(id) DO NOTHING")
            lock='' if self.local else ' FOR UPDATE'
            guard=self.execute(c,'SELECT failures,blocked_until FROM mandal_login_guard WHERE id=1'+lock).fetchone()
            if guard['blocked_until']>time.time():return False,'Too many attempts. Please try again in a few minutes.'
            valid=hmac.compare_digest(str(username),str(expected_user)) and (verify_password(password,encoded) if str(encoded).startswith('pbkdf2_sha256$') else len(str(encoded))>=12 and hmac.compare_digest(hashlib.sha256(password.encode()).digest(),hashlib.sha256(str(encoded).encode()).digest()))
            if valid:self.execute(c,'UPDATE mandal_login_guard SET failures=0,blocked_until=0 WHERE id=1');return True,''
            failures=guard['failures']+1 if guard['blocked_until']==0 else 1
            self.execute(c,'UPDATE mandal_login_guard SET failures=?,blocked_until=? WHERE id=1',(failures,time.time()+300 if failures>=5 else 0))
            return False,'Incorrect admin username or password.'

def clean(value,limit):
    if not isinstance(value,str) or not value.strip() or len(value.strip())>limit:raise ValueError(f'Enter a name of 1–{limit} characters.')
    return value.strip()
def whole(value):
    if isinstance(value,bool) or not isinstance(value,int) or not 1<=value<=100000:raise ValueError('Quantity must be a whole number between 1 and 100,000.')
    return value
def phone_number(value):
    raw=str(value).strip()
    if not raw:return ''
    if not re.fullmatch(r'[+\d\s()-]+',raw):raise ValueError('Enter a WhatsApp number with country code, e.g. +91 9876543210.')
    digits=re.sub(r'\D','',raw)
    if len(digits)==10:digits='91'+digits
    if digits.startswith('00'):digits=digits[2:]
    if not 8<=len(digits)<=15 or digits.startswith('0'):raise ValueError('Enter a valid international WhatsApp number.')
    return digits
def now():return datetime.now(timezone.utc).isoformat()
def holding_message(name,holdings):
    lines=[f'નમસ્તે {name},','', 'મંડળનો સામાન — હાલમાં આપની પાસે રહેલા સામાનની યાદી:','']
    if holdings:lines += [f'{n}. {h["item_name"]} — {int(h["quantity"])} નંગ' for n,h in enumerate(holdings,1)]
    else:lines += ['હાલમાં આપની પાસે મંડળનો કોઈ સામાન નોંધાયેલ નથી.']
    lines += ['',f'કુલ: {sum(int(h["quantity"]) for h in holdings)} નંગ','', 'કૃપા કરીને આ યાદી તપાસીને પુષ્ટિ કરશો. કોઈ સામાન પરત આપ્યો હોય અથવા જથ્થામાં તફાવત હોય તો નોંધ સુધારવા માટે મંડળના સંચાલકને જાણ કરશો.','', 'આભાર. 🙏']
    return '\n'.join(lines)
def whatsapp_link(number,message):return 'https://wa.me/'+phone_number(number)+'?text='+quote(message,safe='')
def password_hash(password,salt=None):
    import secrets
    if len(password)<12:raise ValueError('Use at least 12 characters.')
    salt=salt or secrets.token_hex(16)
    return f'pbkdf2_sha256$600000${salt}$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
def verify_password(password,encoded):
    try:
        algorithm,iterations,salt,wanted=encoded.split('$')
        if algorithm!='pbkdf2_sha256' or int(iterations)!=600000:return False
        got=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(iterations)).hex()
        return hmac.compare_digest(got,wanted)
    except (ValueError,TypeError,AttributeError):return False

def return_message(name,item,quantity,returned_at,note,current_holding):
    return '\n'.join([f'નમસ્તે {name},','', 'મંડળનો સામાન — સામાન પરત મળ્યાની પુષ્ટિ','',f'સામાન: {item}',f'પરત મળેલો જથ્થો: {int(quantity)} નંગ',f'પરત મળ્યાની નોંધની તારીખ અને સમય: {returned_at}',f'નોંધ: {note or "—"}','',f'આ સામાનમાંથી હાલમાં આપની પાસે બાકી રહેલો જથ્થો: {int(current_holding)} નંગ','(આ સંદેશ તૈયાર કરતી વખતે રજિસ્ટરમાં નોંધાયેલ બાકી જથ્થો.)','', 'સામાન પરત આપવા બદલ આભાર. કોઈ વિગતમાં સુધારો જરૂરી હોય તો મંડળના સંચાલકને જાણ કરશો. 🙏'])
