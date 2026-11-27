from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN
import gestion
import inventario as inv


class TestUnidadesDeInsumo(TestCase):
    def test_bistec_y_arroz_por_unidades_enteras(self):
        for name, label, size in (("Bistec de res","filetes",280), ("Arroz cocido","porciones",500)):
            item = {"display_unit":label, "display_unit_milli":size}
            with self.subTest(name=name):
                self.assertEqual(inv.item_quantity(name,{"unit":label,"value":3,"unit_milli":size},
                                                   unit="kg",item=item),3*size)
                for quantity in ({"unit":label,"value":1.5,"unit_milli":size},
                                 {"unit":label,"value":1,"unit_milli":size+1}, "0.125"):
                    with self.assertRaises(ValueError):
                        inv.item_quantity(name,quantity,unit="kg",item=item)

    def test_papa_acepta_solo_medios_kilos_y_respeta_el_historial(self):
        for value,expected in (("0.5",500),("1",1000),("1.5",1500)):
            self.assertEqual(inv.item_quantity("Papa para freír",value,unit="kg"),expected)
        with self.assertRaises(ValueError):
            inv.item_quantity("Papa para freír","1.25",unit="kg")
        self.assertEqual(inv.item_quantity("Papa para freír","1.25",unit="kg",previous=1250),1250)
        with self.assertRaises(ValueError):
            inv.item_quantity("Papa para freír","250",unit="g")

    def test_cambiar_unidad_solo_cambia_la_equivalencia(self):
        item = {"id":1,"name":"Arroz cocido","unit":"kg"}
        db = Mock()
        with patch.object(inv,"_item",return_value=item):
            inv.act(db,ADMIN,"inv.item_unit",{"id":1,"display_unit":"porciones","base_per_unit":"0.5"})
        db.execute.assert_called_once_with(
            "UPDATE inv_items SET display_unit=?,display_unit_milli=? WHERE id=?",("porciones",500,1))

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
