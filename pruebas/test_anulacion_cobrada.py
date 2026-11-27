from unittest import TestCase
from unittest.mock import patch

from test_atencion_v4 import ADMIN, WAITER, Cursor, Stub, inv


class PaidOrderDB(Stub):
    def __init__(self, status="Cobrado", request_status=None, *, paid_lines=True):
        self.day=inv.today()
        self.request_status=request_status
        self.paid_lines=paid_lines
        super().__init__(order=dict(id=1,number=1,version=4,status=status,paid_at=self.day+" 13:00:00",
                                   day=self.day,user_id=WAITER["id"]))

    def execute(self,sql,args=()):
        normalized=" ".join(sql.lower().split())
        if "from inv_cancel_requests where order_id=?" in normalized or normalized.startswith("select * from inv_cancel_requests where id="):
            self.statements.append((sql,args))
            if self.request_status and ("where id=" in normalized or self.request_status=="Pendiente"):
                return Cursor(dict(id=7,order_id=1,revision=2,reason="Error de pedido",request_day=self.day,
                                   status=self.request_status,prior_status="Cobrado",decided_by="Caja",
                                   decided_at=self.day,decision_reason=None))
            return Cursor()
        if normalized.startswith("select l.* from inv_lines l join inv_sales"):
            return Cursor(rows=[dict(product_id=5,qty=3,price=500,refunded=1)] if self.paid_lines else [])
        if normalized.startswith("select cash_day from sale_voids"):
            return Cursor(dict(cash_day=self.day))
        if normalized.startswith("select lot_id,amount from sale_void_stock"):
            return Cursor(rows=[(9,1000)])
        if normalized.startswith("select detail_no,product_id,qty from inv_details"):
            return Cursor(rows=[dict(detail_no=1,product_id=5,qty=1),dict(detail_no=2,product_id=5,qty=2)])
        if normalized.startswith("select a.*,l.item_id"):
            return Cursor(rows=[dict(item_id=4,lot_id=9,expiry=None,amount=1500,processed=500)])
        if "from inv_return_details" in normalized:
            return Cursor(rows=[(1,1,1)])
        return super().execute(sql,args)

    def executemany(self,sql,rows):
        self.statements.append((sql,list(rows)))


class TestAnulacionCobrada(TestCase):
    def test_charged_detail_allows_request_without_changing_cash_or_stock(self):
        for status in ("Cobrado","Devuelto"):
            with self.subTest(status=status):
                db=PaidOrderDB(status)
                with patch.object(inv,"business_day",return_value=db.day):
                    result=inv.act(db,WAITER,"pedidos.request_cancel",dict(id=1,version=4,reason="Pedido duplicado"))
                self.assertEqual(result["solicitud_id"],7)
                self.assertFalse(any("sale_voids" in sql or sql.startswith("UPDATE") for sql,_ in db.statements))

    def test_permission_charge_and_pending_request_guards(self):
        payload=dict(id=1,version=4,reason="Pedido duplicado")
        with self.assertRaises(PermissionError):
            inv._ask_cancel(PaidOrderDB(),dict(WAITER,id=99),payload)
        with self.assertRaisesRegex(ValueError,"al menos un detalle cobrado"):
            inv._ask_cancel(PaidOrderDB(paid_lines=False),ADMIN,payload)
        with self.assertRaisesRegex(ValueError,"solicitud de cancelación pendiente"):
            inv._ask_cancel(PaidOrderDB(request_status="Pendiente"),ADMIN,payload)
        with self.assertRaisesRegex(ValueError,"Envía una solicitud"):
            inv.act(PaidOrderDB(),ADMIN,"pedidos.void_sale",payload)

    def test_approval_reverses_remaining_balance_and_selected_stock(self):
        db=PaidOrderDB(request_status="Pendiente")
        payload=dict(id=1,request_id=7,revision=2,approve=True,restock_details=[2],expected_day=db.day)
        with (
            patch.object(inv,"business_day",return_value=db.day),
            patch.object(inv,"_move") as movement,
        ):
            result=inv._decide_cancel(db,ADMIN,payload)
        self.assertEqual(result["void_cents"],1000)
        movement.assert_called_once()
        self.assertEqual(movement.call_args.args[2:4],(9,1000))
        void=next(args for sql,args in db.statements if sql.startswith("INSERT sale_voids"))
        self.assertEqual(void[-2:],(1000,7))
        request=next(args for sql,args in db.statements if "UPDATE inv_cancel_requests SET status=" in sql)
        self.assertEqual(request[0],"Aprobada")

    def test_rejection_leaves_the_charge_and_cannot_be_resolved_twice(self):
        db=PaidOrderDB(request_status="Pendiente")
        payload=dict(id=1,request_id=7,revision=2,approve=False)
        with patch.object(inv,"business_day",return_value=db.day):
            self.assertFalse(inv._decide_cancel(db,ADMIN,payload)["aprobada"])
        self.assertFalse(any("sale_voids" in sql or "UPDATE inv_orders SET status=" in sql for sql,_ in db.statements))
        with self.assertRaisesRegex(ValueError,"Actualiza la solicitud"):
            inv._decide_cancel(PaidOrderDB(request_status="Rechazada"),ADMIN,payload)

    def test_refund_is_paused_during_the_cancellation_request(self):
        with self.assertRaisesRegex(ValueError,"Resuelve la solicitud de anulación"):
            inv._refund(PaidOrderDB(request_status="Pendiente"),ADMIN,
                        dict(id=1,product_id=5,qty=1,reason="Devolución"))

    def test_undo_reverses_stock_and_restores_paid_status_and_pending_request(self):
        db=PaidOrderDB("Anulada","Aprobada")
        with (
            patch.object(inv,"business_day",return_value=db.day),
            patch.object(inv,"_move") as movement,
        ):
            inv._undo_request(db,ADMIN,dict(id=7,kind="cancel",revision=2))
        self.assertEqual(movement.call_args.args[2:4],(9,-1000))
        self.assertTrue(any(sql.startswith("DELETE FROM sale_voids") for sql,_ in db.statements))
        self.assertTrue(any(sql.startswith("UPDATE inv_orders SET status=?") and args==("Cobrado",1)
                            for sql,args in db.statements))
        self.assertTrue(any(sql.startswith("UPDATE inv_cancel_requests SET status='Pendiente'") for sql,_ in db.statements))
