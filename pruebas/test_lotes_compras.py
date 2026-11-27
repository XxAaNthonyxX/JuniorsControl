from unittest import TestCase
from unittest.mock import Mock, patch

import gestion
from test_atencion_v4 import ADMIN, Cursor


DAY="2026-11-27"
CAJA={"id":9,"role":"caja","name":"Caja"}
PURCHASE={"id":2,"status":"Enviada","purchase_day":DAY,"version":2,"supplier":"Proveedor","assignee_id":None}


class TestLotesCompras(TestCase):
    def test_midnight_blocks_edit_and_dispatch_of_a_prior_day(self):
        with patch.object(gestion.inv,"today",return_value="2026-11-28"):
            db=Mock()
            db.execute.return_value.fetchone.return_value=PURCHASE
            with self.assertRaisesRegex(ValueError,"00:00"):
                gestion._edit_purchase(db,ADMIN,{"id":2})
            with self.assertRaisesRegex(ValueError,"00:00"):
                gestion._send_purchase_list(db,ADMIN,{"day":DAY,"orders":[{"id":2,"version":2}]})
            db.execute.assert_called_once()

    def test_send_list_requires_current_versions_and_includes_draft_and_approved(self):
        db=Mock()
        db.execute.return_value=Cursor(rows=[dict(PURCHASE,status="Borrador"),dict(PURCHASE,id=3,status="Aprobada")])
        orders=[{"id":2,"version":2},{"id":3,"version":2}]
        with (
            patch.object(gestion.inv,"today",return_value=DAY),
            patch.object(gestion,"_dispatch_purchase") as dispatch,
        ):
            self.assertEqual(gestion._send_purchase_list(db,ADMIN,{"day":DAY,"orders":orders}),{"day":DAY,"sent":2})
            self.assertEqual([c.args[2]["id"] for c in dispatch.call_args_list],[2,3])
            dispatch.reset_mock()
            with self.assertRaisesRegex(ValueError,"lista del día cambió"):
                gestion._send_purchase_list(db,ADMIN,{"day":DAY,"orders":[dict(orders[0],version=1),orders[1]]})
            dispatch.assert_not_called()

    def test_edit_received_purchase_adds_only_extra_quantity_to_reception(self):
        db=Mock()
        previous=dict(id=3,item_id=5,qty_m=5000,unit_cents=100)
        reviewed=dict(id=7,item_id=5,qty_m=5000,approved_m=3000,decision=None)
        db.execute.side_effect=[Cursor(rows=[previous]),Cursor(rows=[reviewed]),Cursor(),Cursor(),Cursor()]
        with (
            patch.object(gestion,"_lines",return_value=[(5,8000,100)]),
            patch.object(gestion,"budget",return_value={"available_cents":1000}),
        ):
            gestion._edit_sent_purchase(db,ADMIN,dict(PURCHASE,status="Recibida"),{"lines":[]},PURCHASE["supplier"])
        receipt=next(c.args[1] for c in db.execute.call_args_list if c.args[0].startswith("INSERT INTO g_receipts"))
        self.assertEqual(receipt[:5],(5,3,"Proveedor",3000,100))
        self.assertFalse(any("DELETE FROM g_receipts" in c.args[0] for c in db.execute.call_args_list))

    def test_denied_rejection_only_reopens_the_unapproved_quantities(self):
        db=Mock()
        issue=dict(id=1,receipt_id=7,closed=None)
        receipt=dict(item_id=5,line_id=3,supplier="Proveedor",qty_m=5000,approved_m=3000,unit_cents=100)
        with (
            patch.object(gestion,"_one",side_effect=[issue,receipt,(2,)]),
            patch.object(gestion.inv,"receive") as receive,
        ):
            gestion._resolve(db,CAJA,{"id":1,"approve":False,"resolution":"Revisar las unidades restantes"})
        receive.assert_not_called()
        self.assertEqual(db.execute.call_args_list[0].args[1][:5],(5,3,"Proveedor",2000,100))
        self.assertFalse(db.execute.call_args_list[-1].args[1][0])

    def test_admitted_rejection_does_not_create_a_receipt(self):
        db=Mock()
        with patch.object(gestion,"_one",return_value={"id":1,"receipt_id":7,"closed":None}):
            gestion._resolve(db,CAJA,{"id":1,"approve":True,"resolution":"Daño confirmado"})
        db.execute.assert_called_once()
        self.assertTrue(db.execute.call_args.args[1][0])
