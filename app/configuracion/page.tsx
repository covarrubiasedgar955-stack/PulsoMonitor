"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { ActivityItem, AppSettings, BackupInfo } from "@/types/news";

const initialSettings: AppSettings = {
  media_name: "Pulso Tequila",
  tagline: "Centro inteligente de monitoreo de noticias",
  default_municipality: "Tequila",
  contact_email: "",
  updated_at: "",
};

function dateTime(value: string) {
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function fileSize(bytes: number) {
  if (bytes < 1024 * 1024) return `${Math.max(1, Math.round(bytes / 1024))} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<AppSettings>(initialSettings);
  const [activity, setActivity] = useState<ActivityItem[]>([]);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [backingUp, setBackingUp] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [configuration, log, backupList] = await Promise.all([
        api.getSettings(), api.listActivity(), api.listBackups(),
      ]);
      setSettings(configuration);
      setActivity(log);
      setBackups(backupList);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar la configuración.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function save(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setSuccess("");
    try {
      setSettings(await api.updateSettings(settings));
      setSuccess("La configuración se guardó correctamente.");
      setActivity(await api.listActivity());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la configuración.");
    } finally {
      setSaving(false);
    }
  }

  async function createBackup() {
    setBackingUp(true);
    setError("");
    setSuccess("");
    try {
      const created = await api.createBackup();
      setSuccess(`Respaldo creado: ${created.name}`);
      const [backupList, log] = await Promise.all([api.listBackups(), api.listActivity()]);
      setBackups(backupList);
      setActivity(log);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo crear el respaldo.");
    } finally {
      setBackingUp(false);
    }
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">VERSIÓN 1.0 · ADMINISTRACIÓN</p><h1>Configuración</h1><p>Personaliza el medio, revisa la actividad y protege la base de datos.</p></div>
        <button className="button primary" onClick={createBackup} disabled={backingUp}>{backingUp ? "Creando…" : "＋ Crear respaldo"}</button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <div className="settings-grid">
        <section className="panel settings-profile">
          <div className="panel-header"><div><h2>Identidad del medio</h2><p>Datos generales usados por el equipo editorial.</p></div></div>
          {loading ? <div className="settings-loading">Cargando configuración…</div> : (
            <form className="settings-form" onSubmit={save}>
              <label>Nombre del medio<input required minLength={2} maxLength={100} value={settings.media_name} onChange={(event) => setSettings({ ...settings, media_name: event.target.value })} /></label>
              <label>Lema o descripción<input required minLength={2} maxLength={180} value={settings.tagline} onChange={(event) => setSettings({ ...settings, tagline: event.target.value })} /></label>
              <div className="settings-row">
                <label>Municipio principal<input required minLength={2} maxLength={100} value={settings.default_municipality} onChange={(event) => setSettings({ ...settings, default_municipality: event.target.value })} /></label>
                <label>Correo de contacto<input type="email" maxLength={180} value={settings.contact_email} onChange={(event) => setSettings({ ...settings, contact_email: event.target.value })} placeholder="redaccion@ejemplo.com" /></label>
              </div>
              <button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar cambios"}</button>
            </form>
          )}
        </section>

        <section className="panel backup-panel">
          <div className="panel-header"><div><h2>Respaldos</h2><p>Copias seguras de noticias, usuarios y configuración.</p></div><span className="coverage-badge">{backups.length} copias</span></div>
          <div className="backup-notice"><span>✓</span><div><strong>Protección automática de SQLite</strong><p>Se conservan las 10 copias más recientes en la carpeta backend\backups.</p></div></div>
          <div className="backup-list">
            {backups.length === 0 && <div className="settings-empty">Aún no hay respaldos. Crea el primero antes de un cambio importante.</div>}
            {backups.map((backup) => (
              <div className="backup-item" key={backup.name}>
                <span className="backup-icon">▣</span>
                <div><strong>{backup.name}</strong><small>{dateTime(backup.created_at)} · {fileSize(backup.size)}</small></div>
                <button className="button secondary compact" onClick={() => api.downloadBackup(backup.name)}>Descargar</button>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="panel activity-panel">
        <div className="panel-header"><div><h2>Actividad reciente</h2><p>Historial de accesos y acciones administrativas importantes.</p></div><button className="text-link" onClick={load}>Actualizar</button></div>
        <div className="activity-list">
          {activity.length === 0 && <div className="settings-empty">Todavía no hay actividad registrada.</div>}
          {activity.map((item) => (
            <div className="activity-item" key={item.id}>
              <span className="activity-dot" />
              <div><strong>{item.user_name || "Sistema"} · {item.action}</strong><small>{item.detail || item.entity}{item.entity_id ? ` · ${item.entity_id}` : ""}</small></div>
              <time>{dateTime(item.created_at)}</time>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
