"use client";

import { APP_VERSION } from "@/lib/version";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RadarItem, RadarSource, RadarSourceInput, RadarStats } from "@/types/news";

const categories = ["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad"];
const emptyStats: RadarStats = { sources: 0, active_sources: 0, findings: 0, pending: 0, imported: 0 };
const emptySource: RadarSourceInput = { name: "", url: "", municipality: "Tequila", category: "General", enabled: true };

function dateTime(value: string | null) {
  if (!value) return "Aún no escaneada";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function SourceModal({ item, onClose, onSaved }: { item: RadarSource | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<RadarSourceInput>(item ? {
    name: item.name,
    url: item.url,
    municipality: item.municipality,
    category: item.category,
    enabled: item.enabled,
  } : emptySource);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (item) await api.updateRadarSource(item.id, draft);
      else await api.createRadarSource(draft);
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la fuente.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="source-form-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar formulario" />
      <section className="modal radar-source-modal">
        <div className="modal-header">
          <div><p className="eyebrow">RADAR DE FUENTES</p><h2 id="source-form-title">{item ? "Editar fuente" : "Agregar fuente"}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="full">Nombre de la fuente *<input disabled={Boolean(item?.managed)} required minLength={3} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Ej. Gobierno de Tequila" /></label>
            <label className="full">Dirección RSS o Atom *<input disabled={Boolean(item?.managed)} required type="url" value={draft.url} onChange={(event) => setDraft({ ...draft, url: event.target.value })} placeholder="https://sitio.mx/noticias/feed" /></label>
            <label>Municipio<input disabled={Boolean(item?.managed)} value={draft.municipality} onChange={(event) => setDraft({ ...draft, municipality: event.target.value })} /></label>
            <label>Categoría<select disabled={Boolean(item?.managed)} value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })}>{categories.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label className="checkbox full"><input type="checkbox" checked={draft.enabled} onChange={(event) => setDraft({ ...draft, enabled: event.target.checked })} /> Escanear esta fuente cuando use “Escanear todas”</label>
          </div>
          <div className="source-help"><strong>{item?.managed ? "Cobertura administrada por Pulso Monitor" : "¿Qué dirección debo pegar?"}</strong><span>{item?.managed ? "Puedes activar o pausar este municipio. La búsqueda y la importación de borradores son automáticas." : "La dirección del canal RSS o Atom publicado por el sitio. El Radar no evade accesos ni consulta perfiles privados."}</span></div>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar fuente"}</button></div>
        </form>
      </section>
    </div>
  );
}

