# Pulso Monitor v1.2

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
- Catálogo de municipios y zonas de cobertura.
- Conteos de noticias, pendientes, publicadas, urgentes y fuentes por municipio.
- Filtro exacto de Noticias por municipio.
- Incorporación automática de las zonas ya utilizadas en Noticias o Radar.
- Mapa interactivo de incidencias con cartografía de OpenStreetMap.
- Ubicación de noticias mediante un clic o coordenadas manuales.
- Marcadores diferenciados por prioridad y estado editorial.
- Filtros geográficos por municipio, estado y prioridad.
- Edición o retiro de una ubicación sin eliminar la noticia.
- Detección automática de calles, carreteras, colonias, comunidades y lugares mencionados.
- Geocodificación de bajo volumen con caché local y un máximo de una consulta por segundo.
- Confirmación editorial de cada marcador sugerido automáticamente.
- Exclusión automática de posibles domicilios particulares, víctimas y menores.
- Usuarios reales con roles de Administrador, Editor y Reportero.
- Contraseñas protegidas con scrypt, sal única y revocación de sesiones al cambiar permisos o contraseña.
- Panel de configuración con identidad del medio y municipio principal.
- Registro de actividad administrativa y accesos recientes.
- Respaldos verificables de SQLite, descarga local y conservación de las 10 copias más recientes.
- Automatización configurable de Facebook, Radar, geolocalización y respaldos mientras el sistema está encendido.
- Ejecución manual de cada tarea y programación desde un panel central.
- Alertas relevantes para contenido nuevo, respaldos y errores que requieren atención.
- Estadísticas editoriales para periodos de 7, 30 y 90 días.
- Tendencias diarias de noticias creadas y publicadas.
- Análisis por estado, categoría, municipio y fuente.
- Indicadores de publicación, uso de IA y cobertura geográfica.
- Exportación de reportes CSV compatibles con Excel.

## Instalación rápida en Windows

1. Descarga o actualiza el repositorio.
2. Haz doble clic en `instalar.bat` y espera a que termine.
3. Haz doble clic en `iniciar.bat`.
4. Se abrirá `http://127.0.0.1:3010` en el navegador.

Durante una instalación nueva se genera automáticamente una contraseña única. Los datos aparecen en `ACCESO.txt`, un archivo local excluido de Git. En una actualización se conservan los usuarios y contraseñas existentes. Guárdalo en un lugar seguro y no lo compartas.

## Usuarios y permisos

El administrador puede crear cuentas desde **Usuarios** y asignar uno de estos perfiles:

- **Administrador:** usuarios, configuración, conexiones externas, noticias y publicación.
- **Editor:** revisión editorial, eliminación, programación y publicación.
- **Reportero:** creación y preparación de contenido sin acceso a administración ni publicación.

Las contraseñas no se almacenan como texto. Al cambiar una contraseña, desactivar una cuenta o modificar su rol, las sesiones anteriores dejan de ser válidas.

## Configuración y respaldos

El módulo **Configuración** permite editar la identidad del medio, consultar la actividad reciente y crear copias de seguridad. Los respaldos se guardan en `backend\backups`, pueden descargarse desde el panel y se limitan automáticamente a las 10 copias más recientes.

## Automatizaciones

El módulo **Automatizaciones** permite activar y programar cuatro tareas: sincronización de Facebook, escaneo de fuentes Radar, geolocalización supervisada y respaldos de SQLite. Cada tarea puede ejecutarse inmediatamente o repetirse entre cada 15 minutos y una vez por semana.

Las tareas programadas funcionan mientras Pulso Monitor y su ventana de API estén encendidos. El historial muestra nuevos hallazgos, copias creadas y errores relevantes. Por seguridad editorial, la automatización nunca aprueba ni publica noticias en Facebook: toda publicación continúa requiriendo revisión humana.

## Estadísticas y reportes

El módulo **Estadísticas** transforma la actividad editorial en indicadores fáciles de revisar. Permite comparar los últimos 7, 30 o 90 días, consultar la evolución diaria, reconocer los temas, municipios y fuentes con mayor actividad, y medir qué proporción del contenido fue publicado, preparado con IA o ubicado en el mapa.

El botón **Exportar Excel** descarga un archivo CSV con las noticias del periodo seleccionado. El archivo incluye título, resumen, fuente, municipio, categoría, estado, fechas, uso de IA y ubicación, y puede abrirse directamente en Excel sin modificar la base de datos.

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

## Municipios

El módulo **Municipios** concentra la cobertura editorial de Pulso Tequila. Permite agregar, editar, activar o desactivar municipios y comunidades, consultar sus indicadores y abrir directamente las noticias de una zona. Si un municipio ya tiene noticias o fuentes, se conserva como historial y debe desactivarse en lugar de eliminarse.

Los nombres usados previamente en Noticias y Radar se incorporan automáticamente, por lo que la actualización no pierde ni modifica el contenido existente.

## Mapa de incidencias

El módulo **Mapa** intenta ubicar automáticamente las noticias nuevas cuando contienen una referencia geográfica explícita. También incluye el botón `Ubicar automáticamente` para procesar noticias anteriores. Cada marcador automático aparece como **Por confirmar** hasta que el administrador lo revise; siempre es posible editarlo, moverlo o retirarlo sin eliminar la noticia.

La detección envía al geocodificador solamente una referencia breve del lugar junto con municipio, estado y país; nunca envía la noticia completa. Los reportes que puedan revelar domicilios particulares, víctimas o menores se excluyen automáticamente y requieren ubicación manual aproximada.

El mapa utiliza Leaflet, las teselas estándar de OpenStreetMap y Nominatim con atribución visible. Requiere conexión a internet y está destinado a un solo panel local de bajo volumen. Las búsquedas se ejecutan en un único hilo, con un máximo de una solicitud por segundo y caché local; no hay autocompletado, consultas periódicas ni descargas masivas. El servicio puede cambiarse mediante `PULSO_GEOCODER_URL` sin modificar el programa. Consulta las políticas oficiales de [teselas](https://operations.osmfoundation.org/policies/tiles/) y [Nominatim](https://operations.osmfoundation.org/policies/nominatim/).

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
app/municipios/      Cobertura e indicadores por municipio
app/mapa/            Mapa interactivo de incidencias
app/automatizaciones/ Programación de tareas y alertas operativas
app/estadisticas/     Indicadores, tendencias y exportación de reportes
app/usuarios/        Usuarios, roles y contraseñas
app/configuracion/   Identidad, actividad y respaldos
components/          Navegación e inicio de sesión
lib/                 Cliente de la API
types/               Tipos de noticias
backend/main.py      API FastAPI y acceso a SQLite
backend/test_api.py  Pruebas del CRUD
instalar.bat         Instalación automática para Windows
iniciar.bat          Arranque automático para Windows
```

## Alcance de esta versión

La v1.2 administra noticias, equipo editorial, permisos, cobertura municipal, automatizaciones supervisadas, fuentes RSS/Atom y publicaciones autorizadas de Facebook. Incorpora análisis editorial, reportes exportables, auditoría, alertas y respaldos sin perder los datos de versiones anteriores. Ningún contenido se publica ni ninguna ubicación sugerida se confirma sin intervención humana.
