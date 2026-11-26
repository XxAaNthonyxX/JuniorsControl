"""Pruebas de lógica v4 sin conectarse a la base real: ejecutar con unittest.
La integridad de FK, índices y transacciones se prueba después en SQL Server aislado.
"""
import sys
import types
import unittest
from pathlib import Path

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
    def __init__(self, order=None, task=None, conflict=None, lines=None, delivered=0):
        self.order=order or {'id':1,'status':'Reservado','paid_at':None,'day':inv.today(),'version':1}
        self.task=task or {'area':'Cocina','status':'En cola'}
        self.task["revision"]=1
        self.conflict=conflict
        self.lines=lines or []
        self.delivered=delivered
        self.statements=[]
    def execute(self,sql,args=()):
        self.statements.append((sql,args))
        s=' '.join(sql.lower().split())
        if 'from inv_orders where id=' in s:return Cursor(self.order)
        if 'top(1) number from inv_orders' in s:return Cursor(self.conflict)
        if 'from inv_cancel_requests where order_id' in s:return Cursor()
        if 'from inv_details where order_id' in s and 'and detail_no' in s:return Cursor(self.task)
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
        db=Stub()
        out=inv._ask_cancel(db,WAITER,{'id':1,'version':1,'reason':'Cliente se retiró'})
        self.assertEqual(out['solicitud_id'],7)
        self.assertFalse(any('update inv_orders set status' in q.lower() for q,_ in db.statements))
        self.assertFalse(any('reserved=reserved-' in q.lower() for q,_ in db.statements))
    def test_send_to_preparation_uses_area_from_catalog(self):
        db=Stub(lines=[{'product_id':6,'qty':1,'detail_no':1,'sent_product':None,'sent_qty':None,'prep_area':'Barra'}])
        out=inv._send_to_areas(db,WAITER,{'id':1,'version':1})
        self.assertEqual(out['enviados'],1)
        ins=[args for q,args in db.statements if 'update inv_details set sent_product' in q.lower()]
        self.assertEqual(ins[0][0],'Barra')
    def test_sql_schema_guards(self):
        schema=(ROOT/'sql'/'atencion_v4.sql').read_text('utf8')
        for token in ['ux_juniors_mesa_jornada_abierta','inv_dispatch','inv_cancel_requests','FOREIGN KEY(order_id,product_id)','juniors_version SET version=4']:
            self.assertIn(token,schema)

if __name__=='__main__':unittest.main()
