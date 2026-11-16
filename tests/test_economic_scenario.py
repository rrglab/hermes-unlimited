import unittest
from unlimited.economic_scenario import _scenario_amount, evaluate_cost_scenario
from unlimited.runtime import ProviderStore
from unlimited.oversight_ledger import OversightLedger
from tempfile import TemporaryDirectory
from pathlib import Path

class EconomicScenarioTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.store=ProviderStore(Path(self.temp.name)/'c.sqlite',
            lambda p,t,i: (p,t,i)==('owner','tenant-a','identity'))
        self.store.create_company('owner','tenant-a','company','C','identity')
        self.store.publish_service('owner','tenant-a','company','service','S',100,'EUR','identity')
        self.store.request_service('owner','tenant-a','company','req','service',{},'identity')
        self.ledger=OversightLedger(self.store)
    def tearDown(self): self.temp.cleanup()
    def scenario(self, cap):
        return evaluate_cost_scenario(self.ledger,'owner','tenant-a','company','req','identity',scenario_cap=cap)
    def test_no_cost_is_not_green(self):
        result=self.scenario('0')
        self.assertEqual(result['comparison'],'INSUFFICIENT_COST_INPUT')
        self.assertIsNone(result['within_scenario_cap'])
        self.assertIsNone(result['net_value'])
    def test_scenario_math_without_approval(self):
        self.ledger.record_costs('owner','tenant-a','company','req','11','2','identity')
        self.ledger.record('owner','tenant-a','company','req','entry','pre_control','30','60','identity')
        over=self.scenario('42')
        self.assertEqual(over['estimated_cost'],'43')
        self.assertEqual(over['difference'],'-1')
        self.assertEqual(over['comparison'],'MODEL_INPUT_OVER_CAP')
        self.assertEqual(over['currency'],'EUR')
        self.assertFalse(over['execution_authorized'])
        self.assertFalse(over['independently_verified'])
        self.assertIsNone(over['roi'])
        self.assertEqual(self.scenario('43')['comparison'],'MODEL_INPUT_WITHIN_CAP')
    def test_bad_caps_and_nan_fail_closed(self):
        for value in ('-1','NaN','Infinity','1e200','abc','', '9'*45):
            with self.subTest(value=value),self.assertRaises(ValueError): self.scenario(value)
        for value in (None,3.14,42,True):
            with self.subTest(value=value),self.assertRaises(ValueError):_scenario_amount(value)
    def test_cross_tenant_identity_never_leaks(self):
        with self.assertRaises(PermissionError):
            evaluate_cost_scenario(self.ledger,'owner','tenant-a','company','req','impostor',scenario_cap='4')
        with self.assertRaises(PermissionError):
            evaluate_cost_scenario(self.ledger,'owner','tenant-b','company','req','identity',scenario_cap='4')
        with self.assertRaises(ValueError):
            evaluate_cost_scenario(self.ledger,'owner','tenant-a','company','absent','identity',scenario_cap='4')

if __name__=='__main__':unittest.main()
