"""Signed HTTP reporting must stay scoped to active CRM assignments."""
import unittest

from tests import test_crm_sync_http_worker3 as h
from tests import test_registration as users


class ParticipantTasks(h.CRMSyncHTTP):
    def test_task_history_is_scoped_and_actions_are_unconfirmed(self):
        self.assertEqual(self.register(users.ALICE,self.owner_invite())[0],200)
        self.assertEqual(self.register(users.BOB,self.owner_invite())[0],200)
        self.assertEqual(self.as_user('/api/admin/decision',users.OWNER,user_id=users.ALICE,decision='approve')[0],200)
        self.assertEqual(self.event({'event_id':'task-bind','type':'lead.bound','crm_lead_id':'crm:task','telegram_id':users.ALICE})[0],200)
        self.assertEqual(self.event({'event_id':'task-offers','type':'offers.assigned','crm_lead_id':'crm:task','offers':[{'id':'offer-1','name':'Заявка','instructions':'Выполните шаги'}]})[0],200)
        self.assertEqual(self.as_user('/api/tasks',users.ALICE)[1]['tasks'][0]['id'],'offer-1')
        self.assertEqual(self.as_user('/api/tasks',users.BOB)[1],{'tasks':[],'history':[]})
        self.assertEqual(self.as_user('/api/tasks/report',users.BOB,offer_id='offer-1',action='submitted')[0],403)
        self.assertEqual(self.as_user('/api/tasks/report',users.ALICE,offer_id='other',action='submitted')[0],403)
        self.assertEqual(self.as_user('/api/tasks/report',users.ALICE,offer_id='offer-1',action='paid')[0],400)
        status, result = self.as_user('/api/tasks/report',users.ALICE,offer_id='offer-1',action='submitted',note='Заявка заполнена')
        self.assertEqual(status,200)
        self.assertEqual(result['status'],'reported')
        self.assertEqual(self.as_user('/api/tasks',users.ALICE)[1]['history'][0]['action'],'submitted')
        self.assertNotIn('paid',str(self.as_user('/api/tasks',users.ALICE)[1]['history']))
        self.assertEqual(self.as_user('/api/tasks',users.BOB)[1]['history'],[])


if __name__ == '__main__':
    unittest.main()
