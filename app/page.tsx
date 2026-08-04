"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { NewsItem, NewsStats } from "@/types/news";

const emptyStats: NewsStats = { today: 0, pending: 0, published: 0, urgent: 0, total: 0 };

function formatDate(value: string) {
  return new Intl.DateTimeFormat("es-MX", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export default function DashboardPage() {
  const [stats, setStats] = useState(emptyStats);
  const [news, setNews] = useState<NewsItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.stats(), api.listNews({ limit: 5 })])
      .then(([statData, newsData]) => {
        setStats(statData);
        setNews(newsData.items);
      })
      .catch((caught) => setError(caught instanceof Error ? caught.message : "No fue posible conectar con la API."))
      .finally(() => setLoading(false));
  }, []);

  const cards = [
    { label: "Noticias hoy", value: stats.today, icon: "▤", tone: "blue" },
    { label: "Pendientes", value: stats.pending, icon: "◷", tone: "orange" },
    { label: "Publicadas", value: stats.published, icon: "✓", tone: "green" },
    { label: "Urgentes", value: stats.urgent, icon: "!", tone: "red" },
  ];

  return (
    <main>
      <div className="page-heading">
        <div><p className="eyebrow">RESUMEN GENERAL</p><h1>Dashboard</h1><p>Lo más importante de Pulso Tequila, en un vistazo.</p></div>
        <Link href="/noticias" className="button primary">Administrar noticias</Link>
      </div>

      {error && <div className="alert error"><strong>Backend sin conexión.</strong> {error} Inicia el archivo <code>iniciar.bat</code>.</div>}

      <section className="stats-grid" aria-label="Estadísticas">
        {cards.map((card) => (
          <article className="stat-card" key={card.label}>
            <div className={`stat-icon ${card.tone}`}>{card.icon}</div>
            <div><span>{card.label}</span><strong>{loading ? "—" : card.value}</strong><small>Datos en tiempo real</small></div>
          </article>
        ))}
      </section>

      <section className="panel">
        <div className="panel-header">
          <div><h2>Últimas noticias</h2><p>Contenido agregado recientemente</p></div>
          <Link href="/noticias" className="text-link">Ver todas →</Link>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Noticia</th><th>Municipio</th><th>Categoría</th><th>Estado</th><th>Fecha</th></tr></thead>
            <tbody>
              {news.map((item) => (
                <tr key={item.id}>
                  <td><strong>{item.title}</strong><small>{item.source}</small></td>
                  <td>{item.municipality}</td>
                  <td><span className="tag">{item.category}</span></td>
                  <td><span className={`status status-${item.status.toLowerCase().replaceAll(" ", "-").replace("ó", "o")}`}>{item.status}</span></td>
                  <td>{formatDate(item.created_at)}</td>
                </tr>
              ))}
              {!loading && news.length === 0 && <tr><td colSpan={5} className="empty">Todavía no hay noticias.</td></tr>}
              {loading && <tr><td colSpan={5} className="empty">Cargando noticias…</td></tr>}
            </tbody>
          </table>
        </div>
      </section>
    </main>
  );
}
