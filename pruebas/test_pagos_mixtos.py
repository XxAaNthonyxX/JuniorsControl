from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN, Cursor
import inventario as inv


class TestPagosMixtos(TestCase):
    def test_guardar_un_cobro_y_sus_importes(self):
        day = "2026-11-30"
        order = {"id": 1, "day": day, "number": 6, "status": "Reservado",
                 "version": 4, "paid_at": None}
        db = Mock()
        db.execute.side_effect = [
            Cursor(), Cursor(rows=[(8, 2000, None)]), Cursor(row=(4400,)),
            Cursor(lastrowid=9), Cursor(), Cursor(), Cursor(row=(9,)),
        ]
        payload = {"id": 1, "version": 4, "expected_day": day, "expected_cents": 4400,
                   "payments": [{"method": "Efectivo", "cents": 2000},
                                {"method": "Yape", "cents": 2400}]}
        with patch.object(inv, "_get_order", return_value=order), \
             patch.object(inv, "_pending_cancel", return_value=False), \
             patch.object(inv, "_close_details", return_value={1: 2}), \
             patch.object(inv, "_reserve_lines"), \
             patch.object(inv, "business_day", return_value=day), \
             patch.object(inv, "_move") as move, patch.object(inv, "_event"):
            result = inv._pay(db, ADMIN, payload)
            self.assertEqual(result, {"id": 1, "sale_code": "V0009"})
            order["paid_at"] = day
            self.assertEqual(inv._pay(db, ADMIN, payload), result)
            move.assert_called_once()
        db.executemany.assert_called_once()
        self.assertEqual(list(db.executemany.call_args.args[1]), [(9, "Efectivo", 2000), (9, "Yape", 2400)])

    def test_rechazar_totales_invalidos_y_medios_repetidos(self):
        for payments in (
            [{"method": "Efectivo", "cents": 4399}],
            [{"method": "Yape", "cents": 4401}],
            [{"method": "Yape", "cents": 0}, {"method": "Tarjeta", "cents": 4400}],
            [{"method": "Yape", "cents": 2000}, {"method": "Yape", "cents": 2400}],
            [{"method": "Yape", "cents": "4400"}],
            [{"method": "Otro", "cents": 4400}],
        ):
            with self.subTest(payments=payments), self.assertRaises(ValueError):
                inv._payment_breakdown({"payments": payments}, 4400)

    def test_conservar_pago_unico(self):
        self.assertEqual(inv._payment_breakdown({"payment_method": "Yape"}, 4400), [("Yape", 4400)])
