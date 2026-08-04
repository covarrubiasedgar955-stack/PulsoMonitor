"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";

const navigation = [
  { href: "/", label: "Dashboard", icon: "▦", ready: true },
  { href: "/noticias", label: "Noticias", icon: "▤", ready: true },
  { href: "/ia", label: "Asistente IA", icon: "✦", ready: true },
  { href: "#", label: "Radar", icon: "⌖", ready: false },
  { href: "#", label: "Municipios", icon: "⌂", ready: false },
  { href: "#", label: "Configuración", icon: "⚙", ready: false },
];

function Login({ onSuccess }: { onSuccess: () => void }) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError("");
    try {
      const result = await api.login(username, password);
      localStorage.setItem("pulso_token", result.access_token);
      localStorage.setItem("pulso_user", JSON.stringify(result.user));
      onSuccess();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "No se pudo iniciar sesión.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="login-page">
      <section className="login-card">
        <div className="brand-mark large">P</div>
        <p className="eyebrow">CENTRO DE MONITOREO</p>
        <h1>Pulso Monitor</h1>
        <p className="login-copy">Administra las noticias de Pulso Tequila desde un solo lugar.</p>
        <form onSubmit={submit} className="login-form">
          <label>
            Usuario
            <input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            Contraseña
            <input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </label>
          {error && <div className="alert error">{error}</div>}
          <button className="button primary wide" disabled={loading}>
            {loading ? "Ingresando…" : "Entrar al sistema"}
          </button>
        </form>
        <p className="login-hint">Acceso inicial: admin / admin123</p>
      </section>
    </main>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const sync = () => setAuthenticated(Boolean(localStorage.getItem("pulso_token")));
    sync();
    window.addEventListener("pulso:logout", sync);
    return () => window.removeEventListener("pulso:logout", sync);
  }, []);

  if (authenticated === null) return <div className="splash">Cargando Pulso Monitor…</div>;
  if (!authenticated) return <Login onSuccess={() => setAuthenticated(true)} />;

  function logout() {
    localStorage.removeItem("pulso_token");
    localStorage.removeItem("pulso_user");
    setAuthenticated(false);
  }

  return (
    <div className="app-frame">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark">P</div>
          <div><strong>Pulso</strong><span>Monitor</span></div>
        </div>
        <nav aria-label="Navegación principal">
          {navigation.map((item) =>
            item.ready ? (
              <Link
                key={item.label}
                href={item.href}
                onClick={() => setMenuOpen(false)}
                className={pathname === item.href ? "active" : ""}
              >
                <span>{item.icon}</span>{item.label}
              </Link>
            ) : (
              <button key={item.label} className="nav-disabled" title="Disponible próximamente">
                <span>{item.icon}</span>{item.label}<small>Próximamente</small>
              </button>
            )
          )}
        </nav>
        <div className="sidebar-footer">
          <span className="status-dot" /> API local
          <small>Versión 0.2</small>
        </div>
      </aside>
      {menuOpen && <button className="backdrop" aria-label="Cerrar menú" onClick={() => setMenuOpen(false)} />}
      <div className="workspace">
        <header className="topbar">
          <button className="menu-button" onClick={() => setMenuOpen(true)} aria-label="Abrir menú">☰</button>
          <div>
            <strong>Pulso Monitor</strong>
            <span>Centro inteligente de monitoreo de noticias</span>
          </div>
          <div className="profile">
            <div className="avatar">E</div>
            <div><strong>Edgar</strong><span>Administrador</span></div>
            <button onClick={logout} title="Cerrar sesión">Salir</button>
          </div>
        </header>
        <div className="page-content">{children}</div>
      </div>
    </div>
  );
}
