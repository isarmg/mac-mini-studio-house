"""Release safeguards: drift, rollback and path containment."""
import tempfile,unittest
from unittest.mock import patch
from pathlib import Path
from exact_publish import FileTransaction
from migrate_exact_delivery import ROOT
from exact_candidates import published_component

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

class AssemblyReuseTests(unittest.TestCase):
    def row(self):return {'key':'component','published':True,'source':Path('part.brep'),'packet':ROOT/'canonical.json'}
    def test_only_native_accepted_published_component_can_be_reused(self):
        with patch('exact_candidates.accepted',return_value=True) as accepted,patch('exact_candidates.sha',return_value='bound-hash'):
            result=published_component(self.row())
        self.assertEqual(accepted.call_count,3)
        self.assertTrue(result['preserved_published_component'])
        self.assertEqual(result['source_sha256'],'bound-hash')
        self.assertIsNone(result['revision'])
    def test_damaged_or_unpublished_component_is_rejected(self):
        with patch('exact_candidates.accepted',return_value=False):
            with self.assertRaises(ValueError):published_component(self.row())
        row=self.row();row['published']=False
        with self.assertRaises(ValueError):published_component(row)

if __name__=='__main__':unittest.main()
