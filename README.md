# Pulso Monitor v0.6

Centro local de administración, redacción y detección de noticias para **Pulso Tequila**. Incluye dashboard, gestión editorial, Asistente IA, Radar de fuentes y conexión autorizada con Facebook.

## Funciones disponibles

- Inicio de sesión de administrador.
- Dashboard con noticias del día, pendientes, publicadas y urgentes.
- Alta, edición y eliminación de noticias.
- Búsqueda por título, resumen, fuente, municipio y categoría.
- Filtros por estado y prioridad.
- Base de datos SQLite creada automáticamente.
- API FastAPI documentada en Swagger.
- Diseño adaptable para computadora, tableta y celular.
- Asistente IA para sugerir título, resumen, redacción, categoría, prioridad y etiquetas.
- Modo local disponible sin servicios externos.
- Conexión opcional con OpenAI mediante la Responses API y resultados estructurados.
- Guardado directo de las propuestas como noticias pendientes.
- Registro de fuentes públicas con canales RSS o Atom.
- Escaneo manual de todas las fuentes o de una fuente individual.
- Detección automática de duplicados por identificador de origen.
- Importación de hallazgos como noticias pendientes.
- Conexión con una página administrada mediante Meta Graph API v26.0.
- Sincronización de publicaciones de Facebook sin duplicados.
- Importación de publicaciones de Facebook como noticias pendientes.
- Preparación inteligente de publicaciones de Facebook con título, resumen, categoría, prioridad y etiquetas sugeridas.
- Revisión humana obligatoria antes de publicar cualquier borrador preparado por el asistente.
- Cola editorial para aprobar y publicar noticias en una página de Facebook conectada.
- Programación administrada por Meta entre 10 minutos y 75 días.
- Cancelación segura de publicaciones programadas antes de su salida.

## Instalación rápida en Windows

1. Descarga o actualiza el repositorio.
2. Haz doble clic en `instalar.bat` y espera a que termine.
3. Haz doble clic en `iniciar.bat`.
4. Se abrirá `http://127.0.0.1:3010` en el navegador.

Durante la instalación se genera automáticamente una contraseña única. Los datos aparecen en `ACCESO.txt`, un archivo local excluido de Git. Guárdalo en un lugar seguro y no lo compartas.

## Asistente IA

El módulo **Asistente IA** funciona inmediatamente en modo local. Para activar la redacción avanzada:

1. Entra a `Asistente IA` desde el menú.
2. Pulsa `Conectar OpenAI`.
3. Crea una clave en https://platform.openai.com/api-keys.
4. Pega la clave en el formulario local y pulsa `Guardar conexión`.

La clave se valida y se guarda solamente en `backend/.env` dentro de la computadora. Este archivo está excluido de Git.

## Radar de fuentes

El módulo **Radar** consulta únicamente canales RSS o Atom públicos que el administrador registra expresamente:

1. Entra a `Radar` y pulsa `Agregar fuente`.
2. Escribe el nombre, municipio, categoría y la dirección del canal RSS o Atom.
3. Pulsa `Escanear` para detectar publicaciones nuevas.
4. Revisa cada hallazgo y usa `Importar a Noticias` cuando sea relevante.

El Radar no evade inicios de sesión, no consulta perfiles privados y no publica automáticamente. Cada hallazgo requiere revisión humana.

## Facebook

El módulo **Facebook** se conecta mediante la API oficial de Meta y requiere:

- El ID de una página que administras.
- Un Page Access Token válido con los permisos aprobados para leer esa página.

Pulso Monitor valida la conexión, guarda el token solamente en `backend/.env` y permite sincronizar hasta 50 publicaciones recientes por operación. Cada publicación puede prepararse con OpenAI o con el analizador local; el resultado se guarda como borrador pendiente. No lee perfiles personales ni grupos privados y no publica automáticamente.

La configuración inicial se realiza desde `Facebook` en el menú. Nunca compartas el token por chat, correo o capturas de pantalla.

## Publicaciones

Para publicar desde Pulso Monitor, el Page Access Token debe incluir estos permisos:

- `pages_show_list`
- `pages_read_engagement`
- `pages_manage_posts`

El módulo **Publicaciones** muestra las noticias listas para aprobación. Puedes publicar inmediatamente o elegir una fecha y hora; la programación queda registrada directamente en Meta, por lo que funciona aunque cierres Pulso Monitor. Antes de enviar contenido debes marcar una confirmación de revisión. Una noticia programada debe cancelarse antes de editarse o eliminarse.

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
npm run dev -- --hostname 127.0.0.1 --port 3010
```

## Direcciones locales

- Panel: http://127.0.0.1:3010
- API: http://127.0.0.1:8000
- Documentación de la API: http://127.0.0.1:8000/docs
- Estado de la API: http://127.0.0.1:8000/health

## Estructura

```text
app/                 Panel Next.js
app/ia/              Asistente de redacción y clasificación
app/radar/           Radar de fuentes y hallazgos
app/facebook/        Conexión autorizada con una página de Facebook
app/publicaciones/   Aprobación, programación y publicación en Facebook
components/          Navegación e inicio de sesión
lib/                 Cliente de la API
types/               Tipos de noticias
backend/main.py      API FastAPI y acceso a SQLite
backend/test_api.py  Pruebas del CRUD
instalar.bat         Instalación automática para Windows
iniciar.bat          Arranque automático para Windows
```

## Alcance de esta versión

La v0.6 administra noticias, ofrece redacción asistida, detecta entradas RSS/Atom, transforma publicaciones autorizadas en borradores y permite aprobarlas, programarlas o publicarlas en la página conectada. El acceso a otras páginas públicas depende de los permisos y la revisión de la aplicación de Meta. Ningún contenido se envía sin confirmación humana.
