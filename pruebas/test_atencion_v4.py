"""Pruebas de lógica v4 sin conectarse a la base real: ejecutar con unittest.
La integridad de FK, índices y transacciones se prueba después en SQL Server aislado.
"""
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
try:
    import pyodbc
except ImportError:
    sys.modules['pyodbc']=types.SimpleNamespace(IntegrityError=type('IntegrityError',(Exception,),{}))
import inventario as inv

class Cursor:
    def __init__(self, row=None, rows=None, lastrowid=None, count=1):
        self._row=row
        self._rows=rows or []
        self.lastrowid=lastrowid
        self.rowcount=count
    def fetchone(self):return self._row
    def fetchall(self):return self._rows
    def __iter__(self):return iter(self._rows)

class Stub:
    def __init__(self, order=None, task=None, conflict=None, lines=None, delivered=0, details=None,
                 cancellation_pending=False):
        self.order=order or {'id':1,'status':'Reservado','paid_at':None,'day':inv.today(),'version':1}
        self.task=task or {'area':'Cocina','status':'En cola'}
        self.task["revision"]=1
        self.conflict=conflict
        self.lines=lines or []
        self.delivered=delivered
        self.details=details or []
        self.cancellation_pending=cancellation_pending
        self.statements=[]
    def execute(self,sql,args=()):
        self.statements.append((sql,args))
        s=' '.join(sql.lower().split())
        if s.startswith('select * from inv_orders where id='):return Cursor(self.order)
        if 'top(1) number from inv_orders' in s:return Cursor(self.conflict)
        if 'from inv_cancel_requests where order_id' in s:return Cursor({'id':7} if self.cancellation_pending else None)
        if s.startswith("select 1 from inv_details where order_id=? and status='entregado'"):
            return Cursor((1,) if self.delivered or any(d["status"]=="Entregado" for d in self.details) else None)
        if 'from inv_details where order_id' in s and 'and detail_no' in s:return Cursor(self.task)
        if s.startswith('select * from inv_details where order_id'):return Cursor(rows=self.details)
        if s.startswith('select number,day from inv_orders'):return Cursor({'number':1,'day':inv.today()})
        if 'select count(*),count(case' in s:return Cursor((1,self.delivered))
        if 'select d.*,p.prep_area' in s:return Cursor(rows=self.lines)
        if 'select * from inv_lines where order_id' in s:return Cursor(rows=self.lines)
        if 'insert into inv_cancel_requests' in s:return Cursor(lastrowid=7)
        return Cursor()

ADMIN={'id':1,'name':'Admin','role':'admin','area':''}
WAITER={'id':2,'name':'Mesero','role':'atencion','area':''}
COOK={'id':3,'name':'Cocinero','role':'area','area':'Cocina'}
BAR={'id':4,'name':'Barra','role':'area','area':'Barra'}

