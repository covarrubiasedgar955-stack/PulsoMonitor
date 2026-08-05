"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import IncidentMap, { type MapPosition } from "@/components/IncidentMap";
import { api } from "@/lib/api";
import type { MapIncident, MapStats, Municipality, NewsItem, NewsPriority, NewsStatus } from "@/types/news";

const emptyStats: MapStats = { news: 0, mapped: 0, unmapped: 0, urgent: 0 };
const statuses: NewsStatus[] = ["Pendiente", "En revisión", "Programada", "Publicada"];
const priorities: NewsPriority[] = ["Baja", "Media", "Alta", "Urgente"];

function statusClass(value: string) {
  return `status status-${value.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`;
}

function dateTime(value: string) {
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function LocationModal({
  news,
  initial,
  onClose,
  onSaved,
}: {
  news: NewsItem[];
  initial: NewsItem | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const candidates = useMemo(() => [...news].sort((a, b) => Number(a.latitude !== null) - Number(b.latitude !== null)), [news]);
  const first = initial || candidates[0] || null;
  const [newsId, setNewsId] = useState(first?.id || 0);
  const [location, setLocation] = useState(first?.location || "");
  const [latitude, setLatitude] = useState(first?.latitude?.toString() || "");
  const [longitude, setLongitude] = useState(first?.longitude?.toString() || "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  const latitudeNumber = Number(latitude);
  const longitudeNumber = Number(longitude);
  const position: MapPosition | null = latitude !== "" && longitude !== "" && Number.isFinite(latitudeNumber) && Number.isFinite(longitudeNumber)
    ? { latitude: latitudeNumber, longitude: longitudeNumber }
    : null;

  function choose(value: string) {
    const selected = candidates.find((item) => item.id === Number(value));
    setNewsId(selected?.id || 0);
    setLocation(selected?.location || "");
    setLatitude(selected?.latitude?.toString() || "");
    setLongitude(selected?.longitude?.toString() || "");
    setError("");
  }

  function pick(point: MapPosition) {
    setLatitude(point.latitude.toFixed(6));
    setLongitude(point.longitude.toFixed(6));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!newsId || !position) {
      setError("Selecciona una noticia y marca su ubicación en el mapa.");
      return;
    }
    setSaving(true);
    setError("");
    try {
      await api.setNewsLocation(newsId, location.trim(), position.latitude, position.longitude);
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la ubicación.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="location-form-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar formulario" />
      <section className="modal location-modal">
        <div className="modal-header">
          <div><p className="eyebrow">GEOLOCALIZACIÓN</p><h2 id="location-form-title">Ubicar noticia</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="location-form-grid">
            <div className="location-fields">
              <label>
                Noticia
                <select required value={newsId} onChange={(event) => choose(event.target.value)}>
                  {candidates.length === 0 && <option value={0}>No hay noticias disponibles</option>}
                  {candidates.map((item) => <option key={item.id} value={item.id}>{item.latitude === null ? "○ " : "● "}{item.title}</option>)}
                </select>
              </label>
              <label>
                Lugar o referencia
                <input maxLength={180} value={location} onChange={(event) => setLocation(event.target.value)} placeholder="Ejemplo: Calle Juárez y Morelos" />
              </label>
              <div className="coordinate-fields">
                <label>Latitud<input type="number" min={-90} max={90} step="any" value={latitude} onChange={(event) => setLatitude(event.target.value)} /></label>
                <label>Longitud<input type="number" min={-180} max={180} step="any" value={longitude} onChange={(event) => setLongitude(event.target.value)} /></label>
              </div>
              <div className="map-pick-help"><strong>¿Cómo ubicarla?</strong><span>Haz clic en el punto exacto del mapa. También puedes escribir las coordenadas.</span></div>
            </div>
            <div className="location-picker">
              <IncidentMap incidents={[]} picking preview={position} onMapClick={pick} compact />
              <span>Haz clic para colocar el marcador</span>
            </div>
          </div>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><button className="button primary" disabled={saving || candidates.length === 0}>{saving ? "Guardando…" : "Guardar ubicación"}</button></div>
        </form>
      </section>
    </div>
  );
}

export default function MapPage() {
  const [stats, setStats] = useState<MapStats>(emptyStats);
  const [incidents, setIncidents] = useState<MapIncident[]>([]);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [locationNews, setLocationNews] = useState<NewsItem | null | undefined>(undefined);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextStats, mapResponse, newsResponse, municipalityResponse] = await Promise.all([
        api.mapStats(),
        api.listMapIncidents({ status, priority, municipality, limit: 300 }),
        api.listNews({ limit: 100 }),
        api.listMunicipalities(),
      ]);
      setStats(nextStats);
      setIncidents(mapResponse.items);
      setNews(newsResponse.items);
      setMunicipalities(municipalityResponse);
      setSelectedId((current) => current && mapResponse.items.some((item) => item.id === current) ? current : mapResponse.items[0]?.id || null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible cargar el mapa.");
    } finally {
      setLoading(false);
    }
  }, [municipality, priority, status]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const selected = incidents.find((item) => item.id === selectedId) || null;

  function openLocation(item?: MapIncident) {
    setLocationNews(item ? news.find((value) => value.id === item.id) || null : null);
    setSuccess("");
    setError("");
  }

  async function saved() {
    setLocationNews(undefined);
    setSuccess("La noticia quedó ubicada correctamente en el mapa.");
    await load();
  }

  async function clearLocation(item: MapIncident) {
    if (!window.confirm(`¿Quitar del mapa “${item.title}”? La noticia se conservará.`)) return;
    setError("");
    setSuccess("");
    try {
      await api.clearNewsLocation(item.id);
      setSuccess("La ubicación se retiró; la noticia continúa guardada.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo quitar la ubicación.");
    }
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">FASE 8 · GEOLOCALIZACIÓN</p><h1>Mapa de incidencias</h1><p>Ubica reportes y noticias para visualizar lo que ocurre en cada zona.</p></div>
        <button className="button primary" onClick={() => openLocation()}>+ Ubicar noticia</button>
      </div>

      <section className="stats-grid map-stats">
        <div className="stat-card"><div className="stat-icon blue">⌖</div><div><span>En el mapa</span><strong>{stats.mapped}</strong><small>Noticias ubicadas</small></div></div>
        <div className="stat-card"><div className="stat-icon orange">○</div><div><span>Por ubicar</span><strong>{stats.unmapped}</strong><small>Noticias sin coordenadas</small></div></div>
        <div className="stat-card"><div className="stat-icon red">!</div><div><span>Urgentes</span><strong>{stats.urgent}</strong><small>Incidencias visibles</small></div></div>
        <div className="stat-card"><div className="stat-icon green">▤</div><div><span>Cobertura</span><strong>{stats.news}</strong><small>Noticias no archivadas</small></div></div>
      </section>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <section className="panel map-panel">
        <div className="map-filters">
          <select aria-label="Filtrar por municipio" value={municipality} onChange={(event) => setMunicipality(event.target.value)}><option value="">Todos los municipios</option>{municipalities.map((item) => <option key={item.id} value={item.name}>{item.name}</option>)}</select>
          <select aria-label="Filtrar por estado" value={status} onChange={(event) => setStatus(event.target.value)}><option value="">Todos los estados</option>{statuses.map((item) => <option key={item}>{item}</option>)}</select>
          <select aria-label="Filtrar por prioridad" value={priority} onChange={(event) => setPriority(event.target.value)}><option value="">Todas las prioridades</option>{priorities.map((item) => <option key={item}>{item}</option>)}</select>
          <button className="button secondary" onClick={load}>Actualizar</button>
        </div>
        <div className="map-layout">
          <div className="map-canvas-wrap">
            <IncidentMap incidents={incidents} selectedId={selectedId} onSelect={setSelectedId} />
            <div className="map-legend"><span><i className="urgent" />Urgente</span><span><i className="pending" />Pendiente</span><span><i className="review" />En revisión</span><span><i className="published" />Publicada</span></div>
            {loading && <div className="map-loading">Actualizando mapa…</div>}
          </div>
          <aside className="incident-list-panel">
            <div className="incident-list-header"><div><strong>Incidencias</strong><span>{incidents.length} ubicadas</span></div><button onClick={() => openLocation()}>+ Agregar</button></div>
            <div className="incident-list">
              {incidents.map((item) => (
                <button className={`incident-card ${item.id === selectedId ? "active" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}>
                  <div><span className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</span><span className={statusClass(item.status)}>{item.status}</span></div>
                  <strong>{item.title}</strong>
                  <p>{item.location || item.municipality}</p>
                  <small>{item.category} · {dateTime(item.created_at)}</small>
                </button>
              ))}
              {!loading && incidents.length === 0 && <div className="map-empty"><span>⌖</span><strong>No hay noticias ubicadas</strong><p>Pulsa “Ubicar noticia” y marca el punto en el mapa.</p></div>}
            </div>
          </aside>
        </div>
        {selected && <div className="selected-incident"><div><span className={`priority priority-${selected.priority.toLowerCase()}`}>{selected.priority}</span><strong>{selected.title}</strong><p>{selected.location || selected.municipality} · {selected.category}</p></div><div><button className="button secondary" onClick={() => openLocation(selected)}>Editar ubicación</button><button className="button danger-outline" onClick={() => clearLocation(selected)}>Quitar del mapa</button></div></div>}
      </section>

      <div className="map-privacy-note"><span>i</span><p><strong>Privacidad editorial:</strong> utiliza ubicaciones aproximadas cuando el reporte involucre domicilios particulares, menores de edad o víctimas.</p></div>

      {locationNews !== undefined && <LocationModal news={news} initial={locationNews} onClose={() => setLocationNews(undefined)} onSaved={saved} />}
    </main>
  );
}
