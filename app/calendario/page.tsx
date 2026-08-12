"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { CalendarItem, CalendarResponse } from "@/types/news";

const weekdays = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];

function dayKey(value: Date | string) {
  const date = typeof value === "string" ? new Date(value) : value;
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function localInputValue(value: string) {
  const date = new Date(value);
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function eventTime(value: string) {
  return new Intl.DateTimeFormat("es-MX", { hour: "numeric", minute: "2-digit" }).format(new Date(value));
}

function fullDate(value: Date) {
  return new Intl.DateTimeFormat("es-MX", { weekday: "long", day: "numeric", month: "long" }).format(value);
}

function statusClass(value: string) {
  return `status status-${value.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`;
}

function PlanModal({ item, onClose, onSaved }: {
  item: CalendarItem;
  onClose: () => void;
  onSaved: (message: string) => void;
}) {
  const [plannedAt, setPlannedAt] = useState(() => localInputValue(item.planned_at || item.event_at));
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await api.planNews(item.id, new Date(plannedAt).toISOString());
      onSaved("La fecha editorial quedó actualizada.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la fecha.");
    } finally {
      setSaving(false);
    }
  }

  async function clearPlan() {
    setSaving(true);
    setError("");
    try {
      await api.planNews(item.id, null);
      onSaved("La noticia se retiró de la planeación y volvió a su fecha de creación.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo retirar la planeación.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="calendar-plan-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar" />
      <section className="modal calendar-plan-modal">
        <div className="modal-header">
          <div><p className="eyebrow">PLANEACIÓN EDITORIAL</p><h2 id="calendar-plan-title">Asignar fecha y hora</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="calendar-plan-news"><span>▤</span><div><strong>{item.title}</strong><small>{item.municipality} · {item.category}</small></div></div>
          <label className="schedule-field">Fecha editorial
            <input type="datetime-local" required value={plannedAt} onChange={(event) => setPlannedAt(event.target.value)} />
            <small>Esta fecha organiza el trabajo interno; no publica automáticamente en Facebook.</small>
          </label>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions calendar-plan-actions">
            {item.planned_at && <button type="button" className="button danger-outline" onClick={clearPlan} disabled={saving}>Retirar del plan</button>}
            <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
            <button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar fecha"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function CalendarPage() {
  const [month, setMonth] = useState(() => new Date(new Date().getFullYear(), new Date().getMonth(), 1));
  const [data, setData] = useState<CalendarResponse | null>(null);
  const [selectedDay, setSelectedDay] = useState(() => dayKey(new Date()));
  const [selectedItem, setSelectedItem] = useState<CalendarItem | null>(null);
  const [planning, setPlanning] = useState<CalendarItem | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const days = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1);
    const start = new Date(first);
    start.setDate(first.getDate() - first.getDay());
    return Array.from({ length: 42 }, (_, index) => {
      const value = new Date(start);
      value.setDate(start.getDate() + index);
      return value;
    });
  }, [month]);

  const load = useCallback(async () => {
    const start = new Date(days[0]);
    start.setHours(0, 0, 0, 0);
    const end = new Date(days[days.length - 1]);
    end.setDate(end.getDate() + 1);
    end.setHours(0, 0, 0, 0);
    setLoading(true);
    setError("");
    try {
      setData(await api.calendar(start.toISOString(), end.toISOString()));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar el calendario.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const grouped = useMemo(() => {
    const result = new Map<string, CalendarItem[]>();
    for (const item of data?.items || []) {
      const key = dayKey(item.event_at);
      result.set(key, [...(result.get(key) || []), item]);
    }
    return result;
  }, [data]);

  const selectedDate = days.find((day) => dayKey(day) === selectedDay) || days[0];
  const selectedItems = grouped.get(selectedDay) || [];
  const monthLabel = new Intl.DateTimeFormat("es-MX", { month: "long", year: "numeric" }).format(month);
  const today = dayKey(new Date());

  function moveMonth(offset: number) {
    const next = new Date(month.getFullYear(), month.getMonth() + offset, 1);
    setMonth(next);
    setSelectedDay(dayKey(next));
    setSelectedItem(null);
    setMessage("");
  }

  function goToday() {
    const now = new Date();
    setMonth(new Date(now.getFullYear(), now.getMonth(), 1));
    setSelectedDay(dayKey(now));
    setSelectedItem(null);
  }

  async function planned(text: string) {
    setPlanning(null);
    setSelectedItem(null);
    setMessage(text);
    await load();
  }

  return (
    <main>
      <div className="page-heading calendar-heading">
        <div><p className="eyebrow">VERSIÓN 1.3 · PLANEACIÓN</p><h1>Calendario editorial</h1><p>Organiza la cobertura, programación y publicaciones de Pulso Tequila.</p></div>
        <div className="heading-actions"><button className="button secondary" onClick={goToday}>Hoy</button><Link href="/publicaciones" className="button primary">Programar en Facebook</Link></div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <section className="stats-grid calendar-stats">
        <article className="stat-card"><div className="stat-icon blue">▦</div><div><span>En agenda</span><strong>{loading ? "—" : data?.total || 0}</strong><small>periodo visible</small></div></article>
        <article className="stat-card"><div className="stat-icon orange">◷</div><div><span>Pendientes</span><strong>{loading ? "—" : data?.pending || 0}</strong><small>requieren trabajo editorial</small></div></article>
        <article className="stat-card"><div className="stat-icon green">✓</div><div><span>Publicadas</span><strong>{loading ? "—" : data?.published || 0}</strong><small>historial del periodo</small></div></article>
        <article className="stat-card"><div className="stat-icon red">!</div><div><span>Urgentes</span><strong>{loading ? "—" : data?.urgent || 0}</strong><small>prioridad inmediata</small></div></article>
      </section>

      <section className="calendar-layout panel">
        <div className="calendar-main">
          <div className="calendar-toolbar">
            <button onClick={() => moveMonth(-1)} aria-label="Mes anterior">←</button>
            <h2>{monthLabel}</h2>
            <button onClick={() => moveMonth(1)} aria-label="Mes siguiente">→</button>
          </div>
          <div className="calendar-weekdays">{weekdays.map((day) => <span key={day}>{day}</span>)}</div>
          <div className="calendar-grid">
            {days.map((day) => {
              const key = dayKey(day);
              const items = grouped.get(key) || [];
              const outside = day.getMonth() !== month.getMonth();
              return (
                <button className={`calendar-day ${outside ? "outside" : ""} ${key === today ? "today" : ""} ${key === selectedDay ? "selected" : ""}`} key={key} onClick={() => { setSelectedDay(key); setSelectedItem(null); }}>
                  <span className="calendar-day-number">{day.getDate()}</span>
                  <div className="calendar-events">
                    {items.slice(0, 3).map((item) => <span className={`calendar-event event-${item.status.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`} key={item.id}><i />{item.title}</span>)}
                    {items.length > 3 && <small>+{items.length - 3} más</small>}
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        <aside className="calendar-agenda">
          <div className="calendar-agenda-head"><p>AGENDA DEL DÍA</p><h2>{fullDate(selectedDate)}</h2><span>{selectedItems.length} contenido{selectedItems.length === 1 ? "" : "s"}</span></div>
          <div className="calendar-agenda-list">
            {selectedItems.map((item) => (
              <button className={`calendar-agenda-item ${selectedItem?.id === item.id ? "active" : ""}`} key={item.id} onClick={() => setSelectedItem(item)}>
                <time>{eventTime(item.event_at)}</time>
                <div><strong>{item.title}</strong><small>{item.municipality} · {item.category}</small></div>
                <span className={statusClass(item.status)}>{item.status}</span>
              </button>
            ))}
            {!loading && selectedItems.length === 0 && <div className="calendar-empty"><span>▦</span><strong>Sin contenido</strong><p>Selecciona otra fecha o planea una noticia desde un día con actividad.</p></div>}
          </div>
          {selectedItem && (
            <div className="calendar-detail">
              <div><span className={`priority priority-${selectedItem.priority.toLowerCase()}`}>{selectedItem.priority}</span><span className="tag">{selectedItem.date_source === "scheduled" ? "Programación Meta" : selectedItem.date_source === "published" ? "Fecha publicada" : selectedItem.date_source === "planned" ? "Plan editorial" : "Fecha de creación"}</span></div>
              <h3>{selectedItem.title}</h3><p>{selectedItem.summary || "Sin resumen editorial."}</p>
              <div className="calendar-detail-actions">
                {!selectedItem.facebook_post_id && <button className="button secondary" onClick={() => setPlanning(selectedItem)}>Cambiar fecha</button>}
                <Link className="button primary" href="/publicaciones">Abrir publicaciones</Link>
              </div>
            </div>
          )}
        </aside>
      </section>
      <div className="calendar-legend"><span><i className="pending" /> Pendiente</span><span><i className="review" /> En revisión</span><span><i className="scheduled" /> Programada</span><span><i className="published" /> Publicada</span></div>
      {planning && <PlanModal item={planning} onClose={() => setPlanning(null)} onSaved={planned} />}
    </main>
  );
}