export default function RadarPage() {
  const [sources, setSources] = useState<RadarSource[]>([]);
  const [items, setItems] = useState<RadarItem[]>([]);
  const [stats, setStats] = useState<RadarStats>(emptyStats);
  const [pendingOnly, setPendingOnly] = useState(true);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState<number | "all" | null>(null);
  const [importing, setImporting] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<RadarSource | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [sourceData, itemData, statsData] = await Promise.all([
        api.listRadarSources(), api.listRadarItems(pendingOnly), api.radarStats(),
      ]);
      setSources(sourceData);
      setItems(itemData.items);
      setStats(statsData);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible cargar el Radar.");
    } finally {
      setLoading(false);
    }
  }, [pendingOnly]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function scan(sourceId?: number) {
    setScanning(sourceId ?? "all");
    setError("");
    setMessage("");
    try {
      const result = await api.scanRadar(sourceId);
      const cleaned = result.cleaned ? ` · ${result.cleaned} antiguo${result.cleaned === 1 ? "" : "s"} eliminado${result.cleaned === 1 ? "" : "s"}` : "";
      const filtered = result.filtered ? ` · ${result.filtered} fuera de cobertura` : "";
      const duplicates = result.duplicates ? ` · ${result.duplicates} duplicado${result.duplicates === 1 ? "" : "s"} bloqueado${result.duplicates === 1 ? "" : "s"}` : "";
      setMessage(`Escaneo terminado: ${result.detected} publicación${result.detected === 1 ? "" : "es"} útil${result.detected === 1 ? "" : "es"} · ${result.imported} borrador${result.imported === 1 ? " creado" : "es creados"}${filtered}${duplicates}${cleaned}.`);
      if (result.errors.length) setError(result.errors.join(" · "));
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo escanear la fuente.");
    } finally {
      setScanning(null);
    }
  }

  async function importItem(item: RadarItem) {
    setImporting(item.id);
    setError("");
    setMessage("");
    try {
      await api.importRadarItem(item.id);
      setMessage("El hallazgo se guardó como noticia pendiente.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo importar el hallazgo.");
    } finally {
      setImporting(null);
    }
  }

  async function removeSource(source: RadarSource) {
    if (!window.confirm(`¿Eliminar la fuente “${source.name}” y todos sus hallazgos?`)) return;
    try {
      await api.deleteRadarSource(source.id);
      setMessage("La fuente fue eliminada del Radar.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo eliminar la fuente.");
    }
  }

  function addSource() { setEditing(null); setModalOpen(true); }
  function editSource(source: RadarSource) { setEditing(source); setModalOpen(true); }
  function closeModal() { setModalOpen(false); setEditing(null); }
  async function savedSource() { closeModal(); setMessage("La fuente quedó guardada."); await load(); }

  return (
    <main>
      <div className="page-heading radar-heading">
        <div><p className="eyebrow">VERSIÓN {APP_VERSION} · COBERTURA LOCAL</p><h1>Radar</h1><p>Busca automáticamente noticias de Tequila y municipios cercanos.</p></div>
        <div className="heading-actions"><button className="button secondary" onClick={addSource}>+ Agregar fuente</button><button className="button primary" onClick={() => scan()} disabled={scanning !== null || sources.length === 0}>{scanning === "all" ? "Escaneando…" : "⌖ Escanear todas"}</button></div>
      </div>

      <div className="stats-grid radar-stats">
        <div className="stat-card"><div className="stat-icon blue">⌖</div><div><span>Fuentes activas</span><strong>{stats.active_sources}</strong><small>{stats.sources} registradas</small></div></div>
        <div className="stat-card"><div className="stat-icon orange">◉</div><div><span>Por revisar</span><strong>{stats.pending}</strong><small>hallazgos nuevos</small></div></div>
        <div className="stat-card"><div className="stat-icon green">✓</div><div><span>Importadas</span><strong>{stats.imported}</strong><small>en el módulo Noticias</small></div></div>
        <div className="stat-card"><div className="stat-icon blue">▤</div><div><span>Total detectadas</span><strong>{stats.findings}</strong><small>sin duplicados</small></div></div>
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message} {message.includes("noticia") && <Link href="/noticias">Ir a Noticias →</Link>}</div>}

      <div className="radar-grid">
        <section className="panel radar-sources">
          <div className="panel-header"><div><h2>Fuentes</h2><p>Canales RSS y Atom que autorizaste.</p></div><button className="text-link" onClick={addSource}>Agregar</button></div>
          <div className="source-list">
            {sources.map((source) => (
              <article className="source-card" key={source.id}>
                <div className="source-card-top"><div className={`source-signal ${source.enabled ? "on" : "off"}`} /><div><strong>{source.name}</strong><span>{source.municipality} · {source.category}{source.managed ? " · Automática" : ""}</span></div><span className="source-count">{source.pending}</span></div>
                <div className="source-meta"><span>{dateTime(source.last_scan)}</span>{source.last_error && <em title={source.last_error}>Atención ({source.consecutive_errors}/3): {source.last_error}</em>}</div>
                <div className="source-actions"><button onClick={() => scan(source.id)} disabled={scanning !== null}>{scanning === source.id ? "Escaneando…" : "Escanear"}</button><button onClick={() => editSource(source)}>{source.managed ? "Activar / pausar" : "Editar"}</button>{!source.managed && <button className="danger" onClick={() => removeSource(source)}>Eliminar</button>}</div>
              </article>
            ))}
            {!loading && sources.length === 0 && <div className="radar-empty small"><div>⌖</div><strong>Aún no hay fuentes</strong><span>Agrega el primer canal RSS o Atom para comenzar.</span><button className="button primary" onClick={addSource}>Agregar fuente</button></div>}
          </div>
        </section>

        <section className="panel radar-findings">
          <div className="panel-header findings-header"><div><h2>Hallazgos</h2><p>Publicaciones detectadas por el Radar.</p></div><div className="radar-tabs"><button className={pendingOnly ? "active" : ""} onClick={() => setPendingOnly(true)}>Por revisar</button><button className={!pendingOnly ? "active" : ""} onClick={() => setPendingOnly(false)}>Todos</button></div></div>
          <div className="finding-list">
            {items.map((item) => (
              <article className="finding-card" key={item.id}>
                <div className="finding-main"><div className="finding-badges"><span className="tag">{item.source_name}</span><span>{item.municipality}</span><span className="tag">Relevancia {item.relevance_level} · {item.relevance_score}</span><span>{dateTime(item.published_at || item.detected_at)}</span></div><h3>{item.title}</h3>{item.summary && <p>{item.summary}</p>}{item.relevance_reason && <small>Por qué se seleccionó: {item.relevance_reason}</small>}</div>
                <div className="finding-actions">{item.url && <a className="button secondary" href={item.url} target="_blank" rel="noreferrer">Abrir fuente ↗</a>}{item.imported_news_id ? <span className="imported-badge">✓ Importada</span> : <button className="button primary" onClick={() => importItem(item)} disabled={importing === item.id}>{importing === item.id ? "Importando…" : "Importar a Noticias"}</button>}</div>
              </article>
            ))}
            {loading && <div className="radar-empty"><span>Cargando Radar…</span></div>}
            {!loading && items.length === 0 && <div className="radar-empty"><div>◉</div><strong>{sources.length ? "No hay hallazgos por revisar" : "El Radar está listo"}</strong><span>{sources.length ? "Escanea tus fuentes para buscar publicaciones nuevas." : "Agrega una fuente autorizada para comenzar a detectar contenido."}</span></div>}
          </div>
        </section>
      </div>
      {modalOpen && <SourceModal item={editing} onClose={closeModal} onSaved={savedSource} />}
    </main>
  );
}
