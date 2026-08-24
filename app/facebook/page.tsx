"use client";

import Link from "next/link";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AIStatus, FacebookPost, FacebookStatus } from "@/types/news";

function dateTime(value: string | null) {
  if (!value) return "Sin sincronizar";
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export default function FacebookPage() {
  const [status, setStatus] = useState<FacebookStatus | null>(null);
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null);
  const [posts, setPosts] = useState<FacebookPost[]>([]);
  const [pendingOnly, setPendingOnly] = useState(true);
  const [pageId, setPageId] = useState("");
  const [pageToken, setPageToken] = useState("");
  const [loading, setLoading] = useState(true);
  const [connecting, setConnecting] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [diagnosing, setDiagnosing] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [importing, setImporting] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [connection, postData, editorialAI] = await Promise.all([
        api.facebookStatus(), api.listFacebookPosts(pendingOnly), api.aiStatus(),
      ]);
      setStatus(connection);
      setPageId((current) => current || connection.page_id);
      setPosts(postData.items);
      setAIStatus(editorialAI);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo cargar Facebook.");
    } finally {
      setLoading(false);
    }
  }, [pendingOnly]);

  useEffect(() => {
    const timer = window.setTimeout(load, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    setConnecting(true);
    setError("");
    setMessage("");
    try {
      const connection = await api.connectFacebook(pageId.trim(), pageToken.trim());
      setStatus(connection);
      setPageToken("");
      setReconnecting(false);
      setMessage(`La página ${connection.page_name} quedó conectada correctamente.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo conectar la página.");
    } finally {
      setConnecting(false);
    }
  }

  async function diagnose() {
    setDiagnosing(true);
    setError("");
    setMessage("");
    try {
      const connection = await api.diagnoseFacebook();
      setStatus(connection);
      if (connection.health === "ok") {
        setMessage("La conexión con Meta funciona correctamente.");
      } else if (connection.needs_reconnect) {
        setError(connection.health_message);
        setReconnecting(true);
      } else {
        setError(connection.health_message);
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo comprobar la conexión con Meta.");
    } finally {
      setDiagnosing(false);
    }
  }

  async function sync() {
    setSyncing(true);
    setError("");
    setMessage("");
    try {
      const result = await api.syncFacebook();
      setMessage(`Sincronización terminada: ${result.detected} publicación${result.detected === 1 ? " nueva" : "es nuevas"}.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo sincronizar Facebook.");
    } finally {
      setSyncing(false);
    }
  }

  async function preparePost(post: FacebookPost) {
    setImporting(post.id);
    setError("");
    setMessage("");
    try {
      const result = await api.prepareFacebookPost(post.id);
      const assistant = result.provider === "openai" ? "OpenAI" : "el analizador local";
      setMessage(`Borrador preparado con ${assistant}: “${result.news.title}”.`);
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo preparar la publicación.");
    } finally {
      setImporting(null);
    }
  }

  async function disconnect() {
    if (!window.confirm("¿Desconectar la página de Facebook? Las publicaciones ya detectadas no se eliminarán.")) return;
    try {
      await api.disconnectFacebook();
      setMessage("La página quedó desconectada.");
      await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo desconectar Facebook.");
    }
  }

  return (
    <main>
      <div className="page-heading facebook-heading">
        <div><p className="eyebrow">FASE 5 · FLUJO INTELIGENTE</p><h1>Facebook</h1><p>Sincroniza publicaciones y conviértelas en borradores editoriales listos para revisar.</p></div>
        {status?.connected && <div className="heading-actions"><button className="button secondary" onClick={diagnose} disabled={diagnosing}>{diagnosing ? "Comprobando…" : "Comprobar conexión"}</button><button className="button secondary" onClick={() => { setPageId(status.page_id); setReconnecting(true); }}>Reconectar Facebook</button><button className="button facebook-button" onClick={sync} disabled={syncing || status.needs_reconnect}>{syncing ? "Sincronizando…" : "Sincronizar ahora"}</button></div>}
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert success">{message} {message.includes("Borrador") && <Link href="/noticias">Revisar en Noticias →</Link>}</div>}

      {!loading && (!status?.connected || reconnecting) ? (
        <div className="facebook-connect-grid">
          <section className="panel facebook-intro">
            <div className="facebook-logo">f</div>
            <p className="eyebrow">CONEXIÓN OFICIAL DE META</p>
            <h2>{reconnecting ? "Renueva la conexión" : "Conecta una página autorizada"}</h2>
            <p>Pulso Monitor utilizará Graph API {status?.graph_version || "v26.0"} para leer las publicaciones creadas por una página que administras.</p>
            <ul><li>No accede a perfiles personales.</li><li>No consulta grupos privados.</li><li>No publica nada automáticamente.</li><li>El token permanece únicamente en tu computadora.</li></ul>
            <a className="text-link" href="https://developers.facebook.com/docs/pages-api/getting-started/" target="_blank" rel="noreferrer">Consultar guía oficial de Meta ↗</a>
          </section>
          <section className="panel facebook-connect-form">
            <div className="panel-header"><div><h2>{reconnecting ? "Nuevo acceso de Facebook" : "Datos de la página"}</h2><p>Necesitas el ID y un Page Access Token válido.</p></div>{reconnecting && <button className="button secondary" type="button" onClick={() => setReconnecting(false)}>Cancelar</button>}</div>
            <form onSubmit={connect}>
              <label>ID de la página *<input required minLength={3} value={pageId} onChange={(event) => setPageId(event.target.value)} placeholder="Ej. 123456789012345" /></label>
              <label>Page Access Token *<textarea required minLength={30} rows={5} value={pageToken} onChange={(event) => setPageToken(event.target.value)} placeholder="Pega aquí el token generado por Meta…" autoComplete="off" /></label>
              <div className="token-notice"><strong>Dato privado</strong><span>No pegues este token en el chat ni lo compartas con otras personas.</span></div>
              <button className="button facebook-button wide" disabled={connecting}>{connecting ? "Validando con Meta…" : "Conectar página"}</button>
            </form>
          </section>
        </div>
      ) : (
        <>
          <div className="stats-grid facebook-stats">
            <div className="stat-card"><div className="stat-icon facebook">f</div><div><span>Página conectada</span><strong className="page-name-stat">{status?.page_name || "—"}</strong><small>ID {status?.page_id || "—"}</small></div></div>
            <div className="stat-card"><div className="stat-icon orange">◉</div><div><span>Por revisar</span><strong>{status?.pending || 0}</strong><small>publicaciones nuevas</small></div></div>
            <div className="stat-card"><div className="stat-icon green">✓</div><div><span>Importadas</span><strong>{status?.imported || 0}</strong><small>en el módulo Noticias</small></div></div>
            <div className="stat-card"><div className="stat-icon blue">↻</div><div><span>Última sincronización</span><strong className="sync-date-stat">{dateTime(status?.last_sync || null)}</strong><small>{status?.graph_version}</small></div></div>
          </div>

          {status?.health === "ok" && <div className="alert success">✓ {status.health_message} <button className="text-link" onClick={diagnose} disabled={diagnosing}>Comprobar ahora</button></div>}
          {status?.health !== "ok" && status?.connected && <div className="alert error">{status.health_message} {status.needs_reconnect && <button className="text-link" onClick={() => { setPageId(status.page_id); setReconnecting(true); }}>Reconectar Facebook</button>}</div>}

          <section className="panel facebook-posts">
            <div className="panel-header findings-header"><div><h2>Publicaciones detectadas</h2><p>El asistente sugiere título, resumen, categoría, prioridad y etiquetas.</p></div><div className="facebook-review-tools"><span className={`ai-mode ${aiStatus?.connected ? "connected" : ""}`}>✦ {aiStatus?.connected ? "OpenAI conectado" : "Analizador local"}</span><div className="radar-tabs"><button className={pendingOnly ? "active" : ""} onClick={() => setPendingOnly(true)}>Por revisar</button><button className={!pendingOnly ? "active" : ""} onClick={() => setPendingOnly(false)}>Todas</button></div></div></div>
            <div className="facebook-post-list">
              {posts.map((post) => (
                <article className="facebook-post-card" key={post.id}>
                  {post.picture_url ? <div className="facebook-post-image" role="img" aria-label="Imagen de la publicación" style={{ backgroundImage: `url(${JSON.stringify(post.picture_url)})` }} /> : <div className="facebook-post-placeholder">f</div>}
                  <div className="facebook-post-copy"><div className="finding-badges"><span className="tag">Facebook</span><span>{dateTime(post.created_time || post.detected_at)}</span></div><p>{post.message}</p>{post.permalink_url && <a href={post.permalink_url} target="_blank" rel="noreferrer">Abrir publicación original ↗</a>}</div>
                  <div className="finding-actions">{post.imported_news_id ? <span className="imported-badge">✓ Preparada</span> : <button className="button primary" onClick={() => preparePost(post)} disabled={importing === post.id}>{importing === post.id ? "Analizando…" : "✦ Preparar con IA"}</button>}</div>
                </article>
              ))}
              {loading && <div className="radar-empty"><span>Cargando publicaciones…</span></div>}
              {!loading && posts.length === 0 && <div className="radar-empty"><div>f</div><strong>No hay publicaciones por revisar</strong><span>Pulsa “Sincronizar ahora” para buscar contenido nuevo en la página conectada.</span></div>}
            </div>
          </section>
        </>
      )}
    </main>
  );
}
