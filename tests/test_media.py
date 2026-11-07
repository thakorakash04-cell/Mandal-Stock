import io, os, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PIL import Image
from media import compress_photo,cached_photo
from store import Store

class PhotoTests(unittest.TestCase):
    def picture(self,color):
        output=io.BytesIO();Image.new('RGB',(1800,1200),color).save(output,'PNG');return output.getvalue()
    def test_large_photo_compression_and_metadata(self):
        source=Image.effect_noise((2400,1800),100).convert('RGB');exif=source.getexif();exif[270]='camera metadata'
        original=io.BytesIO();source.save(original,'JPEG',quality=98,exif=exif)
        encoded=compress_photo(original.getvalue())
        self.assertLessEqual(len(encoded),60000);self.assertLess(len(encoded),len(original.getvalue()))
        with Image.open(io.BytesIO(encoded)) as result:
            self.assertLessEqual(max(result.size),720);self.assertEqual(dict(result.getexif()),{});self.assertEqual(result.format,'JPEG')
        with self.assertRaises(ValueError):compress_photo(b'a'*10000001)
    def test_version_migration_and_no_photo_in_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            import sqlite3
            path=Path(temp)/'old.db';c=sqlite3.connect(path)
            c.execute('CREATE TABLE mandal_items(id TEXT PRIMARY KEY,name TEXT,category TEXT,note TEXT,total_qty INTEGER,photo BYTEA,created_at TEXT)')
            c.execute("INSERT INTO mandal_items VALUES('old','Legacy','General','',1,?,'now')",(b'legacy-image',));c.commit();c.close()
            db=Store('sqlite:///'+str(path));db.initialize();db.initialize()
            item=db.snapshot()['items'][0];self.assertEqual(item['photo_version'],'legacy:old');self.assertNotIn('photo',item)
            encoded=compress_photo(self.picture('red'));changed=db.replace_photo('old',encoded,admin=True)
            self.assertNotEqual(changed['photo_version'],item['photo_version']);self.assertEqual(db.photo('old',changed['photo_version']),encoded)
            with self.assertRaises(PermissionError):db.replace_photo('old',encoded)
    def test_reruns_reuse_photos_and_only_changed_photo_reloads(self):
        from streamlit.testing.v1 import AppTest
        with tempfile.TemporaryDirectory() as temp:
            url='sqlite:///'+temp+'/photos.db';db=Store(url);db.initialize()
            red=compress_photo(self.picture('red'));blue=compress_photo(self.picture('blue'))
            first=db.add_item('First','General','',1,red,admin=True);second=db.add_item('Second','General','',1,red,admin=True)
            os.environ.update(DATABASE_URL=url,ALLOW_LOCAL_SQLITE='true')
            original=Store.photo;calls=[]
            def read(store,item_id,photo_version=None):calls.append(item_id);return original(store,item_id,photo_version)
            with patch.object(Store,'photo',read):
                app=AppTest.from_file(str(Path(__file__).parents[1]/'app.py'),default_timeout=20).run()
                self.assertEqual(len(app.exception),0);self.assertEqual(len(calls),2)
                app.run();self.assertEqual(len(calls),2)
                db.replace_photo(first['id'],blue,admin=True)
                next(b for b in app.button if b.label=='↻ Refresh').click().run()
                self.assertEqual(len(app.exception),0);self.assertEqual(calls.count(first['id']),2);self.assertEqual(calls.count(second['id']),1)
                # Cached bytes remain usable when PostgreSQL reads are unavailable.
                with patch.object(Store,'photo',side_effect=RuntimeError('offline')):
                    app.run();self.assertEqual(len(app.exception),0)
            # Upload seeding means the first display needs no database image read.
            seeded=AppTest.from_string('''import os
import streamlit as st
from media import cached_photo
st.write(len(cached_photo(os.environ['DATABASE_URL'],'seeded','content-hash',_uploaded=b'upload')))
st.write(len(cached_photo(os.environ['DATABASE_URL'],'seeded','content-hash')))
''').run()
            self.assertEqual(len(seeded.exception),0)
            self.assertEqual([m.value for m in seeded.markdown],['`6`','`6`'])

if __name__=='__main__':unittest.main()
