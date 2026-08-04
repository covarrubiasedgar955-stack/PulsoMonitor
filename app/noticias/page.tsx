"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { NewsInput, NewsItem, NewsPriority, NewsStatus } from "@/types/news";

type Draft = Omit<NewsInput, "tags"> & { tags: string };

const initialDraft: Draft = {
  title: "",
  summary: "",
  content: "",
  source: "Facebook",
  author: "Redacción Pulso Tequila",
  municipality: "Tequila",
  category: "General",
  priority: "Media",
  status: "Pendiente",
  image_url: "",
  url: "",
  published_at: null,
  is_ai: false,
  tags: "",
};

const statuses: NewsStatus[] = ["Pendiente", "En revisión", "Programada", "Publicada", "Archivada"];
const priorities: NewsPriority[] = ["Baja", "Media", "Alta", "Urgente"];
const categories = ["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad"];

function dateTime(value: string) {
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function statusClass(value: string) {
  return `status status-${value.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`;
}

function NewsModal({ item, onClose, onSaved }: { item: NewsItem | null; onClose: () => void; onSaved: () => void }) {
  const [draft, setDraft] = useState<Draft>(() => item ? {
    title: item.title,
    summary: item.summary,
    content: item.content,
    source: item.source,
    author: item.author,
    municipality: item.municipality,
    category: item.category,
    priority: item.priority,
    status: item.status,
    image_url: item.image_url,
    url: item.url,
    published_at: item.published_at,
    is_ai: item.is_ai,
    tags: item.tags.join(", "),
  } : initialDraft);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  function field<K extends keyof Draft>(key: K, value: Draft[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    const payload: NewsInput = {
      ...draft,
      title: draft.title.trim(),
      summary: draft.summary.trim(),
      content: draft.content.trim(),
      tags: draft.tags.split(",").map((tag) => tag.trim()).filter(Boolean),
      published_at: draft.published_at || null,
    };
    try {
      if (item) await api.updateNews(item.id, payload);
      else await api.createNews(payload);
      onSaved();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la noticia.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="modal-layer" role="dialog" aria-modal="true" aria-labelledby="news-form-title">
      <button className="modal-backdrop" onClick={onClose} aria-label="Cerrar formulario" />
      <section className="modal">
        <div className="modal-header">
          <div><p className="eyebrow">MÓDULO DE NOTICIAS</p><h2 id="news-form-title">{item ? "Editar noticia" : "Nueva noticia"}</h2></div>
          <button className="icon-button" onClick={onClose} aria-label="Cerrar">×</button>
        </div>
        <form onSubmit={submit}>
          <div className="form-grid">
            <label className="full">Título *<input required maxLength={180} value={draft.title} onChange={(event) => field("title", event.target.value)} placeholder="Título de la noticia" /></label>
            <label className="full">Resumen<textarea rows={2} value={draft.summary} onChange={(event) => field("summary", event.target.value)} placeholder="Resumen breve para identificarla" /></label>
            <label className="full">Contenido<textarea rows={5} value={draft.content} onChange={(event) => field("content", event.target.value)} placeholder="Texto completo de la publicación" /></label>
            <label>Municipio<input value={draft.municipality} onChange={(event) => field("municipality", event.target.value)} /></label>
            <label>Categoría<select value={draft.category} onChange={(event) => field("category", event.target.value)}>{categories.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Estado<select value={draft.status} onChange={(event) => field("status", event.target.value as NewsStatus)}>{statuses.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Prioridad<select value={draft.priority} onChange={(event) => field("priority", event.target.value as NewsPriority)}>{priorities.map((value) => <option key={value}>{value}</option>)}</select></label>
            <label>Fuente<input value={draft.source} onChange={(event) => field("source", event.target.value)} /></label>
            <label>Autor<input value={draft.author} onChange={(event) => field("author", event.target.value)} /></label>
            <label className="full">Enlace de origen<input type="url" value={draft.url} onChange={(event) => field("url", event.target.value)} placeholder="https://..." /></label>
            <label className="full">URL de imagen<input type="url" value={draft.image_url} onChange={(event) => field("image_url", event.target.value)} placeholder="https://..." /></label>
            <label className="full">Etiquetas<input value={draft.tags} onChange={(event) => field("tags", event.target.value)} placeholder="tequila, deportes, comunidad" /></label>
            <label className="checkbox full"><input type="checkbox" checked={draft.is_ai} onChange={(event) => field("is_ai", event.target.checked)} /> Contenido apoyado por IA</label>
          </div>
          {error && <div className="alert error">{error}</div>}
          <div className="modal-actions"><button type="button" className="button secondary" onClick={onClose}>Cancelar</button><button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Guardar noticia"}</button></div>
        </form>
      </section>
    </div>
  );
}

export default function NewsPage() {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [priority, setPriority] = useState("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<NewsItem | null>(null);
  const pageSize = 10;

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const response = await api.listNews({ search, status, priority, limit: pageSize, offset: (page - 1) * pageSize });
      setItems(response.items);
      setTotal(response.total);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No fue posible cargar las noticias.");
    } finally {
      setLoading(false);
    }
  }, [page, priority, search, status]);

  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function remove(item: NewsItem) {
    if (!window.confirm(`¿Eliminar definitivamente “${item.title}”?`)) return;
    try {
      await api.deleteNews(item.id);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo eliminar la noticia.");
    }
  }

  function create() { setEditing(null); setModalOpen(true); }
  function edit(item: NewsItem) { setEditing(item); setModalOpen(true); }
  function close() { setModalOpen(false); setEditing(null); }
  async function saved() { close(); await load(); }
  const pages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">GESTIÓN EDITORIAL</p><h1>Noticias</h1><p>Crea, revisa y organiza todo el contenido de Pulso Tequila.</p></div>
        <button className="button primary" onClick={create}>+ Nueva noticia</button>
      </div>

      <section className="panel">
        <div className="filters">
          <label className="search-box"><span>⌕</span><input value={search} onChange={(event) => { setSearch(event.target.value); setPage(1); }} placeholder="Buscar por título, fuente, municipio…" /></label>
          <select aria-label="Filtrar por estado" value={status} onChange={(event) => { setStatus(event.target.value); setPage(1); }}><option value="">Todos los estados</option>{statuses.map((value) => <option key={value}>{value}</option>)}</select>
          <select aria-label="Filtrar por prioridad" value={priority} onChange={(event) => { setPriority(event.target.value); setPage(1); }}><option value="">Todas las prioridades</option>{priorities.map((value) => <option key={value}>{value}</option>)}</select>
          <button className="button secondary" onClick={load}>Actualizar</button>
        </div>

        {error && <div className="alert error">{error}</div>}
        <div className="table-wrap">
          <table>
            <thead><tr><th>Noticia</th><th>Municipio</th><th>Categoría</th><th>Prioridad</th><th>Estado</th><th>Fecha</th><th>Acciones</th></tr></thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.id}>
                  <td className="news-cell"><strong>{item.title}</strong><small>{item.summary || item.source}</small></td>
                  <td>{item.municipality}</td>
                  <td><span className="tag">{item.category}</span></td>
                  <td><span className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</span></td>
                  <td><span className={statusClass(item.status)}>{item.status}</span></td>
                  <td>{dateTime(item.created_at)}</td>
                  <td><div className="row-actions"><button onClick={() => edit(item)} title="Editar">Editar</button><button className="danger" onClick={() => remove(item)} title="Eliminar">Eliminar</button></div></td>
                </tr>
              ))}
              {loading && <tr><td colSpan={7} className="empty">Cargando noticias…</td></tr>}
              {!loading && items.length === 0 && <tr><td colSpan={7} className="empty"><strong>No encontramos noticias.</strong><span>Cambia los filtros o agrega la primera noticia.</span></td></tr>}
            </tbody>
          </table>
        </div>
        <div className="pagination"><span>{total} noticia{total === 1 ? "" : "s"}</span><div><button disabled={page === 1} onClick={() => setPage((value) => value - 1)}>← Anterior</button><strong>Página {page} de {pages}</strong><button disabled={page >= pages} onClick={() => setPage((value) => value + 1)}>Siguiente →</button></div></div>
      </section>
      {modalOpen && <NewsModal item={editing} onClose={close} onSaved={saved} />}
    </main>
  );
}
