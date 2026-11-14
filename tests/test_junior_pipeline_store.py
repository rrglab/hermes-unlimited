import tempfile
import unittest
from pathlib import Path
from unlimited.junior_pipeline_store import source_key, sync_discovery
from unlimited.tool_to_agent_pipeline import build_pipeline

class JuniorPipelineStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=str(Path(self.tmp.name)/'test.sqlite')
        self.schemas=[{'name':'read_records','parameters':{'type':'object','properties':{}}}]
    def tearDown(self):self.tmp.cleanup()
    def scan(self,tenant='t1',schemas=None,provider='p1'):
        return sync_discovery(self.path,provider,tenant,'mcp:workspace',
            lambda previous:build_pipeline(tenant,'mcp',schemas or self.schemas,previous=previous))
    def test_version_diff_is_durable(self):
        first=self.scan()
        self.assertEqual(first['candidates'][0]['change'],'NEW')
        self.assertEqual(first['previous_count'],0)
        second=self.scan()
        self.assertEqual(second['candidates'][0]['change'],'UNCHANGED')
        self.assertEqual(second['previous_count'],1)
        changed=self.scan(schemas=[{**self.schemas[0],'description':'new version'}])
        self.assertEqual(changed['candidates'][0]['change'],'CHANGED')
        self.assertTrue(changed['revalidate'])
    def test_tenant_and_provider_isolation(self):
        self.scan(tenant='a',provider='one')
        self.assertEqual(self.scan(tenant='b',provider='one')['previous_count'],0)
        self.assertEqual(self.scan(tenant='a',provider='two')['previous_count'],0)
        self.assertEqual(self.scan(tenant='a',provider='one')['previous_count'],1)
    def test_no_credentials_and_no_forged_authority(self):
        with self.assertRaises(PermissionError):
            sync_discovery(self.path,'p','t','mcp:x',lambda prev:{'execution_authorized':True,'snapshot':{'x':'0'*64}})
        self.assertEqual(self.scan()['previous_count'],0)
    def test_source_requires_stable_namespace(self):
        self.assertEqual(source_key('hermes',toolset='file'),'hermes:file')
        self.assertEqual(source_key('connector',query='search Gmail'),'connector:search Gmail')
        for source in ('mcp','openapi'):
            with self.assertRaises(ValueError):source_key(source)
        with self.assertRaises(ValueError):source_key('mcp',namespace='../bad')

if __name__=='__main__':unittest.main()
