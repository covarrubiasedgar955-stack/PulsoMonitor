# Pulso Monitor v0.2

Centro local de administración y redacción asistida de noticias para **Pulso Tequila**. Incluye un dashboard, gestión editorial completa y un Asistente IA que transforma reportes o publicaciones en propuestas listas para revisar.

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

## Instalación rápida en Windows

1. Descarga o actualiza el repositorio.
2. Haz doble clic en `instalar.bat` y espera a que termine.
3. Haz doble clic en `iniciar.bat`.
4. Se abrirá `http://127.0.0.1:3010` en el navegador.

Acceso inicial:

```text
Usuario: admin
Contraseña: admin123
```

> La contraseña inicial está pensada para uso local. Antes de publicar el sistema en internet, configura credenciales y una clave secreta propias mediante las variables incluidas en `backend/.env.example`.

## Asistente IA

El módulo **Asistente IA** funciona inmediatamente en modo local. Para activar la redacción avanzada:

1. Entra a `Asistente IA` desde el menú.
2. Pulsa `Conectar OpenAI`.
3. Crea una clave en https://platform.openai.com/api-keys.
4. Pega la clave en el formulario local y pulsa `Guardar conexión`.

La clave se valida y se guarda solamente en `backend/.env` dentro de la computadora. Este archivo está excluido de Git.

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
components/          Navegación e inicio de sesión
lib/                 Cliente de la API
types/               Tipos de noticias
backend/main.py      API FastAPI y acceso a SQLite
backend/test_api.py  Pruebas del CRUD
instalar.bat         Instalación automática para Windows
iniciar.bat          Arranque automático para Windows
```

## Alcance de esta versión

La v0.2 administra noticias y ofrece redacción asistida con revisión humana obligatoria. El monitoreo de fuentes externas autorizadas se incorporará en la siguiente fase.
