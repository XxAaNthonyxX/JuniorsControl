from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import WAITER, Cursor
import acceso
import gestion
import inventario as inv


class TestPermisosMesero(TestCase):
    def test_mesero_no_accede_a_compras_aunque_tenga_una_delegacion_anterior(self):
        db = Mock()
        for action in ("purchase", "edit_purchase", "decide", "reopen", "dispatch", "send_purchase_list", "report"):
            with self.subTest(action=action), self.assertRaises(PermissionError):
                gestion.act(db, WAITER, "gestion." + action, {"id": 12})
        db.execute.assert_not_called()

        db.execute.return_value = Cursor(rows=[{"id": 1, "area": "Limpieza y Atención"},
                                               {"id": 2, "area": "Brasas"}])
        result = gestion.state(db, dict(WAITER, area="Brasas"))
        self.assertEqual(result["purchases"], [])
        self.assertEqual([r["id"] for r in result["alerts"]], [1])
        db.execute.assert_called_once()

    def test_mesero_no_puede_ser_delegado_de_una_compra(self):
        db = Mock()
        db.execute.return_value = Cursor(row={"id": WAITER["id"], "role": "atencion"})
        with self.assertRaisesRegex(ValueError, "persona autorizada"):
            gestion._assignee(db, WAITER["id"])
        db.execute.return_value = Cursor(row={"id": 3, "role": "caja"})
        self.assertEqual(gestion._assignee(db, 3), 3)

    def test_inventario_del_mesero_usa_solo_limpieza_y_atencion(self):
        waiter = dict(WAITER, area="Brasas")
        item = {"id": 11, "area": "Limpieza y Atención", "available": 8}
        grill = {"id": 2, "area": "Brasas", "available": 20}
        lots = [{"id": 1, "item_id": 11}, {"id": 2, "item_id": 2}]
        db = Mock()
        db.execute.return_value = Cursor(row=(0,))
        with (patch.object(inv, "stock", return_value=[item, grill]),
              patch.object(inv, "batches", return_value=lots),
              patch.object(inv, "_products", return_value=[{"id": 1, "name": "Pollo a la brasa"}]),
              patch.object(inv, "_orders", return_value=[]),
              patch.object(inv, "_service_requests", return_value=[])):
            state = inv.state(db, waiter, "2026-11-30")
        self.assertEqual(state["areas"], ("Limpieza y Atención",))
        self.assertEqual(state["items"], [item])
        self.assertEqual(state["lots"], lots[:1])
        self.assertEqual(state["products"][0]["name"], "Pollo a la brasa")
        self.assertEqual(acceso._role_area({"role": "atencion", "area": "Brasas"}), ("atencion", "Atención"))
        self.assertTrue(any("LOWER(i.area) IN (?)" in call.args[0] and call.args[1]==["limpieza y atención"]
                            for call in db.execute.call_args_list))

    def test_mesero_no_puede_consultar_ni_consumir_insumos_ajenos(self):
        db = Mock()
        with self.assertRaises(PermissionError):
            inv._history(db, WAITER, {"area": "Barra"})
        db.execute.assert_not_called()
        with patch.object(inv, "_item", return_value={"id": 2, "area": "Brasas"}):
            with self.assertRaises(PermissionError):
                inv.act(db, WAITER, "inv.use", {"item_id": 2, "qty": 1, "reason": "Prueba"})
        db.execute.assert_not_called()
