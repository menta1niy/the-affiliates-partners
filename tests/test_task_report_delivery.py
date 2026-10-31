"""Task report durability, signed delivery, retry and financial-stage isolation."""
import json
import os
import sqlite3
import time
import unittest
from contextlib import closing
from unittest.mock import patch
from uuid import uuid4

from server import integration, task_report_delivery
from tests import test_participant_tasks as base
from tests import test_registration as users


class TaskReportDelivery(base.ParticipantTasks):
    def test_signed_retry_idempotent_report_id(self):
        lead, offer = str(uuid4()), str(uuid4())
        self.assertEqual(self.register(users.ALICE,self.owner_invite())[0],200)
        self.assertEqual(self.as_user('/api/admin/decision',users.OWNER,user_id=users.ALICE,decision='approve')[0],200)
        self.assertEqual(self.event({'event_id':'task-delivery-bind','type':'lead.bound','crm_lead_id':lead,'telegram_id':users.ALICE})[0],200)
        self.assertEqual(self.event({'event_id':'task-delivery-offers','type':'offers.assigned','crm_lead_id':lead,'offers':[{'id':offer,'title':'Task'}]})[0],200)
        status, report = self.as_user('/api/tasks/report',users.ALICE,offer_id=offer,action='submitted',note='Sent')
        self.assertEqual(status,200)
        calls = []
        def sender(event,url):
            calls.append((event,url))
            if len(calls)==1: raise OSError('transient')
        with patch('server.task_report_delivery.endpoint',return_value='https://example.invalid/task-reports'):
            self.assertEqual(task_report_delivery.dispatch_once(sender=sender,now=10000000000)['failed'],1)
            self.assertEqual(task_report_delivery.dispatch_once(sender=sender,now=10000000100)['delivered'],1)
            self.assertEqual(task_report_delivery.dispatch_once(sender=sender,now=10000000200)['claimed'],0)
        event,url = calls[1]
        self.assertEqual(event['report_id'],report['report_id'])
        self.assertEqual(event['event_id'],'participant-task:'+report['report_id'])
        self.assertEqual(event['crm_lead_id'],lead)
        self.assertEqual(event['offer_id'],offer)
        self.assertNotIn('stage',event)
        self.assertNotIn('paid',event)
        self.assertEqual(self.as_user('/api/tasks',users.ALICE)[1]['history'][0]['action'],'submitted')
        with closing(sqlite3.connect(self.db_path)) as conn:
            row=conn.execute('SELECT delivered_at,attempts FROM participant_task_report_outbox WHERE report_id=?',(report['report_id'],)).fetchone()
        self.assertEqual(row,(10000000100,2))

    def test_hmac_headers_match_event_body(self):
        event={'event_id':'participant-task:abc','type':'participant.task.reported',
               'report_id':str(uuid4()),'crm_lead_id':str(uuid4()),'telegram_id':123456,
               'offer_id':str(uuid4()),'action':'submitted','note':'test','created_at':12345}
        seen=[]
        class Response:
            status=200
            def __enter__(self):return self
            def __exit__(self,*args):return False
            def read(self,*args):return b'{"ok":true}'
        def opener(req,timeout):
            raw=req.data
            stamp=req.get_header('X-ta-timestamp')
            sig=req.get_header('X-ta-signature')
            self.assertEqual(integration.signature(raw,int(stamp),'x'*40),sig)
            self.assertEqual(req.get_header('X-ta-event-id'),event['event_id'])
            seen.append(json.loads(raw))
            return Response()
        with patch.dict(os.environ,{'PARTNERS_CRM_SHARED_SECRET':'x'*40}):
            task_report_delivery.submit(event,'https://example.invalid',opener=opener,now=12345)
        self.assertEqual(seen,[{key:event[key] for key in ('report_id','crm_lead_id','offer_id','action','note')} |
                               {'created_at':'1970-01-01T03:25:45+00:00'}])


if __name__=='__main__': unittest.main()
