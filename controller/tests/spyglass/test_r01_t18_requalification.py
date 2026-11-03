"""The narrow requalification cannot bypass functional or source failures."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts'))
from requalify_r01_t18 import compatible_makefile, compatible_inventory, completed_root, PDS_TARGET, PDS_HELP


class RequalificationBoundary(unittest.TestCase):
    def setUp(self):
        self.before = 'PYTHON := locked\nsmoke:\n\t$(PYTHON) scripts/run_smoke.py\n\ntest:\n\t$(PYTHON) tests.py\n\nhelp:\n\t@echo help\n'
        self.after = self.before.replace('\t$(PYTHON) scripts/run_smoke.py\n', '\t$(PYTHON) scripts/run_smoke.py\n'+PDS_TARGET).replace('\nhelp:\n', '\nhelp:\n'+PDS_HELP)

    def test_precise_unrelated_addition_accepted(self):
        compatible_makefile(self.before, self.after)
        compatible_inventory({'Makefile': 'before', 'rtl': 'locked'}, {'Makefile': 'after', 'rtl': 'locked'})

    def test_test_recipe_or_global_change_rejected(self):
        for modified in (self.after.replace('tests.py', 'other.py'), self.after.replace('locked', 'unlocked')):
            with self.assertRaisesRegex(ValueError, 'extends beyond'):
                compatible_makefile(self.before, modified)

    def test_rtl_change_or_missing_source_rejected(self):
        for current in ({'Makefile': 'after', 'rtl': 'changed'}, {'Makefile': 'after'}):
            with self.assertRaisesRegex(ValueError, 'only the precise'):
                compatible_inventory({'Makefile': 'before', 'rtl': 'locked'}, current)

    def test_functional_failure_rejected(self):
        manifest = dict(task_id='T18', run_id='r01-resume-v1', status='FAIL', exit_code=1)
        source_failure = dict(name='source-unchanged', status='FAIL')
        completed_root(manifest, [dict(status='PASS')], [source_failure], '1')
        for commands, checks in (([dict(status='FAIL')], [source_failure]),
                                 ([dict(status='PASS')], [source_failure, dict(name='negative-empty', status='FAIL')])):
            with self.assertRaisesRegex(ValueError, 'only terminal'):
                completed_root(manifest, commands, checks, '1')


if __name__ == '__main__':
    unittest.main()
