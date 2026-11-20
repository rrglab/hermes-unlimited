import pathlib
import tempfile
import unittest

from unlimited.memory_recall import recall_existing
from unlimited.runtime import ProviderStore, UnverifiedIdentity


class MemoryRecallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = pathlib.Path(self.tmp.name) / "memory.sqlite"
        self.store = ProviderStore(self.db, lambda provider, tenant, identity:
                                   (provider, tenant, identity) == ("owner", "tenant-a", "@owner"))
        with self.store._db() as db:
            db.execute("""CREATE TABLE company_memory (
                entry_id TEXT PRIMARY KEY, provider TEXT, tenant TEXT, company TEXT,
                task_kind TEXT, source_id TEXT, classification TEXT, independently_verified INTEGER,
                lesson TEXT, evidence_digest TEXT, cost_minor REAL, verified_value_minor INTEGER,
                created_at INTEGER)""")
            for id, tenant, state, ver in (("a", "tenant-a", "RECORDED_UNVERIFIED", 0),
                                            ("b", "tenant-a", "VERIFIED_OUTCOME", 1),
                                            ("c", "tenant-b", "VERIFIED_OUTCOME", 1)):
                db.execute("INSERT INTO company_memory VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (id,"owner",tenant,"company","triage","task",state,ver,"memo",None,0,0,1))
    def tearDown(self): self.tmp.cleanup()
    def recall(self, **kwargs):
        return recall_existing(self.store,"owner","tenant-a","company","@owner",**kwargs)
    def test_tenant_isolation_and_no_attestation(self):
        result=self.recall()
        self.assertEqual({x['entry_id'] for x in result['entries']},{'a','b'})
        self.assertFalse(result['attestation_verified'])
        self.assertTrue(all(not x['independent_attestation_checked'] for x in result['entries']))
    def test_verified_only_is_stored_label_filter_not_attestation(self):
        result=self.recall(verified_only=True)
        self.assertEqual([x['entry_id'] for x in result['entries']],['b'])
        self.assertFalse(result['attestation_verified'])
    def test_negative_authorization(self):
        with self.assertRaises(UnverifiedIdentity):
            recall_existing(self.store,"owner","tenant-b","company","@owner")
        with self.assertRaises(ValueError): self.recall(task_kind="../secret")
        with self.assertRaises(ValueError): self.recall(limit=True)
        with self.assertRaises(ValueError): self.recall(limit=51)
        with self.assertRaises(ValueError): self.recall(verified_only="false")
        with self.assertRaises(ValueError):
            recall_existing(self.store,"owner","tenant-a","../company","@owner")
    def test_missing_table_is_unavailable_not_fabricated(self):
        with self.store._db() as db: db.execute("DROP TABLE company_memory")
        result=self.recall()
        self.assertEqual(result['entries'],[])
        self.assertFalse(result['memory_available'])
    def test_does_not_insert_or_change_existing_rows(self):
        with self.store._db() as db:
            before=db.execute('SELECT * FROM company_memory ORDER BY entry_id').fetchall()
        self.recall(task_kind='triage',limit=1)
        with self.store._db() as db:
            after=db.execute('SELECT * FROM company_memory ORDER BY entry_id').fetchall()
        self.assertEqual(before,after)

if __name__ == '__main__':unittest.main()
