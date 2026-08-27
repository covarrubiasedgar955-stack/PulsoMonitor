"use client";

import { APP_VERSION } from "@/lib/version";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { EditorialAction, EditorialBoard, EditorialItem, EditorialState, Municipality, UserInfo } from "@/types/news";

const states: EditorialState[] = ["Borrador", "En revisión", "Aprobada", "Cambios solicitados"];
const categories = ["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad", "Gobierno", "Economía"];

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

function isLocalImage(value: string) {
  return /^https?:\/\/(127\.0\.0\.1|localhost):8000\/api\/imagenes\//.test(value);
}

export default function EditorialReviewPage() {
  const [board, setBoard] = useState<EditorialBoard | null>(null);
  const [team, setTeam] = useState<UserInfo[]>([]);
  const [municipalities, setMunicipalities] = useState<Municipality[]>([]);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [state, setState] = useState("");
  const [assignee, setAssignee] = useState("");
  const [municipality, setMunicipality] = useState("");
  const [sort, setSort] = useState("priority_desc");
  const [imageFilter, setImageFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [priority, setPriority] = useState("");
  const [category, setCategory] = useState("");
  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [batchAssignee, setBatchAssignee] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<EditorialItem | null>(null);
  const [imageUrl, setImageUrl] = useState("");
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState("");
  const [uploadInputKey, setUploadInputKey] = useState(0);
  const [noteAction, setNoteAction] = useState<EditorialAction | null>(null);
  const [note, setNote] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [imageError, setImageError] = useState("");
  const [imageMessage, setImageMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [result, members, current, municipalityList] = await Promise.all([
        api.editorialBoard(state, assignee ? Number(assignee) : undefined, municipality, sort, imageFilter, search, priority, category, page, 20),
        api.editorialTeam(),
        api.currentUser(),
        api.listMunicipalities(),
      ]);
      setBoard(result);
      setSelectedIds((current) => current.filter((id) => result.items.some((item) => item.id === id)));
      setTeam(members);
      setUser(current);
      setMunicipalities(municipalityList.filter((item) => item.active));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar la revisión editorial.");
    } finally {
      setLoading(false);
    }
  }, [assignee, category, imageFilter, municipality, page, priority, search, sort, state]);

  useEffect(() => { setPage(1); }, [assignee, category, imageFilter, municipality, priority, search, sort, state]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 250);
    return () => window.clearTimeout(timer);
  }, [load]);

  useEffect(() => {
    setImageUrl(selected?.image_url && !isLocalImage(selected.image_url) ? selected.image_url : "");
    setImageFile(null);
    setImagePreview("");
    setUploadInputKey((value) => value + 1);
    setImageError("");
    setImageMessage("");
  }, [selected?.id, selected?.image_url]);

  useEffect(() => {
    if (!imageFile) return;
    const preview = URL.createObjectURL(imageFile);
    setImagePreview(preview);
    return () => URL.revokeObjectURL(preview);
  }, [imageFile]);

  const canReview = user?.role === "Administrador" || user?.role === "Editor";
  const visibleItems = useMemo(() => board?.items || [], [board]);
  const allVisibleSelected = visibleItems.length > 0 && visibleItems.every((item) => selectedIds.includes(item.id));
  const totalPages = Math.max(1, Math.ceil((board?.total || 0) / (board?.page_size || 20)));

  function toggleSelected(id: number) {
    setSelectedIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  async function runBatch(action: "assign" | "archive" | "delete") {
    if (!selectedIds.length) return;
    if (action === "assign" && !batchAssignee) {
      setError("Selecciona primero al responsable.");
      return;
    }
    if (action !== "assign" && !window.confirm(`${action === "delete" ? "Eliminar" : "Archivar"} ${selectedIds.length} noticias seleccionadas? Las aprobadas, programadas o publicadas permanecerán protegidas.`)) return;
    setSaving(true); setError(""); setMessage("");
    try {
      const result = await api.updateEditorialBatch(action, selectedIds, batchAssignee ? Number(batchAssignee) : null);
      const label = action === "assign" ? "asignadas" : action === "archive" ? "archivadas" : "eliminadas";
      setMessage(`${result.updated} noticias ${label}.${result.protected ? ` ${result.protected} permanecieron protegidas.` : ""}`);
      setSelectedIds([]); setSelected(null);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo completar la acción por lote.");
    } finally { setSaving(false); }
  }

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

  async function updateImage(remove = false) {
    if (!selected) return;
    const nextImage = remove ? "" : imageUrl.trim();
    if (!remove && !nextImage) {
      setError("Pega primero la dirección de una fotografía.");
      setImageError("Pega primero la dirección de una fotografía.");
      return;
    }
    setSaving(true); setError(""); setMessage(""); setImageError(""); setImageMessage("");
    try {
      const updated = await api.updateEditorialImage(selected.id, nextImage);
      setSelected(updated);
      setImageUrl(updated.image_url);
      setMessage(remove ? "La imagen fue retirada. La noticia se publicará sin fotografía." : "Fotografía validada y actualizada.");
      setImageMessage(remove ? "La imagen fue retirada." : "Fotografía validada y actualizada.");
      await load();
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : "No se pudo actualizar la imagen.";
      setError(detail); setImageError(detail);
    } finally { setSaving(false); }
  }

  function chooseImage(file: File | undefined) {
    setError(""); setMessage(""); setImageError(""); setImageMessage("");
    if (!file) { setImageFile(null); return; }
    if (!(["image/jpeg", "image/png", "image/webp"].includes(file.type))) {
      setError("Selecciona una fotografía JPEG, PNG o WebP."); setImageError("Selecciona una fotografía JPEG, PNG o WebP.");
      setImageFile(null); return;
    }
    if (file.size > 8 * 1024 * 1024) {
      setError("La fotografía debe pesar menos de 8 MB."); setImageError("La fotografía debe pesar menos de 8 MB.");
      setImageFile(null); return;
    }
    setImageFile(file);
  }

  async function uploadImage() {
    if (!selected || !imageFile) return;
    setSaving(true); setError(""); setMessage(""); setImageError(""); setImageMessage("");
    try {
      const updated = await api.uploadEditorialImage(selected.id, imageFile);
      setSelected(updated);
      setImageUrl("");
      setImageFile(null);
      setMessage("La fotografía se subió y quedó lista para publicar en Facebook.");
      setImageMessage("La fotografía se subió y quedó lista para publicar en Facebook.");
      await load();
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : "No se pudo subir la fotografía.";
      setError(detail); setImageError(detail);
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
        <div><p className="eyebrow">VERSIÓN {APP_VERSION} · CONTROL EDITORIAL</p><h1>Revisión editorial</h1><p>Asigna responsables, solicita correcciones y aprueba cada noticia antes de publicarla.</p></div>
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
            <label className="editorial-search"><span>⌕</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Buscar título, fuente o contenido…" aria-label="Buscar noticias" /></label>
            <select value={municipality} onChange={(event) => setMunicipality(event.target.value)} aria-label="Municipio"><option value="">Todos los municipios</option>{municipalities.map((item) => <option value={item.name} key={item.id}>{item.name}</option>)}</select>
            <select value={state} onChange={(event) => setState(event.target.value)} aria-label="Estado editorial"><option value="">Todos los estados</option>{states.map((value) => <option key={value}>{value}</option>)}</select>
            <select value={assignee} onChange={(event) => setAssignee(event.target.value)} aria-label="Responsable"><option value="">Todo el equipo</option>{team.map((member) => <option value={member.id} key={member.id}>{member.name}</option>)}</select>
            <select value={priority} onChange={(event) => setPriority(event.target.value)} aria-label="Prioridad"><option value="">Todas las prioridades</option><option>Baja</option><option>Media</option><option>Alta</option><option>Urgente</option></select>
            <select value={category} onChange={(event) => setCategory(event.target.value)} aria-label="Categoría"><option value="">Todas las categorías</option>{categories.map((value) => <option key={value}>{value}</option>)}</select>
            <select value={sort} onChange={(event) => setSort(event.target.value)} aria-label="Ordenar noticias"><option value="newest">Más recientes primero</option><option value="oldest">Más antiguas primero</option><option value="priority_desc">Mayor importancia</option><option value="priority_asc">Menor importancia</option></select>
            <select value={imageFilter} onChange={(event) => setImageFilter(event.target.value)} aria-label="Filtrar por imagen"><option value="all">Todas las imágenes</option><option value="with">Con imagen</option><option value="without">Sin imagen</option></select>
            <button className="button secondary" onClick={() => void load()}>Actualizar</button>
          </div>
          <div className="editorial-batch-bar">
            <label className="batch-select-all"><input type="checkbox" checked={allVisibleSelected} onChange={() => setSelectedIds(allVisibleSelected ? [] : visibleItems.map((item) => item.id))} /> Seleccionar visibles</label>
            <strong>{selectedIds.length} seleccionada{selectedIds.length === 1 ? "" : "s"}</strong>
            <select value={batchAssignee} onChange={(event) => setBatchAssignee(event.target.value)} aria-label="Responsable por lote"><option value="">Elegir responsable</option>{team.map((member) => <option value={member.id} key={member.id}>{member.name}</option>)}</select>
            <button className="button secondary" disabled={!selectedIds.length || saving} onClick={() => void runBatch("assign")}>Asignar</button>
            <button className="button secondary" disabled={!selectedIds.length || saving} onClick={() => void runBatch("archive")}>Archivar</button>
            <button className="button danger-outline" disabled={!selectedIds.length || saving} onClick={() => void runBatch("delete")}>Eliminar</button>
          </div>
          <div className="editorial-list">
            {visibleItems.map((item) => (
              <article className={`editorial-card ${item.priority === "Urgente" ? "urgent-card" : ""} ${selected?.id === item.id ? "selected" : ""}`} key={item.id} onClick={() => setSelected(item)}>
                <label className="editorial-card-check" onClick={(event) => event.stopPropagation()}><input type="checkbox" checked={selectedIds.includes(item.id)} onChange={() => toggleSelected(item.id)} /><span>Seleccionar noticia</span></label>
                <div className={`editorial-card-image ${item.image_url ? "has-image" : ""}`} style={imageStyle(item.image_url)}>{item.image_url ? "" : "Sin imagen"}</div>
                <div className="editorial-card-top"><span className={stateClass(item.editorial_state)}>{item.editorial_state}</span><span className={`priority priority-${item.priority.toLowerCase()}`}>{item.priority}</span>{item.priority === "Urgente" && <strong className="urgent-label">Atención prioritaria</strong>}</div>
                <h3>{item.title}</h3><p>{item.summary || item.content || "Sin resumen editorial."}</p>
                <div className="editorial-source"><span>Fuente: <strong>{item.source || "Sin identificar"}</strong></span>{item.url && <a href={item.url} target="_blank" rel="noreferrer" onClick={(event) => event.stopPropagation()}>Abrir original ↗</a>}</div>
                <div className="editorial-meta"><span>{item.municipality}</span><span>{item.category}</span><span>{when(item.review_requested_at || item.updated_at)}</span></div>
              </article>
            ))}
            {loading && <div className="empty">Cargando flujo editorial…</div>}
            {!loading && visibleItems.length === 0 && <div className="empty"><strong>No hay noticias en esta sección.</strong><span>Cambia los filtros o crea contenido nuevo.</span></div>}
          </div>
          <div className="editorial-pagination"><span>{board?.total || 0} resultados · Página {page} de {totalPages}</span><div><button className="button secondary" disabled={page <= 1 || loading} onClick={() => { setSelectedIds([]); setPage((value) => value - 1); }}>← Anterior</button><button className="button secondary" disabled={page >= totalPages || loading} onClick={() => { setSelectedIds([]); setPage((value) => value + 1); }}>Siguiente →</button></div></div>
        </div>

        <aside className="panel editorial-detail">
          {!selected ? <div className="editorial-placeholder"><span>✓</span><strong>Selecciona una noticia</strong><p>Aquí podrás asignarla y avanzar su revisión.</p></div> : <>
            <div className="panel-header"><div><p className="eyebrow">EXPEDIENTE EDITORIAL</p><h2>{selected.title}</h2></div></div>
            <div className="editorial-detail-body">
              <div className={`editorial-detail-image ${selected.image_url ? "has-image" : ""}`} style={imageStyle(selected.image_url)}>{selected.image_url ? "" : "Sin imagen disponible"}</div>
              {canReview && <div className="editorial-image-control">
                <strong>Fotografía de la noticia</strong>
                <p>Selecciona una foto desde tu computadora o pega una dirección directa. Pulso Monitor rechazará logotipos, íconos y banners.</p>
                <label className="editorial-file-picker">
                  <span>{imageFile ? imageFile.name : "Elegir fotografía de la computadora"}</span>
                  <input key={uploadInputKey} type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => chooseImage(event.target.files?.[0])} disabled={saving} />
                </label>
                {imagePreview && <div className="editorial-upload-preview" style={imageStyle(imagePreview)}><span>Vista previa</span></div>}
                <button className="button primary" disabled={saving || !imageFile} onClick={() => void uploadImage()}>{saving ? "Subiendo…" : "Subir fotografía"}</button>
                {imageError && <div className="alert error">{imageError}</div>}
                {imageMessage && <div className="alert success">{imageMessage}</div>}
                <span className="editorial-image-divider">o utiliza una dirección de Internet</span>
                <input type="url" value={imageUrl} onChange={(event) => setImageUrl(event.target.value)} placeholder="https://sitio.com/fotografia.jpg" disabled={saving} />
                <div className="editorial-image-url-actions"><button className="button primary" disabled={saving || !imageUrl.trim()} onClick={() => void updateImage(false)}>Validar y guardar</button><button className="button danger-outline" disabled={saving || !selected.image_url} onClick={() => void updateImage(true)}>Quitar imagen</button></div>
              </div>}
              <div className="detail-status"><span className={stateClass(selected.editorial_state)}>{selected.editorial_state}</span><span className={`priority priority-${selected.priority.toLowerCase()}`}>{selected.priority}</span></div>
              <p>{selected.summary || "Esta noticia todavía no tiene resumen."}</p>
              <dl><div><dt>Responsable</dt><dd>{selected.assigned_name}</dd></div><div><dt>Municipio</dt><dd>{selected.municipality}</dd></div><div><dt>Categoría</dt><dd>{selected.category}</dd></div><div><dt>Último cambio</dt><dd>{when(selected.updated_at)}</dd></div></dl>
              <div className="editorial-source-detail"><div><span>Fuente original</span><strong>{selected.source || "Sin identificar"}</strong></div>{selected.url ? <a className="button secondary" href={selected.url} target="_blank" rel="noreferrer">Abrir publicación original ↗</a> : <small>Esta noticia no incluye un enlace de origen.</small>}</div>
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
