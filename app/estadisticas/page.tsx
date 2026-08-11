"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "@/lib/api";
import type { AnalyticsPoint, AnalyticsReport } from "@/types/news";

const periods = [
  { value: 7, label: "7 días" },
  { value: 30, label: "30 días" },
  { value: 90, label: "90 días" },
];

function shortDate(value: string) {
  return new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short" }).format(new Date(`${value}T12:00:00Z`));
}

function BreakdownCard({ title, subtitle, items, tone }: {
  title: string;
  subtitle: string;
  items: AnalyticsPoint[];
  tone: string;
}) {
  const maximum = Math.max(...items.map((item) => item.value), 1);
  return (
    <article className="analytics-breakdown panel">
      <div className="panel-header">
        <div><h2>{title}</h2><p>{subtitle}</p></div>
        <span className="analytics-total">{items.reduce((sum, item) => sum + item.value, 0)}</span>
      </div>
      <div className="analytics-bars">
        {items.map((item) => (
          <div className="analytics-bar-row" key={item.label}>
            <div><strong title={item.label}>{item.label}</strong><span>{item.value}</span></div>
            <div className="analytics-track"><span className={tone} style={{ width: `${(item.value / maximum) * 100}%` }} /></div>
          </div>
        ))}
        {items.length === 0 && <p className="analytics-empty">No hay datos en este periodo.</p>}
      </div>
    </article>
  );
}

export default function AnalyticsPage() {
  const [days, setDays] = useState(30);
  const [report, setReport] = useState<AnalyticsReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setReport(await api.analytics(days));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudieron cargar las estadísticas.");
    } finally {
      setLoading(false);
    }
  }, [days]);

  useEffect(() => {
    let active = true;
    api.analytics(days)
      .then((data) => { if (active) setReport(data); })
      .catch((caught) => {
        if (active) setError(caught instanceof Error ? caught.message : "No se pudieron cargar las estadísticas.");
      })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [days]);

  const maximumTrend = useMemo(
    () => Math.max(1, ...(report?.trend.flatMap((point) => [point.created, point.published]) || [1])),
    [report],
  );

  async function exportReport() {
    setExporting(true);
    setError("");
    try {
      await api.downloadAnalytics(days);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo descargar el reporte.");
    } finally {
      setExporting(false);
    }
  }

  function changePeriod(value: number) {
    setLoading(true);
    setError("");
    setDays(value);
  }

  const summary = report?.summary;
  const cards = [
    { label: "Noticias creadas", value: summary?.created, detail: `${summary?.created_change ?? 0}% vs. periodo anterior`, icon: "▤", tone: "blue" },
    { label: "Publicadas", value: summary?.published, detail: `${summary?.publication_rate ?? 0}% de lo creado`, icon: "✓", tone: "green" },
    { label: "Pendientes", value: summary?.pending, detail: "Carga editorial actual", icon: "◷", tone: "orange" },
    { label: "Urgentes", value: summary?.urgent, detail: "Activas en el sistema", icon: "!", tone: "red" },
  ];

  return (
    <main>
      <div className="page-heading analytics-heading">
        <div>
          <p className="eyebrow">VERSIÓN 1.2 · INTELIGENCIA EDITORIAL</p>
          <h1>Estadísticas</h1>
          <p>Descubre qué se publica, de dónde viene y qué zonas requieren atención.</p>
        </div>
        <div className="analytics-actions">
          <select value={days} onChange={(event) => changePeriod(Number(event.target.value))} aria-label="Periodo del reporte">
            {periods.map((period) => <option value={period.value} key={period.value}>Últimos {period.label}</option>)}
          </select>
          <button className="button secondary" onClick={() => void load()} disabled={loading}>↻ Actualizar</button>
          <button className="button primary" onClick={exportReport} disabled={exporting || loading}>⇩ {exporting ? "Exportando…" : "Exportar Excel"}</button>
        </div>
      </div>

      {error && <div className="alert error">{error}</div>}

      <section className="stats-grid" aria-label="Indicadores editoriales">
        {cards.map((card) => (
          <article className="stat-card" key={card.label}>
            <div className={`stat-icon ${card.tone}`}>{card.icon}</div>
            <div><span>{card.label}</span><strong>{loading ? "—" : card.value ?? 0}</strong><small>{card.detail}</small></div>
          </article>
        ))}
      </section>

      <section className="panel analytics-trend-panel">
        <div className="panel-header">
          <div><h2>Evolución del contenido</h2><p>Noticias creadas y publicadas por día</p></div>
          <div className="analytics-legend"><span><i className="created" /> Creadas</span><span><i className="published" /> Publicadas</span></div>
        </div>
        <div className={`analytics-trend ${days === 90 ? "dense" : ""}`}>
          {report?.trend.map((point, index) => {
            const labelEvery = days === 7 ? 1 : days === 30 ? 5 : 15;
            const showLabel = index === 0 || index === report.trend.length - 1 || index % labelEvery === 0;
            return (
              <div className="trend-day" key={point.date} title={`${shortDate(point.date)}: ${point.created} creadas, ${point.published} publicadas`}>
                <div className="trend-columns">
                  <span className="created" style={{ height: `${Math.max(3, (point.created / maximumTrend) * 100)}%` }} />
                  <span className="published" style={{ height: `${Math.max(3, (point.published / maximumTrend) * 100)}%` }} />
                </div>
                <small>{showLabel ? shortDate(point.date) : ""}</small>
              </div>
            );
          })}
          {!loading && (!report || report.trend.length === 0) && <p className="analytics-empty">No hay actividad en este periodo.</p>}
          {loading && <p className="analytics-empty">Calculando tendencias…</p>}
        </div>
      </section>

      <section className="analytics-performance">
        <article className="panel">
          <div className="panel-header"><div><h2>Desempeño editorial</h2><p>Indicadores del periodo seleccionado</p></div></div>
          <div className="performance-grid">
            {[
              { label: "Contenido publicado", value: summary?.publication_rate ?? 0, detail: `${summary?.published ?? 0} publicaciones` },
              { label: "Apoyo de IA", value: summary?.ai_rate ?? 0, detail: `${summary?.ai_created ?? 0} noticias preparadas` },
              { label: "Cobertura geográfica", value: summary?.mapped_rate ?? 0, detail: `${summary?.mapped ?? 0} noticias ubicadas` },
            ].map((item) => (
              <div className="performance-item" key={item.label}>
                <div><strong>{item.label}</strong><span>{item.value}%</span></div>
                <div className="performance-track"><span style={{ width: `${Math.min(item.value, 100)}%` }} /></div>
                <small>{item.detail}</small>
              </div>
            ))}
          </div>
        </article>
        <BreakdownCard title="Flujo editorial" subtitle="Estado actual del contenido del periodo" items={report?.statuses || []} tone="purple" />
      </section>

      <section className="analytics-breakdown-grid">
        <BreakdownCard title="Categorías" subtitle="Temas con mayor actividad" items={report?.categories || []} tone="blue" />
        <BreakdownCard title="Municipios" subtitle="Cobertura territorial" items={report?.municipalities || []} tone="green" />
        <BreakdownCard title="Fuentes" subtitle="Origen de las noticias" items={report?.sources || []} tone="orange" />
      </section>

      {report && <p className="analytics-updated">Actualizado: {new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(report.generated_at))}</p>}
    </main>
  );
}
