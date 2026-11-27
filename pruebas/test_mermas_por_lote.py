from unittest import TestCase
from unittest.mock import Mock, call, patch

from test_atencion_v4 import ADMIN, Cursor
import gestion
import inventario as inv


class TestMermasPorLote(TestCase):
    item = {"id": 7, "name": "Pechuga de pollo", "area": "Orientales",
            "unit": "kg", "display_unit": "filetes", "display_unit_milli": 1000}
    report = {"item_id": 7, "lot_id": 12, "reason": "Empaque dañado",
              "qty": {"unit": "filetes", "value": 2, "unit_milli": 1000}}

    def test_reserva_dos_filetes_del_lote_elegido(self):
        db = Mock()
        db.execute.side_effect = [
            Cursor(row=self.item),
            Cursor(row=self.item),
            Cursor(rows=[{"id": 12, "free": 3000, "expiry": None}]),
            Cursor(lastrowid=4), Cursor(), Cursor(),
        ]
        with patch.object(inv.porciones, "resolve", return_value=(7, 2000)) as resolve:
            self.assertEqual(gestion._waste(db, ADMIN, self.report), 4)

        resolve.assert_called_once_with(db, 7, 2000)
        lot_query, lot_args = db.execute.call_args_list[2].args
        self.assertIn(" AND id=?", lot_query)
        self.assertEqual((lot_args[0], lot_args[2]), (7, 12))
        self.assertEqual(db.execute.call_args_list[3].args[1][:3], (7, 12, 2000))
        db.execute.assert_has_calls([
            call("UPDATE inv_lots SET reserved=reserved+? WHERE id=?", (2000, 12)),
            call("INSERT INTO g_waste_lots(waste_id,lot_id,amount) VALUES(?,?,?)", (4, 12, 2000)),
        ])

    def test_exige_lote_y_filetes_enteros(self):
        with patch.object(gestion, "_item", return_value=self.item), patch.object(inv, "_plan") as plan:
            with self.assertRaisesRegex(ValueError, "lote afectado"):
                gestion._waste(Mock(), ADMIN, dict(self.report, lot_id=None))
            partial = dict(self.report["qty"], value="1.5")
            with self.assertRaises(ValueError):
                gestion._waste(Mock(), ADMIN, dict(self.report, qty=partial))
            plan.assert_not_called()

    def test_aprobacion_descuenta_el_lote_y_rechazo_solo_libera_la_reserva(self):
        waste = {"id": 4, "status": "Pendiente", "qty_m": 2000, "reason": "Empaque dañado"}
        for approve, status in ((True, "Aprobada"), (False, "Rechazada")):
            with (self.subTest(status=status), patch.object(inv, "_move") as move,
                  patch.object(inv, "withdraw") as withdraw,
                  patch.object(inv, "business_day", return_value="2026-11-30") as day):
                db = Mock()
                steps = [Cursor(row=waste), Cursor(rows=[{"lot_id": 12, "amount": 2000}]), Cursor()]
                if approve:
                    steps.append(Cursor(row={"approved_m": 6000, "unit_cents": 450, "entered_m": 6000}))
                db.execute.side_effect = steps + [Cursor(), Cursor()]
                self.assertEqual(gestion._review_waste(db, ADMIN, {"id": 4, "approve": approve}), 4)
                db.execute.assert_any_call("UPDATE inv_lots SET reserved=reserved-? WHERE id=?", (2000, 12))
                self.assertEqual(db.execute.call_args.args[1][0], status)
                withdraw.assert_not_called()
                if approve:
                    move.assert_called_once_with(db, ADMIN, 12, -2000, "Merma: Empaque dañado", "ME0004")
                    self.assertEqual(db.execute.call_args.args[1][3:5], (900, "2026-11-30"))
                else:
                    move.assert_not_called()
                    day.assert_not_called()
                    self.assertEqual(db.execute.call_args.args[1][3:5], (None, None))

    def test_valora_cuartos_con_el_costo_del_pollo_entero_recibido(self):
        db = Mock()
        db.execute.return_value = Cursor(row={"approved_m": 1000, "unit_cents": 1001, "entered_m": 4000})

        self.assertEqual(gestion._waste_lot_cost(db, {12: 2000}), 501)
        db.execute.return_value = Cursor()
        self.assertIsNone(gestion._waste_lot_cost(db, {12: 2000}))

    def test_costo_manual_solo_completa_merma_aprobada_pendiente(self):
        db = Mock()
        with self.assertRaises(PermissionError):
            gestion.act(db, dict(ADMIN, role="recepcion"), "gestion.waste_cost", {"id": 4, "cost_cents": 0})
        db.execute.assert_not_called()
        db.execute.return_value = Cursor()
        self.assertEqual(gestion.act(db, ADMIN, "gestion.waste_cost", {"id": 4, "cost_cents": 0})["id"], 4)
        query, args = db.execute.call_args.args
        self.assertIn("status=N'Aprobada' AND cost_cents IS NULL", query)
        self.assertEqual(args, (0, 4))
        db.execute.return_value = Cursor(count=0)
        with self.assertRaisesRegex(ValueError, "costo pendiente"):
            gestion.act(db, ADMIN, "gestion.waste_cost", {"id": 4, "cost_cents": 500})

    def test_mermas_historicas_toman_solo_lotes_de_sus_salidas(self):
        db = Mock()
        db.execute.side_effect = [
            Cursor(rows=[{"id": 4}, {"id": 5}]),
            Cursor(rows=[(12, 2000)]),
            Cursor(row={"approved_m": 6000, "unit_cents": 450, "entered_m": 6000}),
            Cursor(),
            Cursor(rows=[(14, 1000)]),
            Cursor(),
        ]

        gestion.register_existing_waste_costs(db)

        updates = [call.args[1] for call in db.execute.call_args_list if call.args[0].startswith("UPDATE")]
        self.assertEqual(updates, [(900, 4)])
        query, args = db.execute.call_args_list[1].args
        self.assertIn("delta<0", query)
        self.assertEqual(args, ("ME0004",))
