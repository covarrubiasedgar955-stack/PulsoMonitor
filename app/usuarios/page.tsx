"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { UserCreateInput, UserInfo, UserRecord, UserRole } from "@/types/news";

const roles: UserRole[] = ["Administrador", "Editor", "Reportero"];

function formatDate(value: string | null) {
  if (!value) return "Nunca";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function UserModal({ item, onClose, onSaved }: {
  item: UserRecord | null;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [draft, setDraft] = useState<UserCreateInput>(() => ({
    username: item?.username || "",
    name: item?.name || "",
    role: item?.role || "Reportero",
    password: "",
    active: item?.active ?? true,
  }));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (item) {
        await api.updateUser(item.id, { name: draft.name.trim(), role: draft.role, active: draft.active });
        if (draft.password) await api.updateUserPassword(item.id, draft.password);
        onSaved(draft.password ? "Usuario actualizado. Deberá iniciar sesión con su nueva contraseña." : "Usuario actualizado correctamente.");
      } else {
        await api.createUser({ ...draft, username: draft.username.trim(), name: draft.name.trim() });
        onSaved("Usuario creado correctamente.");
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar el usuario.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="user-form-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar formulario" />
      <section className="modal user-modal">
        <div className="modal-header">
          <div><p className="eyebrow">SEGURIDAD Y ACCESO</p><h2 id="user-form-title">{item ? "Editar usuario" : "Nuevo usuario"}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <label>
              Nombre completo *
              <input required minLength={2} maxLength={100} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} />
            </label>
            <label>
              Usuario *
              <input required disabled={Boolean(item)} minLength={3} maxLength={40} pattern="[A-Za-z0-9._-]+" value={draft.username} onChange={(event) => setDraft({ ...draft, username: event.target.value })} />
            </label>
            <label>
              Rol *
              <select value={draft.role} onChange={(event) => setDraft({ ...draft, role: event.target.value as UserRole })}>
                {roles.map((role) => <option key={role}>{role}</option>)}
              </select>
            </label>
            <label>
              {item ? "Nueva contraseña (opcional)" : "Contraseña *"}
              <input required={!item} type="password" minLength={10} maxLength={128} value={draft.password} onChange={(event) => setDraft({ ...draft, password: event.target.value })} autoComplete="new-password" />
            </label>
            <label className="checkbox full">
              <input type="checkbox" checked={draft.active} onChange={(event) => setDraft({ ...draft, active: event.target.checked })} />
              Usuario activo: puede iniciar sesión
            </label>
          </div>
          <div className="role-help">
            <strong>Administrador</strong> controla usuarios y configuración. <strong>Editor</strong> publica y elimina. <strong>Reportero</strong> prepara contenido.
          </div>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
            <button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar usuario"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function UsersPage() {
  const [items, setItems] = useState<UserRecord[]>([]);
  const [current, setCurrent] = useState<UserInfo | null>(null);
  const [editing, setEditing] = useState<UserRecord | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [users, me] = await Promise.all([api.listUsers(), api.currentUser()]);
      setItems(users);
      setCurrent(me);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudieron cargar los usuarios.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const totals = useMemo(() => ({
    active: items.filter((item) => item.active).length,
    admins: items.filter((item) => item.role === "Administrador" && item.active).length,
    editors: items.filter((item) => item.role === "Editor" && item.active).length,
  }), [items]);

  function open(item: UserRecord | null = null) {
    setEditing(item);
    setModalOpen(true);
    setSuccess("");
  }

  async function saved(message: string) {
    setModalOpen(false);
    setEditing(null);
    setSuccess(message);
    await load();
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">VERSIÓN 1.11.2 · EQUIPO</p><h1>Usuarios</h1><p>Controla quién entra a Pulso Monitor y qué acciones puede realizar.</p></div>
        <button className="button primary" onClick={() => open()}>+ Nuevo usuario</button>
      </div>

      <section className="stats-grid user-stats">
        <div className="stat-card"><div className="stat-icon blue">♟</div><div><span>Registrados</span><strong>{items.length}</strong><small>Cuentas del equipo</small></div></div>
        <div className="stat-card"><div className="stat-icon green">✓</div><div><span>Activos</span><strong>{totals.active}</strong><small>Con acceso al sistema</small></div></div>
        <div className="stat-card"><div className="stat-icon purple">◆</div><div><span>Administradores</span><strong>{totals.admins}</strong><small>Control completo</small></div></div>
        <div className="stat-card"><div className="stat-icon orange">✎</div><div><span>Editores</span><strong>{totals.editors}</strong><small>Publican contenido</small></div></div>
      </section>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <section className="panel users-panel">
        <div className="panel-header"><div><h2>Equipo de Pulso Monitor</h2><p>Las contraseñas se guardan cifradas y nunca se muestran.</p></div></div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Usuario</th><th>Rol</th><th>Estado</th><th>Último acceso</th><th>Acciones</th></tr></thead>
            <tbody>
              {loading && <tr><td className="empty" colSpan={5}><strong>Cargando usuarios…</strong></td></tr>}
              {!loading && items.map((item) => (
                <tr key={item.id}>
                  <td className="user-cell"><div className="user-avatar">{item.name.charAt(0).toUpperCase()}</div><div><strong>{item.name}{current?.id === item.id ? " · Tú" : ""}</strong><small>@{item.username}</small></div></td>
                  <td><span className={`role-badge role-${item.role.toLowerCase()}`}>{item.role}</span></td>
                  <td><span className={item.active ? "coverage-status active" : "coverage-status"}>{item.active ? "Activo" : "Inactivo"}</span></td>
                  <td>{formatDate(item.last_login)}</td>
                  <td><button className="button secondary compact" onClick={() => open(item)}>Editar acceso</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {modalOpen && <UserModal item={editing} onClose={() => setModalOpen(false)} onSaved={saved} />}
    </main>
  );
}
