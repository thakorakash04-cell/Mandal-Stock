import sys,time,tempfile,unittest,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from store import Store
from controller import handle_event,view_data

class ServerBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Store('sqlite:///'+self.temp.name+'/qa.db');self.db.initialize()
        self.db.save_member('Jay','9876543210',admin=True);self.db.add_item('Chairs','Furniture','',8,admin=True)
        data=self.db.snapshot(True);self.member=data['members'][0]['id'];self.item=data['items'][0]['id']
        self.config={'ADMIN_USERNAME':'admin','ADMIN_PASSWORD':'test-password-long'};self.session={}
    def tearDown(self):self.temp.cleanup()
    def action(self,action,**values):
        return handle_event(self.db,{'id':str(uuid.uuid4()),'action':action,**values},self.session,self.config,lambda *a:None,lambda *a:None)[0]
    def test_forged_admin_and_expired_session_cannot_write(self):
        result=self.action('issue',admin=True,item_id=self.item,member_id=self.member,quantity=1,note='')
        self.assertFalse(result['ok']);self.assertEqual(self.db.snapshot()['items'][0]['available'],8)
        self.session.update(admin_ok=True,last_admin=time.time()-1900,admin_started=time.time())
        self.assertFalse(self.action('issue',item_id=self.item,member_id=self.member,quantity=1,note='')['ok'])
        self.assertEqual(self.db.snapshot()['items'][0]['available'],8)
    def test_login_history_return_messages_and_logout(self):
        self.assertTrue(self.action('login',username='admin',password='test-password-long')['ok'])
        self.assertTrue(self.action('issue',item_id=self.item,member_id=self.member,quantity=4,note='Event')['ok'])
        self.assertTrue(self.action('return',item_id=self.item,member_id=self.member,quantity=2,note='Good')['ok'])
        self.action('history',page=1,query='',kind='return')
        payload=view_data(self.db,self.db.snapshot(True),self.session,self.config)
        self.assertEqual(len(payload['history']),1);self.assertIn('પરત મળેલો જથ્થો: 2',payload['history'][0]['message'])
        self.assertIn('whatsapp',payload['history'][0]);self.assertIn('whatsapp',payload['receipt'])
        self.action('logout');payload=view_data(self.db,self.db.snapshot(),self.session,self.config)
        self.assertNotIn('whatsapp',payload['members'][0]);self.assertIsNone(payload['receipt']);self.assertNotIn('whatsapp',payload['history'][0])
        self.assertNotIn('ADMIN_PASSWORD',str(payload));self.assertNotIn(self.config['ADMIN_PASSWORD'],str(payload))
    def test_history_not_loaded_until_requested(self):
        from unittest.mock import patch
        with patch.object(self.db,'history',side_effect=AssertionError('unnecessary history read')):
            payload=view_data(self.db,self.db.snapshot(),self.session,self.config)
            self.assertEqual(payload['history'],[])
    def test_replayed_event_is_not_processed_again(self):
        self.action('login',username='admin',password='test-password-long')
        event={'id':str(uuid.uuid4()),'action':'issue','item_id':self.item,'member_id':self.member,'quantity':2,'note':''}
        for _ in range(2):handle_event(self.db,event,self.session,self.config,lambda *a:None,lambda *a:None)
        self.assertEqual(self.db.snapshot()['items'][0]['available'],6)

if __name__=='__main__':unittest.main()
