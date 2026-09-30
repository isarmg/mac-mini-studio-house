"""Release safeguards: drift, rollback and path containment."""
import tempfile,unittest
from pathlib import Path
from exact_publish import FileTransaction
from migrate_exact_delivery import ROOT

class PublicationTests(unittest.TestCase):
    def setUp(self):
        folder=ROOT/'.tmp/exact-publication-tests';folder.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=folder);self.root=Path(self.temp.name)
        self.source=self.root/'stage.txt';self.source.write_text('new',encoding='utf-8')
        self.target=self.root/'final.txt';self.target.write_text('old',encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def tx(self):
        tx=FileTransaction(self.root,self.root/'release');tx.add(self.source,self.target);return tx
    def test_commit_and_byte_for_byte_rollback(self):
        tx=self.tx();tx.commit();self.assertEqual(self.target.read_text(),'new');tx.rollback();self.assertEqual(self.target.read_text(),'old')
    def test_staged_drift_does_not_replace_final(self):
        tx=self.tx();self.source.write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):tx.commit()
        self.assertEqual(self.target.read_text(),'old')
    def test_later_user_edit_is_never_overwritten_by_rollback(self):
        tx=self.tx();tx.commit();self.target.write_text('user edit',encoding='utf-8')
        with self.assertRaises(ValueError):tx.rollback()
        self.assertEqual(self.target.read_text(),'user edit')
    def test_target_must_stay_in_workspace(self):
        tx=FileTransaction(self.root,self.root/'release')
        with self.assertRaises(ValueError):tx.add(self.source,self.root.parent/'outside.txt')
    def test_rollback_removes_only_newly_created_file(self):
        self.target.unlink();tx=self.tx();tx.commit();tx.rollback();self.assertFalse(self.target.exists())

if __name__=='__main__':unittest.main()
