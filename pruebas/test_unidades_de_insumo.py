from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN
import gestion
import inventario as inv


class TestUnidadesDeInsumo(TestCase):
    def test_bistec_y_chicha_usan_unidades_menores_enteras(self):
        self.assertEqual(inv.item_quantity("Bistec", {"unit": "g", "value": "280"}, unit="kg"), 280)
        self.assertEqual(inv.item_quantity("Chicha", {"unit": "mL", "value": "400"}, unit="L"), 400)
        for quantity in ({"unit": "g", "value": "280.5"}, {"unit": "mL", "value": "280"}, "0.28"):
            with self.subTest(quantity=quantity), self.assertRaises(ValueError):
                inv.item_quantity("Bistec", quantity, unit="kg")

    def test_papa_y_arroz_conservan_cantidades_decimales(self):
        for name in ("Papa para freír", "Arroz cocido"):
            with self.subTest(name=name):
                self.assertEqual(inv.item_quantity(name, "1.5", unit="kg"), 1500)

    def test_compra_en_gramos_con_cotizacion_por_kilo(self):
        item = {"id": 1, "name": "Bistec", "unit": "kg"}
        row = {"item_id": 1, "qty": {"unit": "g", "value": "1500"}, "unit_cents": 1200}
        with patch.object(gestion, "_item", return_value=item):
            self.assertEqual(gestion._lines(Mock(), [row]), [(1, 1500, 1200)])
        self.assertEqual(gestion._amount(1500, 1200), 1800)

    def test_recepcion_registra_solo_los_gramos_aprobados(self):
        receipt = {"id": 5, "item_id": 1, "approved_m": None, "qty_m": 1500, "line_id": None}
        item = {"id": 1, "name": "Bistec", "unit": "kg"}
        payload = {"id": 5, "approved": {"unit": "g", "value": "1250"},
                   "received": {"unit": "g", "value": "1500"}, "reason": "Parte rechazada"}
        with patch.object(gestion, "_one", return_value=receipt), \
             patch.object(gestion, "_item", return_value=item), \
             patch.object(inv, "receive", return_value=3) as receive:
            db = Mock()
            gestion._receive(db, ADMIN, payload)
            self.assertEqual(receive.call_args.args[3], 1250)
            self.assertIn("INSERT INTO g_incidents", db.execute.call_args.args[0])
