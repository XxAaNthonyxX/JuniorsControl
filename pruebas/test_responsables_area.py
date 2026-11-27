from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN, Cursor
import acceso
import gestion
import inventario as inv


class TestResponsablesPorArea(TestCase):
    def setUp(self):
        self.parrillas = {"id": 5, "name": "Responsable", "role": "area", "area": "Parrillas"}

    def test_cada_area_tiene_una_cola_y_un_catalogo_de_insumos(self):
        for area in inv.PREPARATION_AREAS:
            user = dict(self.parrillas, area=area)
            with self.subTest(area=area):
                db = Mock()
                db.execute.return_value = Cursor(rows=[{"number": 9, "area": area}])
                self.assertEqual(inv._preparation(db, user), [{"code": "C0009", "number": 9, "area": area}])
                query, parameters = db.execute.call_args.args
                self.assertIn("AND d.area=?", query)
                self.assertEqual(parameters, [area])
                self.assertEqual(inv.inventory_access_areas(user), (area,))
                self.assertTrue(inv._may_work(user, area))
                self.assertTrue(all(not inv._may_work(user, other) for other in inv.PREPARATION_AREAS if other != area))

    def test_comanda_mixta_envia_cada_detalle_a_su_area(self):
        categories = ("Orientales", "Brasas", "Parrillas", "Barra")
        details = [{"detail_no": number, "prep_area": inv._default_prep_area(category)}
                   for number, category in enumerate(categories, 1)]
        db = Mock()
        inv._dispatch_details(db, ADMIN, 17, details)
        expected = [(category, 17, number) for number, category in enumerate(categories, 1)]
        actual = [(args[0], args[2], args[3]) for sql, args in (call.args for call in db.execute.call_args_list)
                  if "UPDATE inv_details" in sql]
        self.assertEqual(actual, expected)

    def test_sin_horno_y_con_compatibilidad_para_cuentas_existentes(self):
        self.assertNotIn("Horno", inv.STAFF_AREAS)
        self.assertEqual(acceso._role_area({"role": "area", "area": "Horno"}), ("area", "Brasas"))
        self.assertEqual(inv.inventory_access_areas(dict(self.parrillas, area="Parrilla")), ("Parrillas",))
        with self.assertRaises(ValueError):
            acceso._role_area({"role": "area", "area": "Área inventada"})
        support = dict(self.parrillas, area="Limpieza y Atención")
        self.assertFalse(inv._can_prepare(support))
        db = Mock()
        self.assertEqual(inv._preparation(db, support), [])
        db.execute.assert_not_called()

    def test_reporta_y_consulta_mermas_de_su_area(self):
        db = Mock()
        wastes = [{"id": 2, "qty_m": 1000, "area": "Parrillas"}, {"id": 3, "qty_m": 2000, "area": "Brasas"}]
        db.execute.side_effect = [Cursor(rows=wastes), Cursor(), Cursor()]
        result = gestion.state(db, self.parrillas)
        self.assertEqual([waste["code"] for waste in result["wastes"]], ["ME0002"])
        with patch.object(gestion, "_item", return_value={"area": "Brasas"}):
            with self.assertRaisesRegex(PermissionError, "otra área"):
                gestion._waste(db, self.parrillas, {"item_id": 4, "lot_id": 2})
        with self.assertRaises(PermissionError):
            gestion._review_waste(db, self.parrillas, {"id": 2, "approve": True})
