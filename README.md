# Pulso Monitor v0.1

Centro local de administración de noticias para **Pulso Tequila**. Esta primera versión incluye un dashboard, estadísticas reales, inicio de sesión, buscador, filtros y gestión completa de noticias mediante una API con base de datos SQLite.

## Funciones disponibles

- Inicio de sesión de administrador.
- Dashboard con noticias del día, pendientes, publicadas y urgentes.
- Alta, edición y eliminación de noticias.
- Búsqueda por título, resumen, fuente, municipio y categoría.
- Filtros por estado y prioridad.
- Base de datos SQLite creada automáticamente.
- API FastAPI documentada en Swagger.
- Diseño adaptable para computadora, tableta y celular.

## Instalación rápida en Windows

1. Descarga o actualiza el repositorio.
2. Haz doble clic en `instalar.bat` y espera a que termine.
3. Haz doble clic en `iniciar.bat`.
4. Se abrirá `http://localhost:3000` en el navegador.

Acceso inicial:

```text
Usuario: admin
Contraseña: admin123
```

> La contraseña inicial está pensada para uso local. Antes de publicar el sistema en internet, configura credenciales y una clave secreta propias mediante las variables incluidas en `backend/.env.example`.

## Inicio manual

Backend:

```powershell
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Frontend, en otra terminal:

```powershell
npm install
npm run dev
```

## Direcciones locales

- Panel: http://localhost:3000
- API: http://127.0.0.1:8000
- Documentación de la API: http://127.0.0.1:8000/docs
- Estado de la API: http://127.0.0.1:8000/health

## Estructura

```text
app/                 Panel Next.js
components/          Navegación e inicio de sesión
lib/                 Cliente de la API
types/               Tipos de noticias
backend/main.py      API FastAPI y acceso a SQLite
backend/test_api.py  Pruebas del CRUD
instalar.bat         Instalación automática para Windows
iniciar.bat          Arranque automático para Windows
```

## Alcance de esta versión

La v0.1 administra noticias capturadas en el panel. La conexión autorizada con fuentes externas y las funciones de redacción asistida por IA se incorporarán en versiones posteriores.
