import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

for name in ('appdaemon', 'appdaemon.plugins', 'appdaemon.plugins.hass', 'appdaemon.plugins.hass.hassapi'):
    sys.modules[name] = types.ModuleType(name)
sys.modules['appdaemon.plugins.hass.hassapi'].Hass = object
spec = importlib.util.spec_from_file_location('archive', Path(__file__).parents[1] / 'appdaemon/fl_usage_archive.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = module.FamilyLinkUsageArchive()
        self.app.path = Path(self.tmp.name) / 'archive.json'
        self.app.data = {}
        self.app.time_zone = 'UTC'
        self.app.output = 'sensor.example_history'
        self.published = []
        self.app.set_state = lambda *args, **kwargs: self.published.append(kwargs)
    def tearDown(self):
        self.tmp.cleanup()
    def sample(self, total, minutes, date='2026-10-20T12:00:00+00:00', truncated=False):
        return {'state': str(total), 'last_updated': date, 'attributes': {'apps': [{'package':'example.app','name':'Example','minutes':minutes}], 'truncated':truncated}}
    def test_daily_max_and_restart_file(self):
        self.app.capture(self.sample(20,12))
        self.app.capture(self.sample(10,5))
        self.assertEqual(self.app.data['2026-10-20']['total'],20)
        self.assertEqual(self.app.data['2026-10-20']['apps']['example.app']['minutes'],12)
        import json
        self.assertEqual(json.loads(self.app.path.read_text()),self.app.data)
    def test_invalid_source_does_not_create_zero(self):
        self.app.capture({'state':'unavailable'})
        self.app.capture(self.sample('nan',2))
        self.assertFalse(self.app.data)
        self.assertFalse(self.app.path.exists())
    def test_truncated_is_preserved(self):
        self.app.capture(self.sample(20,12,truncated=True))
        self.assertTrue(self.published[-1]['attributes']['samples'][0]['attributes']['truncated'])
    def test_retention(self):
        from datetime import datetime, timedelta, timezone
        for i in range(100):
            stamp=(datetime(2026,1,1,tzinfo=timezone.utc)+timedelta(days=i)).isoformat()
            self.app.capture(self.sample(20,12,stamp))
        self.assertEqual(len(self.app.data),90)
        self.assertEqual(len(self.published[-1]['attributes']['samples']),7)

if __name__ == '__main__': unittest.main()
