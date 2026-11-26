import sys, tempfile, unittest, uuid, time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from controller import view_data
from native_protocol import handle_native_request

class ExistingSetupNativeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Store('sqlite:///'+self.temp.name+'/test.db');self.db.initialize()
        self.db.add_item('Plates','Utensils','Shelf',10,admin=True);self.db.save_member('Jay','9876543210',admin=True)
        data=self.db.snapshot(True);self.item=data['items'][0]['id'];self.member=data['members'][0]['id'];self.session={}
        self.config={'ADMIN_USERNAME':'admin','ADMIN_PASSWORD':'test-password-long'}
    def tearDown(self):self.temp.cleanup()
    def wrap(self,event):return {'id':str(uuid.uuid4()),'action':'native_request','request':event}
    def call(self,event):return handle_native_request(self.db,self.wrap(event),self.session,self.config,lambda i,v:self.db.photo(i,v),lambda *a:None)
    def event(self,action,**kw):return {'id':str(uuid.uuid4()),'action':action,**kw}
    def login(self):self.assertTrue(self.call(self.event('login',username='admin',password='test-password-long'))[0]['ok'])
    def test_public_read_and_admin_guards(self):
        self.assertTrue(self.call(self.event('native_sync',page=1,query='',kind='all'))[0]['ok'])
        result=self.call(self.event('issue',item_id=self.item,member_id=self.member,quantity=2,admin=True))[0]
        self.assertFalse(result['ok']);self.assertEqual(self.db.snapshot()['items'][0]['available'],10)
        payload=view_data(self.db,self.db.snapshot(),self.session,self.config)
        self.assertNotIn('whatsapp',payload['members'][0]);self.assertNotIn(self.config['ADMIN_PASSWORD'],str(payload))
    def test_delivery_rerun_and_explicit_ledger_retry(self):
        self.login();event=self.event('issue',item_id=self.item,member_id=self.member,quantity=4)
        envelope=self.wrap(event)
        result=handle_native_request(self.db,envelope,self.session,self.config,lambda *a:None,lambda *a:None)[0]
        self.assertTrue(result['ok'])
        self.assertIsNone(handle_native_request(self.db,envelope,self.session,self.config,lambda *a:None,lambda *a:None)[0])
        self.assertTrue(self.call(event)[0]['ok']);self.assertEqual(self.db.snapshot()['items'][0]['available'],6)
        changed=dict(event,quantity=5);self.assertFalse(self.call(changed)[0]['ok'])
        self.session.pop('native_results',None);self.session.pop('processed_event',None)
        self.assertTrue(self.call(event)[0]['ok']);self.assertEqual(self.db.snapshot()['items'][0]['available'],6)
    def test_partial_return_history_and_logout(self):
        self.login();self.call(self.event('issue',item_id=self.item,member_id=self.member,quantity=4))
        self.assertTrue(self.call(self.event('return',item_id=self.item,member_id=self.member,quantity=2,note='Good'))[0]['ok'])
        self.assertEqual(self.db.snapshot()['holdings'][0]['quantity'],2)
        self.assertFalse(self.call(self.event('return',item_id=self.item,member_id=self.member,quantity=3))[0]['ok'])
        self.call(self.event('native_sync',page=1,query='',kind='return'))
        payload=view_data(self.db,self.db.snapshot(True),self.session,self.config)
        self.assertEqual(len(payload['history']),1);self.assertIn('પરત',payload['receipt']['text'])
        self.assertTrue(self.call(self.event('logout'))[0]['ok'])
        payload=view_data(self.db,self.db.snapshot(),self.session,self.config)
        self.assertNotIn('whatsapp',payload['members'][0]);self.assertIsNone(payload['receipt'])
    def test_expiry_rejects_cached_mutation(self):
        self.login();event=self.event('issue',item_id=self.item,member_id=self.member,quantity=1)
        self.assertTrue(self.call(event)[0]['ok'])
        with patch('controller.time.time',return_value=time.time()+1900):
            self.assertFalse(self.call(event)[0]['ok'])
        self.assertEqual(self.db.snapshot()['items'][0]['available'],9)
    def test_actual_streamlit_native_component_and_website(self):
        import os, json
        from streamlit.testing.v1 import AppTest
        with patch.dict(os.environ, {'DATABASE_URL':self.db.url,'ALLOW_LOCAL_SQLITE':'true','ADMIN_USERNAME':'admin','ADMIN_PASSWORD':'test-password-long'}):
            app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20)
            app.query_params['mandal_native']='1'
            app.query_params['native_client']='test-native-client'
            app.run();self.assertEqual(len(app.exception),0)
            def args():return json.loads(app.get('component_instance')[0].proto.json_args)
            self.assertEqual(args()['client'],'test-native-client')
            self.assertNotIn('whatsapp',args()['data']['members'][0])
            def send(action,**kw):
                event=self.wrap(self.event(action,**kw))
                app.session_state['samaan_native_connection']=event
                app.run();self.assertEqual(len(app.exception),0)
                self.assertEqual(args()['response']['delivery'],event['id'])
                return args()
            self.assertFalse(send('issue',item_id=self.item,member_id=self.member,quantity=2)['response']['ok'])
            self.assertTrue(send('login',username='admin',password='test-password-long')['data']['admin'])
            self.assertEqual(send('issue',item_id=self.item,member_id=self.member,quantity=4)['data']['items'][0]['available'],6)
            self.assertEqual(send('return',item_id=self.item,member_id=self.member,quantity=2)['data']['items'][0]['available'],8)
            self.assertEqual(len(send('native_sync',page=1,query='',kind='return')['data']['history']),1)
            self.assertFalse(send('logout')['data']['admin'])
            self.assertNotIn('whatsapp',args()['data']['members'][0])
            # The ordinary deployment still selects its original website component.
            normal=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20).run()
            self.assertEqual(len(normal.exception),0)
            self.assertIn('samaan_workspace',normal.get('component_instance')[0].proto.component_name)

    def test_validation_and_failed_login(self):
        self.assertFalse(self.call(self.event('login',username='admin',password='bad'))[0]['ok'])
        self.assertFalse(self.call(self.event('native_sync',page=0))[0]['ok'])
        self.assertFalse(self.call(self.event('native_sync',page=True))[0]['ok'])
        self.assertFalse(self.call(self.event('arbitrary_sql'))[0]['ok'])
        self.assertIsNone(handle_native_request(self.db,{'id':'bad','request':{}},self.session,self.config,lambda *a:None,lambda *a:None)[0])
