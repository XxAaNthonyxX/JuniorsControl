from unittest import TestCase
from unittest.mock import Mock, patch

from test_atencion_v4 import ADMIN, WAITER, Cursor
import acceso


class TestReenvioAcceso(TestCase):
    email = "persona@example.test"
    login_url = "https://juniors.example.test/"
    smtp = {"email": "remitente@example.test", "protected": b"secreto simulado"}

    def test_cuenta_activa_recibe_enlace_y_conserva_sus_datos(self):
        db = Mock()
        db.execute.side_effect = [Cursor(row={"active": 1}), Cursor(row=self.smtp)]
        with patch.object(acceso, "_new_code") as code, patch.object(acceso, "_send_email") as send:
            result = acceso.act(db, ADMIN, "invite", {
                "email": self.email, "role": "admin", "_login_url": self.login_url,
            })
            result["_send_invite"]()
        code.assert_not_called()
        send.assert_called_once()
        sender, protected, recipient, subject, body = send.call_args.args
        self.assertEqual((sender, protected, recipient), (self.smtp["email"], self.smtp["protected"], self.email))
        self.assertEqual(subject, "Tu acceso a JuniorsControl")
        self.assertIn(self.login_url, body)
        self.assertIn("contraseña habitual", body)
        self.assertEqual(db.execute.call_count, 2)
        self.assertTrue(all(call.args[0].startswith("SELECT") for call in db.execute.call_args_list))

    def test_invitacion_pendiente_reemplaza_el_codigo(self):
        db = Mock()
        db.execute.side_effect = [Cursor(), Cursor(row=self.smtp), Cursor(), Cursor()]
        activation_url = self.login_url + "#activar"
        with patch.object(acceso, "_new_code", return_value="123456"), patch.object(acceso, "_send_code") as send:
            result = acceso.act(db, ADMIN, "invite", {"email": self.email, "role": "atencion",
                                                       "_activation_url": activation_url})
            result["_send_invite"]()
        send.assert_called_once_with(self.smtp["email"], self.smtp["protected"], self.email, "123456",
                                     activation_url=activation_url)
        db.execute.assert_any_call("DELETE FROM auth_invites WHERE email=?", (self.email,))
        query, values = db.execute.call_args.args
        self.assertTrue(query.startswith("INSERT INTO auth_invites"))
        self.assertEqual(values[:3], (self.email, "atencion", ""))
        self.assertTrue(acceso._valid_code({"digest": values[3], "attempts": 0}, {"code": "123456"}))

    def test_solo_administracion_puede_reenviar_y_la_cuenta_debe_estar_activa(self):
        db = Mock()
        payload = {"email": self.email, "_login_url": self.login_url}
        with self.assertRaises(PermissionError):
            acceso.act(db, WAITER, "invite", payload)
        db.execute.assert_not_called()
        db.execute.return_value = Cursor(row={"active": 0})
        with self.assertRaisesRegex(ValueError, "Activa la cuenta"):
            acceso.act(db, ADMIN, "invite", payload)
        db.execute.assert_called_once()
