import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"server"))
import app
from crm_snapshot import begin, batch, finalize

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch=patch.object(app,"DB",Path(self.tmp.name)/"snapshot.sqlite3")
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def rows(self,n):
        return [("crm-"+str(uuid4()),"Offer "+str(i),"БАНКИ","Card",True) for i in range(n)]

    def commit(self,conn,workspace,run,rows,now=1000):
        for i in range(0,len(rows),80):
            batch(conn,workspace,run,rows[i:i+80],now)
        ordered=sorted(rows)
        digest=hashlib.sha256("\n".join(json.dumps(list(row),ensure_ascii=False) for row in ordered).encode()).hexdigest()
        return finalize(conn,workspace,run,digest,now)

    def test_450_rows_atomic_replay_and_partial_failure(self):
        workspace=str(uuid4())
        with app.db() as conn:
            run=str(uuid4()); entries=self.rows(450)
            self.assertEqual(begin(conn,workspace,run,450,1000),"pending")
            batch(conn,workspace,run,entries[:80],1000)
            with self.assertRaises(ValueError):
                finalize(conn,workspace,run,"0"*64,1000)
            self.assertEqual(conn.execute("SELECT count(*) FROM offers").fetchone()[0],0)
            self.assertEqual(self.commit(conn,workspace,run,entries),0)
            self.assertEqual(conn.execute("SELECT count(*) FROM offers").fetchone()[0],450)
            self.assertEqual(begin(conn,workspace,run,450,1000),"complete")
            digest=hashlib.sha256("\n".join(json.dumps(list(row),ensure_ascii=False) for row in sorted(entries)).encode()).hexdigest()
            self.assertEqual(finalize(conn,workspace,run,digest,1000),0)

    def test_old_run_cannot_override_newer_completed_run(self):
        workspace=str(uuid4())
        with app.db() as conn:
            older,newer=str(uuid4()),str(uuid4())
            a,b=self.rows(1),self.rows(1)
            begin(conn,workspace,older,1,1000)
            begin(conn,workspace,newer,1,1000)
            self.commit(conn,workspace,newer,b,1000)
            with self.assertRaisesRegex(ValueError,"Stale"):
                self.commit(conn,workspace,older,a,1000)
            self.assertEqual(conn.execute("SELECT count(*) FROM offers").fetchone()[0],1)

    def test_expiration_does_not_change_existing_offers(self):
        workspace=str(uuid4())
        with app.db() as conn:
            run=str(uuid4())
            begin(conn,workspace,run,1,1000)
            with self.assertRaises(ValueError):
                batch(conn,workspace,run,self.rows(1),1000+3601)
            self.assertEqual(conn.execute("SELECT count(*) FROM offers").fetchone()[0],0)
