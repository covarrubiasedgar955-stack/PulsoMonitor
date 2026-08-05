"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { Municipality, MunicipalityInput } from "@/types/news";

const emptyMunicipality: MunicipalityInput = {
  name: "",
  region: "Valles",
  state: "Jalisco",
  active: true,
};

function MunicipalityModal({
  item,
  onClose,
  onSaved,
}: {
  item: Municipality | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [draft, setDraft] = useState<MunicipalityInput>(() => item ? {
    name: item.name,
    region: item.region,
    state: item.state,
    active: item.active,
  } : emptyMunicipality);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload = {
      ...draft,
      name: draft.name.trim(),
      region: draft.region.trim() || "Valles",
      state: draft.state.trim() || "Jalisco",
    };
    try {
      if (item) await api.updateMunicipality(item.id, payload);
      else await api.createMunicipality(payload);
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar el municipio.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="municipality-form-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar formulario" />
      <section className="modal municipality-modal">
        <div className="modal-header">
          <div>
            <p className="eyebrow">COBERTURA EDITORIAL</p>
            <h2 id="municipality-form-title">{item ? "Editar municipio" : "Agregar municipio"}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="full">
              Municipio o zona *
              <input required minLength={2} maxLength={100} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} placeholder="Ejemplo: Amatitán" />
            </label>
            <label>
              Región
              <input maxLength={100} value={draft.region} onChange={(event) => setDraft({ ...draft, region: event.target.value })} placeholder="Valles" />
            </label>
            <label>
              Estado
              <input maxLength={100} value={draft.state} onChange={(event) => setDraft({ ...draft, state: event.target.value })} placeholder="Jalisco" />
            </label>
            <label className="checkbox full">
              <input type="checkbox" checked={draft.active} onChange={(event) => setDraft({ ...draft, active: event.target.checked })} />
              Incluir este municipio en la cobertura activa
            </label>
          </div>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions">
            <button type="button" className="button secondary" onClick={onClose}>Cancelar</button>
            <button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar municipio"}</button>
          </div>
        </form>
      </section>
    </div>
  );
}

export default function MunicipalitiesPage() {
  const [items, setItems] = useState<Municipality[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Municipality | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setItems(await api.listMunicipalities());
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible cargar los municipios.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const totals = useMemo(() => items.reduce((result, item) => ({
    active: result.active + Number(item.active),
    news: result.news + item.news,
    sources: result.sources + item.radar_sources,
  }), { active: 0, news: 0, sources: 0 }), [items]);

  function create() {
    setEditing(null);
    setModalOpen(true);
  }

  function edit(item: Municipality) {
    setEditing(item);
    setModalOpen(true);
  }

  function close() {
    setEditing(null);
    setModalOpen(false);
  }

  async function saved() {
    close();
    setSuccess("La cobertura se guardó correctamente.");
    await load();
  }

  async function remove(item: Municipality) {
    if (!window.confirm(`¿Eliminar “${item.name}” de la cobertura?`)) return;
    setError("");
    setSuccess("");
    try {
      await api.deleteMunicipality(item.id);
      setSuccess("El municipio se eliminó correctamente.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo eliminar el municipio.");
    }
  }

  return (
    <main>
      <div className="page-heading">
        <div>
          <p className="eyebrow">FASE 7 · COBERTURA</p>
          <h1>Municipios</h1>
          <p>Organiza las noticias y fuentes de cada zona cubierta por Pulso Tequila.</p>
        </div>
        <button className="button primary" onClick={create}>+ Agregar municipio</button>
      </div>

      <section className="stats-grid municipality-stats">
        <div className="stat-card"><div className="stat-icon blue">⌂</div><div><span>Registrados</span><strong>{items.length}</strong><small>Municipios y zonas</small></div></div>
        <div className="stat-card"><div className="stat-icon green">✓</div><div><span>Cobertura activa</span><strong>{totals.active}</strong><small>Listos para monitorear</small></div></div>
        <div className="stat-card"><div className="stat-icon orange">▤</div><div><span>Noticias</span><strong>{totals.news}</strong><small>Contenido clasificado</small></div></div>
        <div className="stat-card"><div className="stat-icon red">⌖</div><div><span>Fuentes Radar</span><strong>{totals.sources}</strong><small>Fuentes vinculadas</small></div></div>
      </section>

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success}</div>}

      <section className="panel municipalities-panel">
        <div className="panel-header">
          <div><h2>Cobertura editorial</h2><p>Los municipios usados en Noticias o Radar se incorporan automáticamente.</p></div>
          <span className="coverage-badge">{totals.active} activos</span>
        </div>

        {loading && <div className="radar-empty small"><div>⌂</div><strong>Cargando cobertura…</strong></div>}
        {!loading && items.length === 0 && <div className="radar-empty small"><div>⌂</div><strong>No hay municipios registrados</strong><span>Agrega la primera zona para comenzar a organizar las noticias.</span></div>}
        {!loading && items.length > 0 && (
          <div className="municipality-grid">
            {items.map((item) => (
              <article className={`municipality-card ${item.active ? "" : "inactive"}`} key={item.id}>
                <div className="municipality-card-head">
                  <div className="municipality-pin">⌖</div>
                  <div><h3>{item.name}</h3><p>{item.region} · {item.state}</p></div>
                  <span className={item.active ? "coverage-status active" : "coverage-status"}>{item.active ? "Activo" : "Inactivo"}</span>
                </div>
                <div className="municipality-metrics">
                  <div><strong>{item.news}</strong><span>Noticias</span></div>
                  <div><strong>{item.pending}</strong><span>Pendientes</span></div>
                  <div><strong>{item.published}</strong><span>Publicadas</span></div>
                  <div><strong>{item.urgent}</strong><span>Urgentes</span></div>
                </div>
                <div className="municipality-source-count"><span>⌁</span> {item.radar_sources} fuente{item.radar_sources === 1 ? "" : "s"} en Radar</div>
                <div className="municipality-actions">
                  <Link className="button secondary" href={`/noticias?municipio=${encodeURIComponent(item.name)}`}>Ver noticias</Link>
                  <button className="button secondary" onClick={() => edit(item)}>Editar</button>
                  <button className="button danger-outline" onClick={() => remove(item)}>Eliminar</button>
                </div>
              </article>
            ))}
          </div>
        )}
      </section>

      <section className="coverage-next">
        <div><span>PRÓXIMO PASO</span><strong>Mapa de incidencias</strong><p>Esta cobertura será la base para ubicar reportes y noticias en el mapa.</p></div>
        <span className="coverage-next-icon">⌖</span>
      </section>

      {modalOpen && <MunicipalityModal item={editing} onClose={close} onSaved={saved} />}
    </main>
  );
}
