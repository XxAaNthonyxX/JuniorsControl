(() => {
  const roles = [
    ["atencion", "Atención"],
    ["caja", "Caja"],
    ["area", "Responsable de área"],
    ["recepcion", "Recepción"],
    ["admin", "Administración"],
  ];
  const roleNames = Object.fromEntries(roles);

  function assignmentFields(record = {}) {
    const areas = [...new Set([...(S.areas || []), record.area].filter(Boolean))];
    return select("role", "Rol", roles, record.role || "atencion")
      + select("area", "Área asignada", [["", "Sin asignar"], ...areas.map(area => [area, area])], record.area || "")
      + '<p class="muted full">Asigna un área a cada responsable. Para el hornero, elige Recepción y su área de Cocina, Parrilla u Horno. Podrá validar entregas y registrar preparaciones de su área. Para el personal de limpieza, elige Recepción y Limpieza.</p>';
  }

  function configureGmail() {
    const smtp = S.smtp || {};
    const fields = input("email", "Correo remitente de Gmail o Google Workspace", "email", smtp.email || "",
      'required maxlength="254" autocomplete="off"')
      + input("password", smtp.configured ? "Nueva contraseña de aplicación (opcional)" : "Contraseña de aplicación",
        "password", "", (smtp.configured ? "" : "required ") + 'maxlength="32" autocomplete="new-password"')
      + '<p class="muted full">Activa la verificación en dos pasos en Google y genera una contraseña de aplicación de 16 caracteres. '
      + '<a href="https://support.google.com/accounts/answer/185833?hl=es" target="_blank" rel="noopener noreferrer">Ver las instrucciones de Google</a></p>';
    modal("Configurar Gmail", fields, values => run("smtp_save", values, "Remitente guardado."));
  }

  function invitePerson(record = {}) {
    const fields = input("email", "Correo de la persona", "email", record.email || "",
      'required maxlength="254" autocomplete="off"') + assignmentFields(record)
      + '<p class="muted full">Junior’s enviará un enlace de activación y un código de 8 dígitos válido por 24 horas. Al reenviar, el código anterior caduca.</p>';
    modal(record.email ? "Reenviar invitación" : "Invitar a una persona", fields,
      values => run("invite", values, "Invitación enviada por Gmail."), "Enviar invitación");
  }

  function editPerson(person) {
    const fields = '<p class="full"><strong>' + h(person.name) + '</strong><br><span class="muted">'
      + h(person.email) + '</span></p>' + assignmentFields(person)
      + select("active", "Estado de la cuenta", [["1", "Activa"], ["0", "Desactivada"]], String(Number(person.active)));
    modal("Editar cuenta", fields, values => run("user_update", { ...values, id: person.id }, "Cuenta actualizada."));
  }

  function deletePerson(person) {
    modal("Eliminar cuenta", "<p>Se cerrarán las sesiones de <strong>" + h(person.email)
      + "</strong>. Para volver a usar este correo se necesitará una invitación nueva. Se conservará el historial de operaciones.</p>",
      () => run("user_delete", {id: person.id}, "Cuenta eliminada."), "Eliminar cuenta");
  }

  pages.equipo = () => {
    const smtp = S.smtp || {};
    const accounts = (S.users || []).map(person => [
      '<strong>' + h(person.name) + '</strong><br><span class="muted">' + h(person.code) + '</span>',
      h(person.email), h(roleNames[person.role] || person.role), h(person.area || "—"),
      badge(person.active ? "Activa" : "Desactivada"), button("Editar", () => editPerson(person))
        + (person.id === S.user.id ? "" : " " + button("Eliminar", () => deletePerson(person)))
    ]);
    const pending = (S.invitations || []).map(record => [
      h(record.email), h(roleNames[record.role] || record.role), h(record.area || "—"),
      h(record.expires), button("Reenviar", () => invitePerson(record)),
    ]);
    const gmail = smtp.configured
      ? '<p><strong>' + h(smtp.email) + '</strong></p><p class="muted">Remitente de los códigos de registro.</p>'
      : '<p class="muted">Configura un remitente de Gmail para invitar al personal.</p>';
    return '<div class="stack">'
      + panel("Equipo", table(["Persona", "Correo", "Rol", "Área", "Estado", ""], accounts, "Aún no hay cuentas."),
        smtp.configured ? button("Invitar persona", () => invitePerson(), "primary") : "")
      + panel("Invitaciones pendientes", table(["Correo", "Rol", "Área", "Vence", ""], pending, "No hay invitaciones pendientes."))
      + panel("Correo de registro", gmail, button("Configurar Gmail", configureGmail, smtp.configured ? "secondary" : "primary"))
      + '</div>';
  };
})();