class TestAtencionV4(unittest.TestCase):
    def test_20_tables_and_floors(self):
        for n in range(1,21): self.assertEqual(inv._table_number(str(n)),n)
        for invalid in [0,21,'-1','2A','Mesa 2',True,None]:
            with self.subTest(value=invalid),self.assertRaises(ValueError):inv._table_number(invalid)
        self.assertEqual((1 if inv._table_number(10)<=10 else 2),1)
        self.assertEqual((1 if inv._table_number(11)<=10 else 2),2)
    def test_roles_are_server_enforced(self):
        self.assertTrue(inv._may_work(ADMIN,'Barra'))
        self.assertTrue(inv._may_work(COOK,'Cocina'))
        self.assertFalse(inv._may_work(COOK,'Barra'))
        self.assertFalse(inv._may_work(BAR,'Parrilla'))
    def test_valid_areas(self):
        for area in ['Cocina','Barra','Parrilla']:self.assertEqual(inv._prep_area(area),area)
        for area in ['Todas','Atención','',None]:
            with self.assertRaises(ValueError):inv._prep_area(area)
    def test_occupied_same_date_blocks_new_order(self):
        db=Stub(conflict={'number':5})
        with self.assertRaisesRegex(ValueError,'OCUPADA.*C0005'):
            inv._save_order(db,WAITER,{'table_number':2,'lines':[{'product_id':1,'qty':1}]})
        self.assertFalse(any('insert into inv_orders' in q.lower() for q,_ in db.statements))
    def test_preparation_wrong_area_is_rejected(self):
        db=Stub(task={'area':'Barra','status':'En cola'})
        with self.assertRaises(PermissionError):
            inv._advance_preparation(db,COOK,{'id':1,'product_id':8,'detail_no':1,'revision':1,'step':'preparar'})
        self.assertFalse(any('update inv_details' in q.lower() for q,_ in db.statements))
    def test_direct_delivery_from_each_pending_status(self):
        for status in ("En cola","Preparando","Listo"):
            with self.subTest(status=status):
                db=Stub(task={"area":"Cocina","status":status})
                result=inv._advance_preparation(db,COOK,{"id":1,"product_id":8,"detail_no":1,"revision":1,"step":"entregar"})
                self.assertEqual(result["estado"],"Entregado")
                update=next(args for sql,args in db.statements if sql.startswith("UPDATE inv_details"))
                self.assertEqual(update[-1],status)
    def test_no_payment_before_delivery(self):
        db=Stub(delivered=0)
        with self.assertRaisesRegex(ValueError,'entregados'):
            inv._pay(db,ADMIN,{'id':1,'version':1})
    def test_request_cancel_keeps_table_busy(self):
        db=Stub(delivered=1)
        out=inv._ask_cancel(db,WAITER,{'id':1,'version':1,'reason':'Cliente se retiró'})
        self.assertEqual(out['solicitud_id'],7)
        self.assertFalse(any('update inv_orders set status' in q.lower() for q,_ in db.statements))
        self.assertFalse(any('reserved=reserved-' in q.lower() for q,_ in db.statements))
    def test_request_cancel_requires_delivery(self):
        with self.assertRaisesRegex(ValueError,"requiere un producto entregado"):
            db=Stub(details=[dict(sent_at="2026-11-27",status="En cola")])
            inv._ask_cancel(db,WAITER,dict(id=1,version=1,reason="Retirar detalle"))
    def test_send_to_preparation_uses_area_from_catalog(self):
        db=Stub(lines=[{'product_id':6,'qty':1,'detail_no':1,'sent_product':None,'sent_qty':None,
                       'prep_area':'Barra','remove_pending':False}])
        out=inv._send_to_areas(db,WAITER,{'id':1,'version':1})
        self.assertEqual(out['enviados'],1)
        ins=[args for q,args in db.statements if 'update inv_details set sent_product' in q.lower()]
        self.assertEqual(ins[0][0],'Barra')
    def test_saving_removed_details_keeps_the_sent_reservation_until_confirmation(self):
        details=[
            dict(detail_no=1,product_id=6,qty=1,sent_at="2026-11-27",sent_product=6,sent_qty=1,status="Preparando",remove_pending=False),
            dict(detail_no=2,product_id=1,qty=1,sent_at=None,status=None,remove_pending=False),
            dict(detail_no=3,product_id=5,qty=1,sent_at=None,status=None,remove_pending=False),
        ]
        db=Stub(details=details,order=dict(id=1,day=inv.today(),status='Reservado',version=1,take_away=False))
        payload=dict(id=1,version=1,table_number=1,lines=[dict(detail_no=3,product_id=5,qty=1)])
        with patch.object(inv,"_reserve_lines") as reserve:
            inv._save_order(db,WAITER,payload)
        self.assertEqual(reserve.call_args.args[2],{5:1,6:1})
        self.assertTrue(any("SET remove_pending=1" in sql and args==(1,1) for sql,args in db.statements))
        self.assertTrue(any("SET status='Cancelado'" in sql and args==(1,2) for sql,args in db.statements))
        self.assertFalse(any("SET sent_product=product_id" in sql for sql,_ in db.statements))

    def test_confirming_changes_replaces_the_sent_snapshot_and_reallocates_stock(self):
        sent=dict(detail_no=1,product_id=6,qty=1,sent_at="2026-11-27",sent_product=6,sent_qty=1,
                  status="Preparando",remove_pending=False,prep_area="Barra")
        removed=dict(sent,detail_no=2,product_id=3,sent_product=3,remove_pending=True)
        delivered=dict(sent,detail_no=3,product_id=4,sent_product=4,status="Entregado")
        changed=dict(sent,product_id=5,qty=2,prep_area="Cocina")
        lines=[dict(detail_no=1,product_id=5,qty=2),dict(detail_no=3,product_id=4,qty=1)]
        order=dict(id=1,day=inv.today(),status="Reservado",version=1,take_away=False)
        db=Stub(order=order,details=[sent,removed,delivered],lines=[changed,delivered])
        payload=dict(id=1,version=1,table_number=1,lines=lines,confirm_changes=True)
        with patch.object(inv,"_reserve_lines") as reserve:
            result=inv._save_order(db,WAITER,payload)
        self.assertFalse(result["cerrada"])
        self.assertEqual(reserve.call_args.args[2],{5:2,4:1})
        self.assertTrue(any("SET status='Cancelado'" in sql and args==(1,2) for sql,args in db.statements))
        self.assertEqual([(args[0],args[2],args[3]) for sql,args in db.statements if "SET sent_product=product_id" in sql],
                         [("Cocina",1,1)])

    def test_confirming_an_edit_cannot_change_a_delivered_detail(self):
        details=[dict(detail_no=1,product_id=6,qty=1,sent_at="2026-11-27",status="Entregado",remove_pending=False)]
        order=dict(id=1,day=inv.today(),status="Reservado",version=1,take_away=False)
        db=Stub(order=order,details=details)
        payload=dict(id=1,version=1,table_number=1,lines=[dict(detail_no=1,product_id=6,qty=2)],confirm_changes=True)
        with self.assertRaisesRegex(ValueError,"entregado no se puede modificar"):
            inv._save_order(db,WAITER,payload)
        self.assertFalse(any(sql.startswith("UPDATE") for sql,_ in db.statements))

    def test_confirming_retirement_reduces_reservations_for_the_same_product(self):
        job=dict(product_id=6,qty=1,sent_product=6,sent_qty=1)
        db=Stub(lines=[dict(job,detail_no=1,remove_pending=True),dict(job,detail_no=2,remove_pending=False)])
        with patch.object(inv,"_reserve_lines") as reserve:
            result=inv._send_to_areas(db,WAITER,dict(id=1,version=1))
        self.assertEqual(result["retirados"],1)
        self.assertEqual(result["enviados"],0)
        self.assertEqual(reserve.call_args.args[2],{6:1})
        self.assertTrue(any("revision=revision+1" in sql and args==(1,1) for sql,args in db.statements))

    def test_retiring_the_last_detail_closes_the_order_and_releases_its_reservation(self):
        db=Stub(lines=[dict(product_id=6,qty=1,sent_product=6,sent_qty=1,detail_no=1,remove_pending=True)])
        with patch.object(inv,"_reserve_lines") as reserve:
            result=inv._send_to_areas(db,WAITER,dict(id=1,version=1))
        self.assertTrue(result["cerrada"])
        self.assertEqual(reserve.call_args.args[2],{})
        self.assertTrue(any(sql.startswith("UPDATE inv_orders SET status=?") and args==("Cancelado",1)
                            for sql,args in db.statements))

    def test_delivering_before_confirmation_cancels_the_pending_retirement(self):
        db=Stub(task=dict(area="Cocina",status="Preparando",remove_pending=True))
        inv._advance_preparation(db,COOK,dict(id=1,product_id=6,detail_no=1,revision=1,step="entregar"))
        self.assertTrue(any("SET product_id=sent_product,qty=sent_qty,remove_pending=0" in sql for sql,_ in db.statements))
        delivered=dict(status="Entregado",product_id=6,qty=1,remove_pending=False)
        with self.assertRaisesRegex(ValueError,"entregado no se puede eliminar"):
            inv._validate_details([dict(detail_no=2,product_id=5,qty=1)],{1:delivered})

    def test_cancel_before_delivery_releases_reservations_and_retires_sent_details(self):
        for dispatched in (False,True):
            with self.subTest(dispatched=dispatched),patch.object(inv,"_release") as release:
                details=[dict(sent_at="2026-11-27",status="Preparando")] if dispatched else [dict(sent_at=None,status=None)]
                db=Stub(details=details)
                inv._cancel(db,WAITER,dict(id=1,version=1))
                release.assert_called_once_with(db,1)
                self.assertTrue(any("UPDATE inv_details SET status='Cancelado'" in sql for sql,_ in db.statements))
                self.assertTrue(any("UPDATE inv_orders SET status='Cancelado'" in sql for sql,_ in db.statements))
                self.assertFalse(any("INSERT INTO inv_cancel_requests" in sql for sql,_ in db.statements))

    def test_cancel_delivered_or_pending_approval_does_not_release_reservations(self):
        for db,error in ((Stub(delivered=1),"productos entregados"),(Stub(cancellation_pending=True),"debe aprobarse")):
            with self.subTest(error=error),patch.object(inv,"_release") as release:
                with self.assertRaisesRegex(ValueError,error):
                    inv._cancel(db,WAITER,dict(id=1,version=1))
                release.assert_not_called()

    def test_cancel_does_not_allow_preparation_role_or_stale_version(self):
        with self.assertRaises(PermissionError):
            inv._cancel(Stub(),COOK,dict(id=1,version=1))
        with self.assertRaisesRegex(ValueError,"otra sesión"):
            inv._cancel(Stub(),WAITER,dict(id=1,version=2))

    def test_cancellation_consumes_only_delivered_details_not_returned_to_inventory(self):
        class CancelDB(Stub):
            def execute(self,sql,args=()):
                if sql.startswith("SELECT item_id,amount"):
                    return Cursor(rows=[(5,500)])
                return super().execute(sql,args)

            def executemany(self,sql,args):
                self.statements.append((sql,list(args)))

        db=CancelDB()
        order=dict(id=1,number=1,day=inv.today())
        details=[dict(detail_no=1,sent_product=3,sent_qty=1),dict(detail_no=2,sent_product=3,sent_qty=2)]
        with patch.object(inv,"withdraw",return_value=[(4,1000,None)]) as withdraw:
            inv._consume_cancelled_deliveries(db,ADMIN,order,7,details,{1})
        self.assertEqual(withdraw.call_args.args[2:4],(5,1000))
        self.assertEqual(db.statements[-1][1],[(7,4,1000)])

    def test_refundable_details_account_for_tagged_and_legacy_credits(self):
        details=[dict(detail_no=1,qty=3),dict(detail_no=2,qty=2),dict(detail_no=3,qty=1)]
        self.assertEqual(inv._detail_refundable(details,{2:1},3),{1:1,2:1,3:1})

    def test_full_refund_requires_remaining_quantities_and_retains_stock_choices(self):
        class RefundDB(Stub):
            def execute(self,sql,args=()):
                if sql.startswith("SELECT detail_no,product_id"):
                    return Cursor(rows=[(1,6),(2,5)])
                if sql.startswith("SELECT product_id,qty-refunded"):
                    return Cursor(rows=[(6,1),(5,2)])
                return super().execute(sql,args)

        db=RefundDB(order=dict(id=1,version=1,status="Cobrado"))
        entries=[dict(detail_no=1,qty=1,restock=False),dict(detail_no=2,qty=2,restock=True)]
        payload=dict(id=1,version=1,expected_day=inv.today(),whole=True,reason="Devolución",details=entries)
        with (
            patch.object(inv,"business_day",return_value=inv.today()),
            patch.object(inv,"_refund",side_effect=[{"return_code":"DV0001"},{"return_code":"DV0002"}]) as refund,
        ):
            with self.assertRaisesRegex(ValueError,"todos los detalles"):
                inv._refund_order(db,ADMIN,dict(payload,details=entries[:1]))
            refund.assert_not_called()
            self.assertEqual(inv._refund_order(db,ADMIN,payload)["return_codes"],["DV0001","DV0002"])
        for call,entry in zip(refund.call_args_list,entries):
            self.assertEqual(call.args[2]["details"],[entry])

    def test_refund_replenishes_only_units_selected_for_stock(self):
        class RefundDB(Stub):
            def execute(self,sql,args=()):
                if sql.startswith("SELECT * FROM inv_lines"):
                    return Cursor(dict(name="Chicha",qty=3,refunded=0))
                if sql.startswith("SELECT COALESCE(SUM(qty)"):
                    return Cursor((0,))
                if sql.startswith("SELECT detail_no,qty"):
                    return Cursor(rows=[dict(detail_no=1,qty=1),dict(detail_no=2,qty=2)])
                if sql.startswith("SELECT a.*,l.item_id"):
                    return Cursor(rows=[dict(item_id=8,lot_id=10,amount=1500,processed=0,expiry=None)])
                if sql.startswith("INSERT INTO inv_returns"):
                    return Cursor(lastrowid=5)
                return super().execute(sql,args)

            def executemany(self,sql,args):
                self.statements.append((sql,list(args)))

        db=RefundDB(order=dict(id=1,version=1,status="Cobrado",number=1,day=inv.today()))
        entries=[dict(detail_no=1,qty=1,restock=False),dict(detail_no=2,qty=2,restock=True)]
        with (
            patch.object(inv,"business_day",return_value=inv.today()),
            patch.object(inv,"_move") as move,
        ):
            inv._refund(db,ADMIN,dict(id=1,product_id=5,qty=3,reason="Devolución",details=entries))
        self.assertEqual(move.call_args.args[2:4],(10,1000))
        self.assertTrue(any("SET processed=processed+?" in sql and args[0]==1500 for sql,args in db.statements))
        self.assertTrue(any("SET refunded=refunded+?" in sql and args[0]==3 for sql,args in db.statements))
    def test_sql_schema_guards(self):
        schema=(ROOT/'sql'/'atencion_v4.sql').read_text('utf8')
        for token in ['ux_juniors_mesa_jornada_abierta','inv_dispatch','inv_cancel_requests','FOREIGN KEY(order_id,product_id)','juniors_version SET version=4']:
            self.assertIn(token,schema)

if __name__=='__main__':unittest.main()
