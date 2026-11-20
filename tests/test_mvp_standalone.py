"""MVP works without CRM workspace, including signed HTTP and tenant RBAC."""
import base64
import io
import os
import sqlite3
import unittest
from urllib.error import HTTPError
from urllib.request import urlopen
from unittest.mock import patch
from PIL import Image

from server import db
from tests.test_registration import HttpHarness, OWNER, ALICE, BOB, init_data


class StandaloneMvpTests(HttpHarness):
    def setUp(self):
        super().setUp()
        self.patch_open = patch.dict(os.environ, {"PARTNERS_MVP_OPEN_REGISTRATION": "true"})
        self.patch_open.start()
        self.addCleanup(self.patch_open.stop)

    def create_offer(self, **changes):
        payload={"name":"Карта Test", "category":"Дебетовые карты",
                 "target_action":"Оформить и активировать", "payout_rub":700,
                 "hold_days":14, "instructions":"Оформите карту",
                 "referral_url":"https://bank.example.test/apply"}
        payload.update(changes)
        status, result = self.as_user('/api/admin/mvp/offer', OWNER, **payload)
        self.assertEqual(status, 200, result)
        return result['offer_id']

    def register_open_user(self, uid=ALICE):
        status, session = self.as_user('/api/session', uid)
        self.assertEqual(status, 200)
        self.assertTrue(session['open_registration'])
        status, user = self.as_user('/api/register', uid, consent=True)
        self.assertEqual(status, 200, user)
        self.assertEqual(user['status'], 'pending')
        self.assertEqual(self.as_user('/api/admin/decision', OWNER, user_id=uid, decision='approve')[0],200)

    def test_owner_creates_assigns_updates_and_lead_sees_only_own_offers(self):
        self.register_open_user(ALICE)
        self.register_open_user(BOB)
        offer = self.create_offer()
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,
            user_id=ALICE, offer_id=offer, stage='in_progress', note='Начал оформление')[0], 200)
        status, view = self.as_user('/api/mvp/overview', ALICE)
        self.assertEqual(status, 200)
        self.assertEqual(view['statistics']['in_progress'], 1)
        self.assertEqual(view['offers'][0]['payout_rub'], 700)
        self.assertEqual(view['offers'][0]['hold_days'], 14)
        self.assertEqual(view['offers'][0]['category'], 'Дебетовые карты')
        self.assertEqual(self.as_user('/api/mvp/overview', BOB)[1]['offers'], [])
        self.assertEqual(self.as_user('/api/admin/mvp/catalog', ALICE)[0], 403)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', ALICE,user_id=BOB,offer_id=offer)[0],403)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='completed',note='Проверено администратором')[0],200)
        self.assertEqual(self.as_user('/api/mvp/overview', ALICE)[1]['statistics']['completed'],1)
        self.assertEqual(self.as_user('/api/admin/participant',OWNER,user_id=ALICE)[1]['manual']['offers'][0]['stage'],'completed')
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,enabled=False,note='')[0],200)
        self.assertEqual(self.as_user('/api/mvp/overview', ALICE)[1]['offers'], [])

    def test_open_registration_requires_signed_initdata_and_consent(self):
        self.assertEqual(self.post('/api/register',{'initData':'invalid','consent':True})[0],401)
        self.assertEqual(self.as_user('/api/register',ALICE,consent=False)[0],400)
        self.assertEqual(self.as_user('/api/mvp/overview',ALICE)[1]['offers'],[])
        self.assertEqual(self.as_user('/api/register',ALICE,consent=True)[0],200)
        with db.transaction() as conn:
            user=db.get_user(conn, ALICE)
            self.assertEqual(user['agency_id'],OWNER)
            self.assertEqual(user['source'],None)
            self.assertEqual(conn.execute('SELECT count(*) FROM crm_registration_outbox').fetchone()[0],0)

    def test_offer_input_validation_and_tenant_isolation(self):
        offer=self.create_offer()
        for data in ({'payout_rub':-1},{'hold_days':366},{'name':''},
                     {'referral_url':'https://login:secret@bank.test/'},
                     {'referral_url':'javascript:alert(1)'},{'referral_url':'https://bank.test\\evil'}):
            with self.subTest(data=data):
                payload={'name':'Card','category':'Card','target_action':'Do',
                         'payout_rub':10,'hold_days':0,**data}
                self.assertEqual(self.as_user('/api/admin/mvp/offer',OWNER,**payload)[0],400)
        self.register_open_user(ALICE)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='paid',note='')[0],400)
        self.assertEqual(self.as_user('/api/admin/mvp/assignment', OWNER,user_id=ALICE,offer_id=offer,stage='assigned',note='')[0],200)

    def test_malformed_assignment_stage_is_client_error_not_server_failure(self):
        self.register_open_user(ALICE)
        offer = self.create_offer()
        for malformed in ([], {}, None, 10):
            with self.subTest(stage=malformed):
                status, response = self.as_user('/api/admin/mvp/assignment', OWNER,
                    user_id=ALICE, offer_id=offer, stage=malformed)
                self.assertEqual(status, 400, response)

    def test_logo_and_category_stages_round_trip(self):
        image=Image.new("RGBA", (240, 140), (255, 120, 40, 150))
        buffer=io.BytesIO();image.save(buffer,format="PNG")
        logo="data:image/png;base64,"+base64.b64encode(buffer.getvalue()).decode("ascii")
        offer=self.create_offer(category="Бизнес-счета",logo_data=logo)
        status,result=self.as_user("/api/admin/mvp/catalog",OWNER)
        self.assertEqual(status,200)
        saved=next(item for item in result["offers"] if item["id"]==offer)
        self.assertEqual(saved["lead_stages"],["application_sent","meeting_scheduled","product_received"])
        self.assertRegex(saved["logo_url"],r"^/partners/api/offer-logo/[0-9a-f]{64}$")
        with urlopen(self.base+saved["logo_url"].replace("/partners/api/","/api/"),timeout=6) as response:
            self.assertEqual(response.status,200)
            self.assertEqual(response.headers["Content-Type"],"image/webp")
            self.assertEqual(Image.open(io.BytesIO(response.read())).format,"WEBP")
        self.register_open_user()
        self.assertEqual(self.as_user("/api/admin/mvp/assignment",OWNER,user_id=ALICE,offer_id=offer)[0],200)
        view=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertEqual(view["logo_url"],saved["logo_url"])
        self.assertEqual(view["lead_stages"],saved["lead_stages"])

        edited={"name":"Бизнес-счёт обновлён","category":"Бизнес-счета",
                "target_action":"Открыть счёт","payout_rub":900,"hold_days":9,
                "offer_id":offer,"lead_stages":["application_sent","account_opened"]}
        self.assertEqual(self.as_user("/api/admin/mvp/offer",OWNER,**edited)[0],200)
        view=self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]
        self.assertEqual(view["lead_stages"],["application_sent","account_opened"])
        self.assertEqual(view["logo_url"],saved["logo_url"])
        self.assertEqual(self.as_user("/api/admin/mvp/offer",OWNER,**edited,remove_logo=True)[0],200)
        self.assertEqual(self.as_user("/api/mvp/overview",ALICE)[1]["offers"][0]["logo_url"],"")

    def test_logo_upload_rejects_invalid_payload_and_preserves_old_offer(self):
        offer=self.create_offer()
        base={"name":"Проверка","category":"МФО","target_action":"Заявка",
              "payout_rub":100,"hold_days":0,"offer_id":offer}
        for changes in (
            {"lead_stages":[]},
            {"lead_stages":["application_sent","application_sent"]},
            {"lead_stages":["credited"]},
            {"logo_data":"data:image/svg+xml;base64,PHN2Zz4="},
            {"logo_data":"data:image/png;base64,YWJjZA=="},
            {"logo_data":3},
            {"remove_logo":True,"logo_data":"data:image/png;base64,QQ=="},
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.as_user("/api/admin/mvp/offer",OWNER,**{**base,**changes})[0],400)
        self.assertEqual(self.as_user("/api/admin/mvp/offer",ALICE,**base)[0],403)
        status,response=self.as_user("/api/admin/mvp/catalog",OWNER)
        self.assertEqual(status,200)
        current=next(item for item in response["offers"] if item["id"]==offer)
        self.assertEqual(current["name"],"Карта Test")

    def test_sqlite_legacy_catalog_columns_are_migrated_in_place(self):
        from server import mvp
        db.initialize()
        with db.transaction() as conn:
            conn.execute("""CREATE TABLE manual_offers (
                id TEXT PRIMARY KEY,name TEXT NOT NULL,category TEXT NOT NULL,
                target_action TEXT NOT NULL,payout_rub INTEGER NOT NULL,
                hold_days INTEGER NOT NULL,instructions TEXT NOT NULL DEFAULT '',
                referral_url TEXT NOT NULL DEFAULT '',active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)""")
            conn.execute("INSERT INTO manual_offers(id,name,category,target_action,payout_rub,hold_days,created_at,updated_at) VALUES('manual_12345678901234567890','Старый оффер','Дебетовые карты','Оформить',200,0,1,1)")
        with db.transaction() as conn:
            mvp.schema(conn)
            record=conn.execute("SELECT logo_hash,lead_stages FROM manual_offers").fetchone()
            self.assertEqual(record["logo_hash"],"")
            self.assertEqual(record["lead_stages"],'["application_sent","meeting_scheduled","product_received"]')


if __name__=='__main__':
    unittest.main()
