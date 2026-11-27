from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import Cursor
import gestion
import inventario as inv


RECEPCION = {"id": 6, "role": "recepcion", "area": "Barra", "name": "Recepción"}


class TestPermisosRecepcion(TestCase):
    def test_compras_y_mermas_rechazadas_antes_de_consultar_datos(self):
        db = Mock()
        actions = (
            "purchase", "edit_purchase", "decide", "reopen", "dispatch", "send_purchase_list",
            "report", "waste", "review_waste", "resolve",
        )
        for action in actions:
            with self.subTest(action=action), self.assertRaises(PermissionError):
                gestion.act(db, RECEPCION, "gestion." + action, {"id": 12})
        db.execute.assert_not_called()

        db.execute.return_value = Cursor(row={"id": RECEPCION["id"], "role": "recepcion"})
        with self.assertRaisesRegex(ValueError, "persona autorizada"):
            gestion._assignee(db, RECEPCION["id"])

    def test_gestion_muestra_la_recepcion_sin_compras_ni_mermas(self):
        db = Mock()
        receipt = {"id": 1, "qty_m": 1000, "approved_m": None, "received_m": None,
                   "unit_cents": 400, "area": "Brasas", "purchase_id": 12}
        db.execute.side_effect = [Cursor(rows=[receipt]), Cursor(), Cursor()]

        state = gestion.state(db, RECEPCION)

        self.assertEqual(state["purchases"], [])
        self.assertEqual(state["wastes"], [])
        self.assertEqual(state["receipts"][0]["status"], "Pendiente")
        self.assertEqual(state["receipts"][0]["area"], "Brasas")
        self.assertNotIn("unit_cents", state["receipts"][0])
        self.assertEqual(db.execute.call_count, 3)

    def test_rechazar_recepcion_registra_solicitud_sin_sumar_stock(self):
        db = Mock()
        receipt = {"id": 6, "item_id": 9, "qty_m": 2000, "approved_m": None, "line_id": None, "version": 1}
        item = {"name": "Bistec de res", "unit": "filetes"}
        db.execute.side_effect = [Cursor(row=receipt), Cursor(row=item), Cursor(), Cursor()]
        with patch.object(inv, "receive") as receive:
            result = gestion.act(db, RECEPCION, "gestion.receive", {
                "id": 6, "version": 1, "received": "2", "approved": "0", "reason": "Producto dañado",
            })
        receive.assert_not_called()
        update, incident = db.execute.call_args_list[2:]
        self.assertIn("UPDATE g_receipts", update.args[0])
        self.assertEqual(update.args[1][:4], (0, 2000, "Producto dañado", None))
        self.assertIn("INSERT INTO g_incidents", incident.args[0])
        self.assertEqual(incident.args[1][0], 6)
        self.assertEqual(result["code"], "RC0006")

    def test_inventario_muestra_los_insumos_y_lotes_de_todas_las_areas(self):
        db = Mock()
        db.execute.return_value = Cursor()
        items = [{"id": i, "area": area, "available": 8} for i, area in enumerate(inv.INVENTORY_AREAS, 1)]
        lots = [{"id": i["id"], "item_id": i["id"]} for i in items]
        with (patch.object(inv, "stock", return_value=items),
              patch.object(inv, "batches", return_value=lots)):
            state = inv.state(db, RECEPCION, "2026-11-30")
        self.assertEqual(state["areas"], inv.INVENTORY_AREAS)
        self.assertEqual(state["items"], items)
        self.assertEqual(state["lots"], lots)

    def test_whatsapp_corresponde_al_proveedor_guardado_en_el_rechazo(self):
        db = Mock()
        db.execute.side_effect = [Cursor(row=("proveedor de prueba",)), Cursor(count=0), Cursor()]
        result = gestion.act(db, RECEPCION, "gestion.supplier_whatsapp", {
            "id": 17, "whatsapp": "987 654 321", "supplier": "Otro proveedor",
        })
        self.assertEqual(result["id"], 17)
        lookup, update, insert = db.execute.call_args_list
        self.assertIn("JOIN g_receipts", lookup.args[0])
        self.assertEqual(lookup.args[1], (17,))
        self.assertEqual(update.args[1], ("51987654321", "proveedor de prueba"))
        self.assertEqual(insert.args[1], ("proveedor de prueba", "51987654321"))

    def test_whatsapp_rechaza_numero_invalido_o_cuenta_sin_permiso(self):
        db = Mock()
        with self.assertRaises(ValueError):
            gestion.act(db, RECEPCION, "gestion.supplier_whatsapp", {"id": 17, "whatsapp": "https://wa.me/"})
        with self.assertRaises(PermissionError):
            gestion.act(db, dict(RECEPCION, role="area"), "gestion.supplier_whatsapp", {"id": 17, "whatsapp": "987654321"})
        db.execute.assert_not_called()
