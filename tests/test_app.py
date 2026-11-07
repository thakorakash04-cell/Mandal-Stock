import os, sys, tempfile, unittest, uuid, concurrent.futures
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store,holding_message,return_message,whatsapp_link,password_hash

class RegisterTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.url='sqlite:///'+self.temp.name+'/test.db';self.db=Store(self.url);self.db.initialize()
        self.db.save_member('Jay','9876543210',admin=True);self.db.save_member('Meet','+91 9876543211',admin=True)
        self.db.add_item('Plates','Utensils','Storage shelf',10,admin=True)
        data=self.db.snapshot(True);self.item=data['items'][0]['id'];self.member=data['members'][0]['id'];self.other=data['members'][1]['id']
    def tearDown(self):self.temp.cleanup()
    def tx(self,kind,qty,member=None,token=None):self.db.record(self.item,member or self.member,kind,qty,'Test',token or str(uuid.uuid4()),admin=True)
    def test_handover_partial_full_return_and_retry(self):
        token=str(uuid.uuid4());self.tx('issue',6,token=token);self.tx('issue',6,token=token)
        self.assertEqual(self.db.snapshot()['items'][0]['available'],4)
        self.tx('return',2);self.assertEqual(self.db.snapshot()['holdings'][0]['quantity'],4)
        with self.assertRaises(ValueError):self.tx('return',5)
        with self.assertRaises(ValueError):self.tx('return',1,self.other)
        with self.assertRaises(ValueError):self.tx('issue',7)
        for n in (-1,0,1.5,True):
            with self.assertRaises(ValueError):self.tx('issue',n)
        self.tx('return',4);self.assertEqual(self.db.snapshot()['holdings'],[])
    def test_concurrent_handover(self):
        def reserve(_):
            try:self.tx('issue',7);return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:results=list(pool.map(reserve,range(2)))
        self.assertEqual(sum(results),1);self.assertEqual(self.db.snapshot()['items'][0]['available'],3)
    def test_public_phone_privacy_and_admin_guard(self):
        self.assertNotIn('whatsapp',self.db.snapshot()['members'][0]);self.assertIn('whatsapp',self.db.snapshot(True)['members'][0])
        with self.assertRaises(PermissionError):self.db.add_item('Test','General','',1)
        with self.assertRaises(PermissionError):self.db.save_member('Test','1234567890')
        with self.assertRaises(PermissionError):self.db.record(self.item,self.member,'issue',1,'',str(uuid.uuid4()))
    def test_pause_and_templates(self):
        self.tx('issue',4);m=self.db.snapshot(True)['members'][0];self.db.save_member(m['name'],m['whatsapp'],m['id'],False,admin=True)
        with self.assertRaises(ValueError):self.tx('issue',1)
        self.tx('return',2)
        message=holding_message(m['name'],self.db.snapshot()['holdings']);self.assertIn('Plates — 2 નંગ',message)
        receipt=return_message(m['name'],'Plates',2,'7 Nov 2026, 11 AM IST','Good condition',2)
        for text in ['પરત મળેલો જથ્થો: 2','Good condition','આ સામાનમાંથી હાલમાં આપની પાસે બાકી રહેલો જથ્થો: 2']:self.assertIn(text,receipt)
        self.assertIn('https://wa.me/91',whatsapp_link(m['whatsapp'],message));self.assertIn('%0A',whatsapp_link(m['whatsapp'],message))
        row=self.db.history()[0];self.assertIn('member_id',row);self.assertIn('item_id',row)
    def test_login_throttling(self):
        hashed=password_hash('a-safe-test-password')
        self.assertTrue(self.db.authenticate('admin','a-safe-test-password','admin',hashed)[0])
        for _ in range(5):self.assertFalse(self.db.authenticate('admin','incorrect','admin',hashed)[0])
        self.assertIn('Too many',self.db.authenticate('admin','a-safe-test-password','admin',hashed)[1])
    def test_streamlit_public_and_admin(self):
        import json
        from streamlit.testing.v1 import AppTest
        os.environ.update(DATABASE_URL=self.url,ALLOW_LOCAL_SQLITE='true',ADMIN_USERNAME='admin',ADMIN_PASSWORD='test-password-long')
        app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20).run()
        self.assertEqual(len(app.exception),0)
        def payload():return json.loads(app.get('component_instance')[0].proto.json_args)['data']
        public=payload();self.assertFalse(public['admin']);self.assertNotIn('whatsapp',public['members'][0])
        self.assertIn('નમસ્તે',public['messages'][self.member]['text'])
        app.session_state['samaan_workspace']={'id':str(uuid.uuid4()),'action':'login','username':'admin','password':'test-password-long'}
        app.run();self.assertEqual(len(app.exception),0);self.assertTrue(payload()['admin'])
        self.assertIn('whatsapp',payload()['members'][0])
        app.session_state['samaan_workspace']={'id':str(uuid.uuid4()),'action':'issue','item_id':self.item,'member_id':self.member,'quantity':3,'note':'Event'}
        app.run();self.assertEqual(len(app.exception),0);self.assertEqual(payload()['holdings'][0]['quantity'],3)
        app.session_state['samaan_workspace']={'id':str(uuid.uuid4()),'action':'return','item_id':self.item,'member_id':self.member,'quantity':1,'note':'Good'}
        app.run();self.assertEqual(len(app.exception),0);self.assertIn('પરત મળેલો જથ્થો: 1',payload()['receipt']['text'])
        app.session_state['samaan_workspace']={'id':str(uuid.uuid4()),'action':'logout'}
        app.run();self.assertFalse(payload()['admin']);self.assertIsNone(payload()['receipt']);self.assertNotIn('whatsapp',payload()['members'][0])

if __name__=='__main__':unittest.main()

