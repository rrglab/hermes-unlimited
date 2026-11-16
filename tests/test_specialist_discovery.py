import unittest
from unlimited.specialist_discovery import inspect_host_registry

class HostRegistry:
    def __init__(self): self.queries=[]
    def get_all_tool_names(self): return ['dns_read','dns_write','other','unlimited_specialist_factory']
    def get_toolset_for_tool(self, name): return 'dns' if name.startswith('dns_') else 'other'
    def get_definitions(self, names, quiet=False):
        self.queries.append((names,quiet))
        return [{"function":{"name": n,"parameters":{"type":"object","properties":{}}}} for n in sorted(names)]

class SpecialistDiscoveryTests(unittest.TestCase):
    def test_discovery_never_claims_authority(self):
        host=HostRegistry()
        result=inspect_host_registry(host,toolset='dns',operation='discover')
        self.assertEqual([x['name'] for x in result['capabilities']],['dns_read','dns_write'])
        self.assertEqual(result['authority'],'NONE')
        self.assertFalse(result['execution_authorized'])
        self.assertTrue(all(x['effect']=='unknown' and not x['availability_verified'] for x in result['capabilities']))
        self.assertEqual(host.queries[0][0],{'dns_read','dns_write'})
    def test_proposal_is_unverified_and_cannot_invent_tools(self):
        proposal=inspect_host_registry(HostRegistry(),toolset='dns',operation='propose',
                                       objective='Assess DNS', selected_tools=['dns_write'])
        self.assertEqual(proposal['status'],'DRAFT_UNVERIFIED')
        self.assertFalse(proposal['execution_authorized'])
        self.assertFalse(proposal['effects_reviewed'])
        with self.assertRaises(ValueError):
            inspect_host_registry(HostRegistry(),toolset='dns',operation='propose',
                                  objective='Run tool', selected_tools=['host.admin'])
    def test_missing_host_rejects_fail_closed(self):
        with self.assertRaises(PermissionError):
            inspect_host_registry(None,toolset='dns',operation='discover')
        with self.assertRaises(PermissionError):
            inspect_host_registry(object(),toolset='dns',operation='discover')
    def test_model_payload_cannot_override_host_registry(self):
        with self.assertRaises(TypeError):
            inspect_host_registry(HostRegistry(),toolset='dns',operation='discover',
                                  registry={'forged':'tool'})
        with self.assertRaises(ValueError):
            inspect_host_registry(HostRegistry(),toolset='../../secret',operation='discover')
        with self.assertRaises(ValueError):
            inspect_host_registry(HostRegistry(),toolset='dns',operation='propose',
                                  objective='Do',selected_tools=['dns_read','dns_read'])
        with self.assertRaises(ValueError):
            inspect_host_registry(HostRegistry(),toolset='dns',operation='discover',objective='Do')
    def test_local_declarations_cannot_claim_host_availability(self):
        from unlimited.specialist_discovery import LocalPluginDeclarations
        registry = LocalPluginDeclarations(({"name":"sample", "parameters":{"type":"object","properties":{}}},))
        local = inspect_host_registry(registry,toolset='hermes_unlimited',operation='discover',
                                      source='LOCAL_PLUGIN_DECLARATION_ONLY')
        self.assertEqual(local['source'],'LOCAL_PLUGIN_DECLARATION_ONLY')
        self.assertFalse(local['execution_authorized'])
        self.assertFalse(local['capabilities'][0]['availability_verified'])
        with self.assertRaises(ValueError):
            LocalPluginDeclarations(({"name":"x"},{"name":"x"}))
        with self.assertRaises(ValueError):
            inspect_host_registry(registry,toolset='hermes_unlimited',operation='discover',
                                  source='VERIFIED_AND_AUTHORIZED')

    def test_host_definition_spoof_fails_closed(self):
        class Forged(HostRegistry):
            def get_definitions(self, names, quiet=False):
                return [{'function':{'name':'malicious','parameters':{'type':'object'}}}]
        with self.assertRaises(ValueError):
            inspect_host_registry(Forged(),toolset='dns',operation='discover')

if __name__=='__main__':unittest.main()
