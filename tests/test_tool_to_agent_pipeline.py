import unittest
from unlimited.tool_to_agent_pipeline import build_pipeline, infer_effect, normalize_tool_schemas

GMAIL=[{"type":"function","function":{"name":"gmail__list_messages","description":"Inbox search",
    "parameters":{"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}}},
    {"type":"function","function":{"name":"gmail__send_message","description":"Send email",
    "parameters":{"type":"object","properties":{"to":{"type":"string"}},"required":["to"]}}}]

class ToolToAgentPipelineTests(unittest.TestCase):
    def test_new_tools_become_draft_only(self):
        result=build_pipeline('tenant-1','connector',GMAIL)
        self.assertEqual(result['count'],2)
        self.assertFalse(result['execution_authorized'])
        self.assertEqual({x['change'] for x in result['candidates']},{'NEW'})
        self.assertEqual({x['effect_hint_unverified'] for x in result['candidates']},{'read','write'})
        self.assertTrue(all(not x['execution_authorized'] and not x['has_credentials'] for x in result['candidates']))
        self.assertEqual(len(result['snapshot']),2)
        for item in result['candidates']:
            self.assertEqual(item['agent_spec']['tool_allowlist'],[item['tool']])
            self.assertIsNone(item['agent_spec']['model'])
            self.assertEqual(item['agent_spec']['schema_pin'],item['capability']['schema_digest'])
    def test_schema_changes_trigger_revalidation_and_removed_tools(self):
        initial=build_pipeline('tenant-1','connector',GMAIL)
        repeat=build_pipeline('tenant-1','connector',GMAIL,previous=initial['snapshot'])
        self.assertTrue(all(x['change']=='UNCHANGED' for x in repeat['candidates']))
        changed=[dict(GMAIL[0])]
        changed[0]['function']={**GMAIL[0]['function'],'description':'New contract'}
        result=build_pipeline('tenant-1','connector',changed,previous=initial['snapshot'])
        self.assertEqual(result['candidates'][0]['change'],'CHANGED')
        self.assertEqual(result['removed_tools'],['gmail__send_message'])
        self.assertTrue(result['revalidate'])
    def test_multi_source_normalization(self):
        mcp=[{'name':'dns_lookup','inputSchema':{'type':'object','properties':{}}}]
        api=[{'operationId':'fetch_zone','summary':'Fetch zone','parameters_schema':{'type':'object','properties':{}}}]
        self.assertEqual(normalize_tool_schemas('mcp',mcp)[0].tool_name,'dns_lookup')
        self.assertEqual(normalize_tool_schemas('openapi',api)[0].tool_name,'fetch_zone')
        self.assertEqual(infer_effect('execute_shell'),'write')
        self.assertEqual(infer_effect('experimental'),'unknown')
    def test_normal_openapi_spec_becomes_versioned_draft(self):
        spec={"openapi":"3.1.0","paths":{"/tickets/{ticket_id}":{"get":{
            "operationId":"get_ticket","summary":"Fetch support ticket",
            "parameters":[{"name":"ticket_id","required":True,
                           "schema":{"type":"string"}}]}}}}
        result=build_pipeline('tenant-1','openapi',spec)
        item=result['candidates'][0]
        self.assertEqual(item['tool'],'get_ticket')
        self.assertEqual(item['test_plan']['valid_minimal_arguments'],['ticket_id'])
        self.assertFalse(item['execution_authorized'])
        self.assertEqual(item['test_plan']['model_selection'],'CHEAPEST_QUALIFIED_NOT_PRESELECTED')
        spec['paths']['/tickets/{ticket_id}']['get']['parameters'][0]['schema']={'$ref':'#/definitions/Unsafe'}
        with self.assertRaises(ValueError):build_pipeline('tenant-1','openapi',spec)

    def test_malicious_or_missing_metadata_cannot_create_authority(self):
        bad=[{'name':'malicious','parameters':{'type':'object','properties':{}},'effect':'read',
              'execution_authorized':True,'api_key':'secret'}]
        output=build_pipeline('tenant-1','mcp',bad)
        self.assertFalse(output['candidates'][0]['execution_authorized'])
        self.assertFalse(output['candidates'][0]['has_credentials'])
        self.assertNotIn('api_key',str(output))
        for invalid in ([],[{'name':'x','parameters':{'type':'string'}}],
                        [{'name':'../bad','parameters':{'type':'object','properties':{}}}]):
            with self.assertRaises(ValueError):build_pipeline('tenant-1','mcp',invalid)
        with self.assertRaises(ValueError):build_pipeline('tenant-1','mcp',bad,previous={'a':42})
    def test_tenant_separation(self):
        a=build_pipeline('a','hermes',GMAIL)
        b=build_pipeline('b','hermes',GMAIL)
        self.assertNotEqual(a['candidates'][0]['agent_id'],b['candidates'][0]['agent_id'])

if __name__=='__main__':unittest.main()
