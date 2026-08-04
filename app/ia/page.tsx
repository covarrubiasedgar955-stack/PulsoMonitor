"use client";

import Link from "next/link";
import { FormEvent, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { AIAnalysis, AIStatus, AITone, NewsInput, NewsPriority } from "@/types/news";

const tones: AITone[] = ["Informativo", "Urgente", "Institucional", "Cercano"];
const priorities: NewsPriority[] = ["Baja", "Media", "Alta", "Urgente"];
const categories = ["General", "Seguridad", "Política", "Deportes", "Eventos", "Turismo", "Servicios", "Comunidad"];
const example = "Protección Civil de Tequila atendió esta tarde un accidente sobre la carretera libre a Guadalajara, a la altura del crucero. La circulación presenta carga vehicular y las autoridades recomiendan manejar con precaución. Hasta el momento no se ha confirmado el número de personas lesionadas.";

export default function AIPage() {
  const [sourceText, setSourceText] = useState("");
  const [municipality, setMunicipality] = useState("Tequila");
  const [source, setSource] = useState("Reporte recibido");
  const [tone, setTone] = useState<AITone>("Informativo");
  const [result, setResult] = useState<AIAnalysis | null>(null);
  const [tagText, setTagText] = useState("");
  const [aiStatus, setAIStatus] = useState<AIStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [showConfig, setShowConfig] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [configuring, setConfiguring] = useState(false);

  useEffect(() => {
    api.aiStatus().then(setAIStatus).catch(() => setAIStatus(null));
  }, []);

  async function analyze(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    setSuccess("");
    try {
      const analysis = await api.analyzeWithAI({ source_text: sourceText, municipality, source, tone });
      setResult(analysis);
      setTagText(analysis.tags.join(", "));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo analizar la información.");
    } finally {
      setLoading(false);
    }
  }

  async function configure(event: FormEvent) {
    event.preventDefault();
    setConfiguring(true);
    setError("");
    try {
      const status = await api.configureAI(apiKey);
      setAIStatus(status);
      setApiKey("");
      setShowConfig(false);
      setSuccess("OpenAI quedó conectado correctamente.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo conectar OpenAI.");
    } finally {
      setConfiguring(false);
    }
  }

  async function saveNews() {
    if (!result) return;
    setSaving(true);
    setError("");
    const payload: NewsInput = {
      title: result.title,
      summary: result.summary,
      content: result.content,
      source,
      author: "Redacción Pulso Tequila",
      municipality,
      category: result.category,
      priority: result.priority,
      status: "Pendiente",
      image_url: "",
      url: "",
      published_at: null,
      is_ai: true,
      tags: tagText.split(",").map((tag) => tag.trim()).filter(Boolean),
    };
    try {
      await api.createNews(payload);
      setSuccess("La propuesta se guardó como noticia pendiente.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo guardar la noticia.");
    } finally {
      setSaving(false);
    }
  }

  async function copyText() {
    if (!result) return;
    await navigator.clipboard.writeText(`${result.title}\n\n${result.content}`);
    setSuccess("Texto copiado al portapapeles.");
  }

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">FASE 2 · REDACCIÓN ASISTIDA</p><h1>Asistente IA</h1><p>Convierte reportes y publicaciones en propuestas listas para revisar.</p></div>
        <div className={`connection-badge ${aiStatus?.connected ? "connected" : "local"}`}>
          <span />{aiStatus?.connected ? `OpenAI · ${aiStatus.model}` : "Modo local"}
        </div>
      </div>

      {!aiStatus?.connected && (
        <div className="ai-notice">
          <div><strong>El asistente ya funciona en modo local.</strong><span>Conecta OpenAI para obtener redacciones más naturales y precisas.</span></div>
          <button className="button secondary" onClick={() => setShowConfig((value) => !value)}>{showConfig ? "Cerrar" : "Conectar OpenAI"}</button>
        </div>
      )}

      {showConfig && (
        <section className="panel ai-config">
          <div><h2>Conectar OpenAI</h2><p>La clave se guarda únicamente en tu computadora y nunca se muestra después.</p></div>
          <form onSubmit={configure}>
            <input type="password" required minLength={20} value={apiKey} onChange={(event) => setApiKey(event.target.value)} placeholder="Clave que comienza con sk-…" autoComplete="off" />
            <button className="button primary" disabled={configuring}>{configuring ? "Validando…" : "Guardar conexión"}</button>
          </form>
          <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" className="text-link">Crear una clave en OpenAI ↗</a>
        </section>
      )}

      {error && <div className="alert error">{error}</div>}
      {success && <div className="alert success">{success} {success.includes("noticia") && <Link href="/noticias">Ver noticias →</Link>}</div>}

      <div className="ai-grid">
        <section className="panel ai-source-panel">
          <div className="panel-header"><div><h2>Información original</h2><p>Pega el reporte tal como lo recibiste.</p></div><button className="text-link" onClick={() => setSourceText(example)}>Usar ejemplo</button></div>
          <form onSubmit={analyze} className="ai-source-form">
            <label>Texto para analizar *<textarea className="source-textarea" required minLength={30} maxLength={12000} value={sourceText} onChange={(event) => setSourceText(event.target.value)} placeholder="Pega aquí una publicación, reporte ciudadano, comunicado o tus apuntes…" /></label>
            <div className="compact-fields">
              <label>Municipio<input value={municipality} onChange={(event) => setMunicipality(event.target.value)} /></label>
              <label>Fuente<input value={source} onChange={(event) => setSource(event.target.value)} /></label>
            </div>
            <label>Tono<select value={tone} onChange={(event) => setTone(event.target.value as AITone)}>{tones.map((value) => <option key={value}>{value}</option>)}</select></label>
            <div className="character-count">{sourceText.length.toLocaleString("es-MX")} / 12,000 caracteres</div>
            <button className="button primary wide ai-analyze-button" disabled={loading}>{loading ? "Analizando información…" : "✦ Generar propuesta"}</button>
          </form>
        </section>

        <section className={`panel ai-result-panel ${result ? "has-result" : ""}`}>
          {!result ? (
            <div className="ai-empty"><div>✦</div><h2>Tu propuesta aparecerá aquí</h2><p>El asistente sugerirá título, resumen, redacción, categoría, prioridad y etiquetas.</p></div>
          ) : (
            <>
              <div className="panel-header">
                <div><h2>Propuesta editorial</h2><p>{result.provider === "openai" ? `Generada con ${result.model}` : "Generada con el analizador local"} · Confianza {result.confidence}%</p></div>
                <button className="button secondary" onClick={copyText}>Copiar</button>
              </div>
              <div className="ai-result-form">
                {result.warnings.length > 0 && <div className="ai-warnings"><strong>Antes de publicar:</strong>{result.warnings.map((warning) => <span key={warning}>• {warning}</span>)}</div>}
                <label>Título<input value={result.title} onChange={(event) => setResult({ ...result, title: event.target.value })} /></label>
                <label>Resumen<textarea rows={3} value={result.summary} onChange={(event) => setResult({ ...result, summary: event.target.value })} /></label>
                <label>Contenido<textarea rows={10} value={result.content} onChange={(event) => setResult({ ...result, content: event.target.value })} /></label>
                <div className="compact-fields">
                  <label>Categoría<select value={result.category} onChange={(event) => setResult({ ...result, category: event.target.value })}>{categories.map((value) => <option key={value}>{value}</option>)}</select></label>
                  <label>Prioridad<select value={result.priority} onChange={(event) => setResult({ ...result, priority: event.target.value as NewsPriority })}>{priorities.map((value) => <option key={value}>{value}</option>)}</select></label>
                </div>
                <label>Etiquetas<input value={tagText} onChange={(event) => setTagText(event.target.value)} /></label>
                <div className="ai-actions"><button className="button secondary" onClick={() => setResult(null)}>Descartar</button><button className="button primary" onClick={saveNews} disabled={saving}>{saving ? "Guardando…" : "Guardar como pendiente"}</button></div>
              </div>
            </>
          )}
        </section>
      </div>
    </main>
  );
}
