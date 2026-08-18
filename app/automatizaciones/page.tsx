"use client";

import { APP_VERSION } from "@/lib/version";
import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { AutomationJob, AutomationKey, SystemNotification } from "@/types/news";

const intervals = [
  { value: 15, label: "Cada 15 minutos" },
  { value: 30, label: "Cada 30 minutos" },
  { value: 60, label: "Cada hora" },
  { value: 180, label: "Cada 3 horas" },
  { value: 360, label: "Cada 6 horas" },
  { value: 720, label: "Cada 12 horas" },
  { value: 1440, label: "Cada día" },
  { value: 10080, label: "Cada semana" },
];

const icons: Record<AutomationKey, string> = {
  facebook: "f",
  radar: "⌖",
  geolocation: "⌾",
  images: "▧",
  backup: "▣",
  cleanup: "⌫",
};

function dateTime(value: string | null) {
  if (!value) return "Sin ejecución";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusText(job: AutomationJob) {
  if (job.last_status === "running") return "Ejecutándose";
  if (job.last_status === "success") return "Correcta";
  if (job.last_status === "error") return "Requiere atención";
  return "Sin ejecutar";
}

export default function AutomationsPage() {
  const [jobs, setJobs] = useState<AutomationJob[]>([]);
  const [notifications, setNotifications] = useState<SystemNotification[]>([]);
  const [running, setRunning] = useState<AutomationKey | null>(null);
  const [saving, setSaving] = useState<AutomationKey | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [automationJobs, alerts] = await Promise.all([api.listAutomations(), api.listNotifications()]);
      setJobs(automationJobs);
      setNotifications(alerts);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudieron cargar las automatizaciones.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const stats = useMemo(() => ({
    active: jobs.filter((job) => job.enabled).length,
    errors: jobs.filter((job) => job.last_status === "error").length,
    unread: notifications.filter((item) => !item.is_read).length,
    completed: jobs.filter((job) => job.last_status === "success").length,
  }), [jobs, notifications]);

  async function saveJob(job: AutomationJob, changes: Partial<Pick<AutomationJob, "enabled" | "interval_minutes">>) {
    setSaving(job.key);
    setError("");
    setSuccess("");
    try {
      const updated = await api.updateAutomation(
        job.key,
        changes.enabled ?? job.enabled,
        changes.interval_minutes ?? job.interval_minutes,
      );
      setJobs((current) => current.map((item) => item.key === job.key ? updated : item));
      setSuccess(`${job.label}: configuración guardada.`);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la automatización.");
    } finally {
      setSaving(null);
    }
  }

  async function execute(job: AutomationJob) {
    setRunning(job.key);
    setError("");
    setSuccess("");
    try {
      const updated = await api.executeAutomation(job.key);
      setJobs((current) => current.map((item) => item.key === job.key ? updated : item));
      if (updated.last_status === "error") setError(`${job.label}: ${updated.last_message}`);
      else setSuccess(`${job.label}: ${updated.last_message}`);
      setNotifications(await api.listNotifications());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "La tarea no pudo ejecutarse.");
    } finally {
      setRunning(null);
    }
  }

  async function markRead() {
    await api.markNotificationsRead();
    setNotifications((current) => current.map((item) => ({ ...item, is_read: true })));
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">VERSIÓN {APP_VERSION} · OPERACIÓN AUTOMÁTICA</p><h1>Automatizaciones</h1><p>Programa tareas de monitoreo y revisa sus resultados desde un solo lugar.</p></div>
        <button className="button secondary" onClick={load}>↻ Actualizar estado</button>
      </div>

      <section className="automation-notice">
        <span>✓</span><div><strong>Control editorial protegido</strong><p>Las tareas buscan, clasifican, ubican y respaldan. Ninguna noticia se publica sin aprobación humana.</p></div>
      </section>

      <section className="stats-grid automation-stats">
        <div className="stat-card"><div className="stat-icon blue">↻</div><div><span>Activas</span><strong>{stats.active}</strong><small>De 6 automatizaciones</small></div></div>
        <div className="stat-card"><div className="stat-icon green">✓</div><div><span>Completadas</span><strong>{stats.completed}</strong><small>Última ejecución correcta</small></div></div>
        <div className="stat-card"><div className="stat-icon red">!</div><div><span>Con atención</span><strong>{stats.errors}</strong><small>Revisa el resultado</small></div></div>
        <div className="stat-card"><div className="stat-icon purple">●</div><div><span>Alertas nuevas</span><strong>{stats.unread}</strong><small>Resultados sin revisar</small></div></div>
      </section>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <section className="automation-grid">
        {loading && <div className="panel settings-loading">Cargando automatizaciones…</div>}
        {!loading && jobs.map((job) => (
          <article className={`panel automation-card ${job.enabled ? "enabled" : ""}`} key={job.key}>
            <div className="automation-card-head">
              <span className={`automation-icon ${job.key}`}>{icons[job.key]}</span>
              <div><h2>{job.label}</h2><p>{job.description}</p></div>
              <label className="switch" title={job.enabled ? "Desactivar" : "Activar"}>
                <input type="checkbox" checked={job.enabled} disabled={saving === job.key} onChange={(event) => saveJob(job, { enabled: event.target.checked })} />
                <span />
              </label>
            </div>
            <div className="automation-controls">
              <label>Frecuencia<select value={job.interval_minutes} disabled={saving === job.key} onChange={(event) => saveJob(job, { interval_minutes: Number(event.target.value) })}>{intervals.map((item) => <option value={item.value} key={item.value}>{item.label}</option>)}</select></label>
              <button className="button primary" onClick={() => execute(job)} disabled={running !== null}>{running === job.key ? "Ejecutando…" : "Ejecutar ahora"}</button>
            </div>
            <div className="automation-result">
              <span className={`job-status ${job.last_status}`}>{statusText(job)}</span>
              <div><strong>{job.last_message || "Esta tarea todavía no se ha ejecutado."}</strong><small>Última: {dateTime(job.last_run)}{job.enabled ? ` · Próxima: ${dateTime(job.next_run)}` : " · Programación desactivada"}</small></div>
            </div>
          </article>
        ))}
      </section>

      <section className="panel notifications-panel">
        <div className="panel-header"><div><h2>Historial de alertas</h2><p>Resultados de las tareas manuales y programadas.</p></div>{stats.unread > 0 && <button className="text-link" onClick={markRead}>Marcar como revisadas</button>}</div>
        <div className="notification-list">
          {notifications.length === 0 && <div className="settings-empty">Las alertas aparecerán después de ejecutar una automatización.</div>}
          {notifications.map((item) => (
            <div className={`notification-item ${item.level} ${item.is_read ? "read" : ""}`} key={item.id}>
              <span>{item.level === "success" ? "✓" : item.level === "error" ? "!" : "i"}</span>
              <div><strong>{item.title}</strong><p>{item.message}</p></div>
              <time>{dateTime(item.created_at)}</time>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}
