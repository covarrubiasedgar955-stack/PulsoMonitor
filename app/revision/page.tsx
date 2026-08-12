"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { EditorialAction, EditorialBoard, EditorialItem, EditorialState, Municipality, UserInfo } from "@/types/news";

const states: EditorialState[] = ["Borrador", "En revisión", "Aprobada", "Cambios solicitados"];

function when(value: string | null) {
  if (!value) return "Sin fecha";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

function stateClass(value: EditorialState) {
  return `review-state review-${value.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`;
}

function imageStyle(value: string) {
  return value ? { backgroundImage: `url("${value.replaceAll('"', "%22")}")` } : undefined;
}

export default function EditorialReviewPage() {
  const [board, setBoard] = useState<EditorialBoard | null>(null);
  const [team, setTeam] = useState<UserInfo[]>([]);
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [state, setState] = useState("");
  const [assignee, setAssignee] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [sort, setSort] = useState("newest");
  const [imageFilter, setImageFilter] = useState("all");
  const [selected, setSelected] = useState<EditorialItem | null>(null);
  const [noteAction, setNoteAction] = useState<EditorialAction | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [result, members, current, municipalityList] = await Promise.all([
        api.editorialBoard(state, assignee ? Number(assignee) : undefined, municipality, sort, imageFilter),
        api.editorialTeam(),
        api.currentUser(),
        api.listMunicipalities(),
      ]);
      setBoard(result);
      setTeam(members);
      setUser(current);
      setMunicipalities(municipalityList.filter((item) => item.active));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar la revisión editorial.");
    } finally {
      setLoading(false);
    }
  }, [assignee, imageFilter, municipality, sort, state]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const canReview = user?.role === "Administrador" || user?.role === "Editor";
  const visibleItems = useMemo(() => board?.items || [], [board]);

  async function assign(item: EditorialItem, value: string) {
    setSaving(true); setError(""); setMessage("");
    try {
      const updated = await api.updateEditorialFlow(item.id, "assign", value ? Number(value) : null);
      setSelected(updated);
      setMessage("Responsable actualizado.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo asignar la noticia.");
    } finally { setSaving(false); }
  }

  function openAction(item: EditorialItem, action: EditorialAction) {
    setSelected(item); setNoteAction(action); setNote(action === "request_changes" ? item.review_note : "");
  }

  async function submitAction(event: FormEvent) {
    event.preventDefault();
    if (!selected || !noteAction) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const updated = await api.updateEditorialFlow(selected.id, noteAction, selected.assigned_to, note);
      setSelected(updated);
      const labels: Record<EditorialAction, string> = {
        assign: "Responsable actualizado.", request_review: "Noticia enviada a revisión.",
        approve: "Noticia aprobada y lista para Publicaciones.", request_changes: "Correcciones enviadas al responsable.",
        reopen: "La noticia volvió a borrador.",
      };
      setMessage(labels[noteAction]); setNoteAction(null); setNote("");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo actualizar el flujo editorial.");
    } finally { setSaving(false); }
  }

  const cards = [
    { label: "Borradores", value: board?.drafts || 0, tone: "blue", icon: "✎" },
    { label: "En revisión", value: board?.review || 0, tone: "orange", icon: "◷" },
    { label: "Aprobadas", value: board?.approved || 0, tone: "green", icon: "✓" },
    { label: "Con cambios", value: board?.changes || 0, tone: "red", icon: "!" },
  ];

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">VERSIÓN 1.4 · CONTROL EDITORIAL</p><h1>Revisión editorial</h1><p>Asigna responsables, solicita correcciones y aprueba cada noticia antes de publicarla.</p></div>
        <Link href="/noticias" className="button primary">+ Crear noticia</Link>
      </div>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message}</div>}

      <section className="stats-grid">
        {cards.map((card) => <article className="stat-card" key={card.label}><div className={`stat-icon ${card.tone}`}>{card.icon}</div><div><span>{card.label}</span><strong>{card.value}</strong><small>noticias</small></div></article>)}
      </section>

      <section className="editorial-layout">
        <div className="panel editorial-board">
          <div className="editorial-filters">
            <select value={municipality} onChange={(event) => setMunicipality(event.target.value)} aria-label="Municipio"><option value="">Todos los municipios</option>{municipalities.map((item) => <option value={item.name} key={item.id}>{item.name}</option>)}</select>
            <select value={state} onChange={(event) => setState(event.target.value)} aria-label="Estado editorial"><option value="">Todos los estados</option>{states.map((value) => <option key={value}>{value}</option>)}</select>
            <select value={assignee} onChange={(event) => setAssignee(event.target.value)} aria-label="Responsable"><option value="">Todo el equipo</option>{team.map((member) => <option value={member.id} key={member.id}>{member.name}</option>)}</select>
            <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Ordenar noticias"><option value="newest">Más recientes primero</option><option value="oldest">Más antiguas primero</option><option value="priority_desc">Mayor importancia</option><option value="priority_asc">Menor importancia</option></select>
            <select value={imageFilter} onChange={(event) => setImageFilter(event.target.value)} aria-label="Filtrar por imagen"><option value="all">Todas las imágenes</option><option value="with">Con imagen</option><option value="without">Sin imagen</option></select>
            <button className="button secondary" onClick={() => void load()}>Actualizar</button>
          </div>
          <div className="editorial-list">
            {visibleItems.map((item) => (
              <article className={`editorial-card ${selected?.id === item.id ? "selected" : ""}`} key={item.id} onClick={() => setSelected(item)}>
                <div className={`editorial-card-image ${item.image_url ? "has-image" : ""}`} style={imageStyle(item.image_url)}>{item.image_url ? "" : "Sin imagen"}</div>
                <div className="editorial-card-top"><span className={stateClass(item.editorial_state)}>{item.editorial_state}</span><span className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</span></div>
                <h3>{item.title}</h3><p>{item.summary || item.content || "Sin resumen editorial."}</p>
                <div className="editorial-meta"><span>{item.municipality}</span><span>{item.category}</span><span>{when(item.review_requested_at || item.updated_at)}</span></div>
              </article>
            ))}
            {loading && <div className="empty">Cargando flujo editorial…</div>}
            {!loading && visibleItems.length === 0 && <div className="empty"><strong>No hay noticias en esta sección.</strong><span>Cambia los filtros o crea contenido nuevo.</span></div>}
          </div>
        </div>

        <aside className="panel editorial-detail">
          {!selected ? <div className="editorial-placeholder"><span>✓</span><strong>Selecciona una noticia</strong><p>Aquí podrás asignarla y avanzar su revisión.</p></div> : <>
            <div className="panel-header"><div><p className="eyebrow">EXPEDIENTE EDITORIAL</p><h2>{selected.title}</h2></div></div>
            <div className="editorial-detail-body">
              <div className={`editorial-detail-image ${selected.image_url ? "has-image" : ""}`} style={imageStyle(selected.image_url)}>{selected.image_url ? "" : "Sin imagen disponible"}</div>
              <div className="detail-status"><span className={stateClass(selected.editorial_state)}>{selected.editorial_state}</span><span className={`priority priority-${selected.priority.toLowerCase()}`}>{selected.priority}</span></div>
              <p>{selected.summary || "Esta noticia todavía no tiene resumen."}</p>
              <dl><div><dt>Responsable</dt><dd>{selected.assigned_name}</dd></div><div><dt>Municipio</dt><dd>{selected.municipality}</dd></div><div><dt>Categoría</dt><dd>{selected.category}</dd></div><div><dt>Último cambio</dt><dd>{when(selected.updated_at)}</dd></div></dl>
              {selected.review_note && <div className="review-note"><strong>Observaciones</strong><p>{selected.review_note}</p></div>}
              {canReview && <label>Asignar responsable<select disabled={saving} value={selected.assigned_to || ""} onChange={(event) => void assign(selected, event.target.value)}><option value="">Sin asignar</option>{team.map((member) => <option value={member.id} key={member.id}>{member.name} · {member.role}</option>)}</select></label>}
              <div className="editorial-actions">
                {(selected.editorial_state === "Borrador" || selected.editorial_state === "Cambios solicitados") && <button className="button primary" onClick={() => openAction(selected, "request_review")}>Enviar a revisión</button>}
                {selected.editorial_state === "En revisión" && canReview && <><button className="button success-button" onClick={() => openAction(selected, "approve")}>Aprobar noticia</button><button className="button danger-outline" onClick={() => openAction(selected, "request_changes")}>Solicitar cambios</button></>}
                {selected.editorial_state === "Aprobada" && <><Link className="button facebook-button" href="/publicaciones">Ir a Publicaciones</Link><button className="button secondary" onClick={() => openAction(selected, "reopen")}>Reabrir</button></>}
                <Link className="button secondary" href="/noticias">Editar contenido</Link>
              </div>
            </div>
          </>}
        </aside>
      </section>

      {selected && noteAction && <div className="modal-layer" role="dialog" aria-modal="true"><button className="modal-backdrop" onClick={() => setNoteAction(null)} aria-label="Cerrar" /><section className="modal review-modal"><div className="modal-header"><div><p className="eyebrow">FLUJO EDITORIAL</p><h2>{noteAction === "approve" ? "Aprobar noticia" : noteAction === "request_changes" ? "Solicitar correcciones" : noteAction === "request_review" ? "Enviar a revisión" : "Reabrir borrador"}</h2></div><button className="icon-button" onClick={() => setNoteAction(null)}>×</button></div><form onSubmit={submitAction}><p><strong>{selected.title}</strong></p><label>{noteAction === "request_changes" ? "Correcciones requeridas *" : "Observaciones (opcional)"}<textarea required={noteAction === "request_changes"} rows={5} maxLength={800} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Escribe instrucciones claras para el equipo…" /></label><div className="modal-actions"><button type="button" className="button secondary" onClick={() => setNoteAction(null)}>Cancelar</button><button className="button primary" disabled={saving}>{saving ? "Guardando…" : "Confirmar"}</button></div></form></section></div>}
    </main>
  );
}
