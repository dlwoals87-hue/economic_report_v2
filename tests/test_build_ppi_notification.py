from __future__ import annotations
import unittest
from scripts.automation import build_ppi_notification as notify
class PpiNotificationTests(unittest.TestCase):
 def test_skip_success_failure(self):
  self.assertEqual(notify.build_notification({'status':'NO_PENDING_PPI_EVENT'})['status'],'NOTIFICATION_SKIPPED')
  success=notify.build_notification({'status':'PROCESSED_AND_INDEXED','event_id':'US_PPI_2026_05','cost_mode':'free'}); self.assertEqual(success['category'],'success'); self.assertIn('ppi-processing:US_PPI_2026_05:success',success['body'])
  self.assertEqual(notify.build_notification({'status':'PPI_PROCESSING_CONFLICT','event_id':'US_PPI_2026_05'})['category'],'failure')
 def test_issue_create_update_and_duplicate(self):
  n=notify.build_notification({'status':'PROCESSED_AND_INDEXED','event_id':'US_PPI_2026_05'})
  self.assertEqual(notify.decide_issue_action(n,[])['notification_action'],'created')
  marker='<!-- automation-key: ppi-processing:US_PPI_2026_05:success -->'
  self.assertEqual(notify.decide_issue_action(n,[{'number':7,'body':marker+'\nold'}])['notification_action'],'updated')
  self.assertEqual(notify.decide_issue_action(n,[{'body':marker},{'body':marker}])['status'],'DUPLICATE_ISSUE_CONFLICT')
