"use client";

import { APP_VERSION } from "@/lib/version";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { FormEvent, ReactNode, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { UserInfo } from "@/types/news";

const navigation = [
  { href: "/", label: "Dashboard", icon: "▦", ready: true },
  { href: "/calendario", label: "Calendario", icon: "□", ready: true },
  { href: "/revision", label: "Revisión editorial", icon: "✓", ready: true },
  { href: "/estadisticas", label: "Estadísticas", icon: "▥", ready: true },
  { href: "/automatizaciones", label: "Automatizaciones", icon: "↻", ready: true, adminOnly: true },
  { href: "/noticias", label: "Noticias", icon: "▤", ready: true },
  { href: "/ia", label: "Asistente IA", icon: "✦", ready: true },
  { href: "/radar", label: "Radar", icon: "⌖", ready: true },
  { href: "/facebook", label: "Facebook", icon: "f", ready: true },
  { href: "/publicaciones", label: "Publicaciones", icon: "◫", ready: true },
  { href: "/municipios", label: "Municipios", icon: "⌂", ready: true },
  { href: "/mapa", label: "Mapa", icon: "⌖", ready: true },
  { href: "/usuarios", label: "Usuarios", icon: "♟", ready: true, adminOnly: true },
  { href: "/configuracion", label: "Configuración", icon: "⚙", ready: true, adminOnly: true },
];

function Login({ onSuccess }: { onSuccess: (user: UserInfo) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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
      onSuccess(result.user);
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
            <input required value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" />
          </label>
          <label>
            Contraseña
            <input required type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
          </label>
          {error && <div className="alert error">{error}</div>}
          <button className="button primary wide" disabled={loading}>
            {loading ? "Ingresando…" : "Entrar al sistema"}
          </button>
        </form>
        <p className="login-hint">Tus datos de acceso están en el archivo ACCESO.txt.</p>
      </section>
    </main>
  );
}

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [authenticated, setAuthenticated] = useState<boolean | null>(null);
  const [user, setUser] = useState<UserInfo | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const sync = () => {
      const active = Boolean(localStorage.getItem("pulso_token"));
      setAuthenticated(active);
      try {
        setUser(active ? JSON.parse(localStorage.getItem("pulso_user") || "null") : null);
      } catch {
        setUser(null);
      }
    };
    sync();
    window.addEventListener("pulso:logout", sync);
    return () => window.removeEventListener("pulso:logout", sync);
  }, []);

  if (authenticated === null) return <div className="splash">Cargando Pulso Monitor…</div>;
  if (!authenticated) return <Login onSuccess={(signedInUser) => { setUser(signedInUser); setAuthenticated(true); }} />;

  function logout() {
    localStorage.removeItem("pulso_token");
    localStorage.removeItem("pulso_user");
    setUser(null);
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
          {navigation.filter((item) => !item.adminOnly || user?.role === "Administrador").map((item) =>
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
          <small>Versión {APP_VERSION}</small>
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
            <div className="avatar">{user?.name?.charAt(0).toUpperCase() || "U"}</div>
            <div><strong>{user?.name || "Usuario"}</strong><span>{user?.role || "Sesión activa"}</span></div>
            <button onClick={logout} title="Cerrar sesión">Salir</button>
          </div>
        </header>
        <div className="page-content">{children}</div>
      </div>
    </div>
  );
}
