from collections import defaultdict
from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN, Cursor
import gestion


class TestBoletasGastos(TestCase):
    def test_numbering_is_shared_by_expense_types_and_restarts_each_day(self):
        issued=defaultdict(list)
        db=Mock()

        def execute(query,args):
            if query.startswith("SELECT COALESCE(MAX(receipt_no)"):
                self.assertNotIn("void_at",query)
                return Cursor((max(issued[args[0]],default=0)+1,))
            if query.startswith("INSERT INTO cash_expenses"):
                day,number,kind,reference,concept,cents,actor,purchase_id=args
                self.assertIsNone(purchase_id)
                self.assertEqual(reference,"")
                self.assertEqual(cents,1050)
                issued[day].append(number)
                return Cursor(lastrowid=sum(map(len,issued.values())))
            raise AssertionError(query)

        db.execute.side_effect=execute
        first,second="2026-11-27","2026-11-28"
        base=dict(day=first,kind="Personal",concept="Prueba",amount="10.50")
        with patch.object(gestion.inv,"business_day",return_value=first):
            self.assertEqual(gestion.act(db,ADMIN,"gestion.cash_expense",base)["code"],"BL0001")
            self.assertEqual(gestion.act(db,ADMIN,"gestion.cash_expense",dict(base,kind="Mercado"))["code"],"BL0002")
        with patch.object(gestion.inv,"business_day",return_value=second):
            self.assertEqual(gestion.act(db,ADMIN,"gestion.cash_expense",dict(base,day=second))["code"],"BL0001")
            with self.assertRaisesRegex(ValueError,"jornada cambió"):
                gestion.act(db,ADMIN,"gestion.cash_expense",base)

    def test_repeated_external_reference_still_detected(self):
        db=Mock()
        db.execute.return_value=Cursor((7,))
        with self.assertRaisesRegex(ValueError,"referencia ya está registrada"):
            gestion._record_cash_expense(db,ADMIN,dict(kind="Mercado",reference="Ext-001"),"2026-11-27")
        db.execute.assert_called_once()
