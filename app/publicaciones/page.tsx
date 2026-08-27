"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { FacebookStatus, NewsItem } from "@/types/news";

type PublishMode = "now" | "schedule";
type PublicationTab = "ready" | "scheduled" | "published" | "all";

function dateTime(value: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function localInputValue(date: Date) {
  const local = new Date(date.getTime() - date.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function initialSchedule() {
  const date = new Date(Date.now() + 20 * 60_000);
  date.setMinutes(Math.ceil(date.getMinutes() / 5) * 5, 0, 0);
  return localInputValue(date);
}

function previewMessage(item: NewsItem) {
  const body = (item.content || item.summary).trim();
  const tags = ["PulsoTequila", ...item.tags]
    .map((tag) => tag.replace(/[^a-zA-Z0-9áéíóúüñÁÉÍÓÚÜÑ_]/g, ""))
    .filter(Boolean)
    .filter((tag, index, values) => values.findIndex((value) => value.toLowerCase() === tag.toLowerCase()) === index)
    .slice(0, 5);
  return [item.title, body.toLowerCase().startsWith(item.title.toLowerCase()) ? "" : body, tags.map((tag) => `#${tag}`).join(" ")]
    .filter(Boolean)
    .join("\n\n");
}

function statusClass(value: string) {
  return `status status-${value.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`;
}

function PublishModal({
  item,
  mode,
  pageName,
  onClose,
  onCompleted,
}: {
  item: NewsItem;
  mode: PublishMode;
  pageName: string;
  onClose: () => void;
  onCompleted: (message: string) => void;
}) {
  const [scheduledAt, setScheduledAt] = useState(initialSchedule);
  const [confirmed, setConfirmed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [imageUnavailable, setImageUnavailable] = useState(false);
  const [limits] = useState(() => ({
    minimum: localInputValue(new Date(Date.now() + 11 * 60_000)),
    maximum: localInputValue(new Date(Date.now() + 75 * 24 * 60 * 60_000)),
  }));
  const message = useMemo(() => previewMessage(item), [item]);
  const localImage = /^https?:\/\/(127\.0\.0\.1|localhost):8000\/api\/imagenes\//.test(item.image_url);
  const hasImage = Boolean(item.image_url) && !imageUnavailable;
  const missingLocalImage = localImage && imageUnavailable;

  useEffect(() => { setImageUnavailable(false); }, [item.id, item.image_url]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!confirmed || missingLocalImage) return;
    setSubmitting(true);
    setError("");
    try {
      const isoDate = mode === "schedule" ? new Date(scheduledAt).toISOString() : null;
      const result = await api.publishNewsToFacebook(item.id, isoDate);
      onCompleted(result.scheduled
        ? `La noticia quedó programada para ${dateTime(result.news.scheduled_at)}.`
        : "La noticia se publicó correctamente en Facebook.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo completar la publicación.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="publish-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar" />
      <section className="modal publish-modal">
        <div className="modal-header">
          <div><p className="eyebrow">APROBACIÓN FINAL</p><h2 id="publish-title">{mode === "schedule" ? "Programar en Facebook" : "Publicar en Facebook"}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="publication-destination"><span>f</span><div><strong>{pageName || "Página de Facebook conectada"}</strong><small>La publicación aparecerá públicamente con la identidad de esta página.</small></div></div>
          <div className="publish-preview-heading"><label className="publish-preview-label">Vista previa final</label><span>{message.length.toLocaleString("es-MX")} caracteres</span></div>
          <article className="facebook-preview-card">
            <header><span className="facebook-preview-avatar">f</span><div><strong>{pageName || "Pulso Tequila"}</strong><small>{mode === "schedule" ? "Publicación programada" : "Publicación inmediata"} · 🌐</small></div></header>
            <pre className="publish-preview">{message}</pre>
            {hasImage && <img src={item.image_url} alt={`Fotografía que acompañará: ${item.title}`} onError={() => setImageUnavailable(true)} />}
            {!hasImage && <div className="facebook-preview-no-image"><strong>Se publicará sin fotografía</strong><span>Facebook mostrará el texto y, cuando exista, el enlace de la fuente original.</span></div>}
          </article>
          {missingLocalImage && <div className="alert error">La fotografía guardada ya no está disponible en esta computadora. Regresa a Revisión editorial y carga nuevamente el archivo antes de publicar.</div>}
          {!item.image_url && <div className="alert warning">Esta noticia no tiene fotografía. Puedes continuar y publicarla únicamente con texto.</div>}
          {mode === "schedule" && (
            <label className="schedule-field">Fecha y hora de publicación
              <input type="datetime-local" required min={limits.minimum} max={limits.maximum} value={scheduledAt} onChange={(event) => setScheduledAt(event.target.value)} />
              <small>Meta permite programar entre 10 minutos y 75 días.</small>
            </label>
          )}
          <label className="publish-confirm"><input type="checkbox" disabled={missingLocalImage} checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} /><span>Confirmo que revisé la fotografía, el título, el contenido y las etiquetas, y autorizo enviarlos a Facebook.</span></label>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Volver</button><button className="button facebook-button" disabled={!confirmed || submitting || missingLocalImage}>{submitting ? "Enviando a Meta…" : mode === "schedule" ? "Confirmar programación" : "Publicar ahora"}</button></div>
        </form>
      </section>
    </div>
  );
}

export default function PublicationsPage() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [facebook, setFacebook] = useState<FacebookStatus | null>(null);
  const [tab, setTab] = useState<PublicationTab>("ready");
  const [selected, setSelected] = useState<{ item: NewsItem; mode: PublishMode } | null>(null);
  const [loading, setLoading] = useState(true);
  const [cancelling, setCancelling] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [news, facebookStatus] = await Promise.all([api.listNews({ limit: 100 }), api.facebookStatus()]);
      setItems(news.items);
      setFacebook(facebookStatus);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar el módulo de publicaciones.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const ready = items.filter((item) => !item.facebook_post_id && item.editorial_state === "Aprobada" && ["Pendiente", "En revisión", "Programada"].includes(item.status));
  const scheduled = items.filter((item) => item.status === "Programada" && Boolean(item.facebook_post_id));
  const published = items.filter((item) => item.status === "Publicada");
  const visible = tab === "ready" ? ready : tab === "scheduled" ? scheduled : tab === "published" ? published : items.filter((item) => item.status !== "Archivada");

  async function cancelSchedule(item: NewsItem) {
    if (!window.confirm(`¿Cancelar la publicación programada “${item.title}”? También se eliminará de la programación de Facebook.`)) return;
    setCancelling(item.id);
    setError("");
    setMessage("");
    try {
      await api.cancelFacebookSchedule(item.id);
      setMessage("La programación se canceló y la noticia volvió a Pendiente.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cancelar la programación.");
    } finally {
      setCancelling(null);
    }
  }

  async function completed(text: string) {
    setSelected(null);
    setMessage(text);
    await load();
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">FASE 6 · DISTRIBUCIÓN</p><h1>Publicaciones</h1><p>Aprueba, programa y publica las noticias de Pulso Tequila.</p></div>
        <Link href="/revision" className="button secondary">Revisión editorial</Link>
      </div>

      {!loading && !facebook?.connected && <div className="alert error">Primero conecta tu página en <Link href="/facebook">Facebook →</Link></div>}
      {facebook?.connected && <div className="publication-connection"><span>f</span><div><strong>{facebook.page_name}</strong><small>Conexión activa. Cada publicación requiere tu confirmación antes de enviarse.</small></div></div>}
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <section className="stats-grid publication-stats" aria-label="Estado de publicaciones">
        <article className="stat-card"><div className="stat-icon orange">◷</div><div><span>Aprobadas</span><strong>{ready.length}</strong><small>listas para publicar</small></div></article>
        <article className="stat-card"><div className="stat-icon blue">◫</div><div><span>Programadas</span><strong>{scheduled.length}</strong><small>administradas por Meta</small></div></article>
        <article className="stat-card"><div className="stat-icon green">✓</div><div><span>Publicadas</span><strong>{published.length}</strong><small>historial editorial</small></div></article>
      </section>

      <section className="panel publications-panel">
        <div className="panel-header publications-header"><div><h2>Cola editorial</h2><p>Nada se publica sin tu confirmación final.</p></div><div className="publication-tabs"><button className={tab === "ready" ? "active" : ""} onClick={() => setTab("ready")}>Listas</button><button className={tab === "scheduled" ? "active" : ""} onClick={() => setTab("scheduled")}>Programadas</button><button className={tab === "published" ? "active" : ""} onClick={() => setTab("published")}>Publicadas</button><button className={tab === "all" ? "active" : ""} onClick={() => setTab("all")}>Todas</button></div></div>
        <div className="publication-list">
          {visible.map((item) => {
            const isScheduled = item.status === "Programada" && Boolean(item.facebook_post_id);
            const canPublish = !item.facebook_post_id && item.editorial_state === "Aprobada" && ["Pendiente", "En revisión", "Programada"].includes(item.status);
            return (
              <article className="publication-card" key={item.id}>
                <div className="publication-card-main"><div><span className={statusClass(item.status)}>{item.status}</span><span className="tag">{item.category}</span></div><h3>{item.title}</h3><p>{item.summary || item.content}</p><small>{item.source} · {item.municipality}</small></div>
                <div className="publication-card-time"><span>{isScheduled ? "Se publicará" : item.status === "Publicada" ? "Publicada" : "Actualizada"}</span><strong>{dateTime(item.scheduled_at || item.published_at || item.updated_at)}</strong></div>
                <div className="publication-actions">
                  {canPublish && <><button className="button facebook-button" disabled={!facebook?.connected} onClick={() => setSelected({ item, mode: "now" })}>Publicar ahora</button><button className="button secondary" disabled={!facebook?.connected} onClick={() => setSelected({ item, mode: "schedule" })}>Programar</button></>}
                  {isScheduled && <button className="button danger-outline" disabled={cancelling === item.id} onClick={() => cancelSchedule(item)}>{cancelling === item.id ? "Cancelando…" : "Cancelar programación"}</button>}
                  {item.status === "Publicada" && item.facebook_post_id && <a className="button secondary" href={`https://www.facebook.com/${item.facebook_post_id}`} target="_blank" rel="noreferrer">Ver en Facebook ↗</a>}
                  {item.status === "Publicada" && !item.facebook_post_id && <span className="manual-publication">Publicada fuera de Pulso Monitor</span>}
                </div>
              </article>
            );
          })}
          {loading && <div className="radar-empty small"><span>Cargando publicaciones…</span></div>}
          {!loading && visible.length === 0 && <div className="radar-empty small"><div>✓</div><strong>No hay contenido en esta sección</strong><span>Las noticias aparecerán aquí conforme avance el flujo editorial.</span></div>}
        </div>
      </section>
      {selected && <PublishModal item={selected.item} mode={selected.mode} pageName={facebook?.page_name || "Pulso Tequila"} onClose={() => setSelected(null)} onCompleted={completed} />}
    </main>
  );
}
