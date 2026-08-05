# ASTRA + ASTRUM en macOS

Esta es la ruta recomendada para incorporar la laptop Mac de un colaborador.
La Mac ejecuta ASTRA, los tres CLI autenticados, el servidor MCP y la validación
ligera. SageMath, Maxima, Cadabra, Lean, GPU y los paquetes propios mantenidos
se usan en ASTRUM por Tailscale y SSH.

No se comparten contraseñas, tokens de los CLI, estado de Tailscale ni claves
SSH privadas. Cada colaborador inicia sesión con sus propias suscripciones y
crea una clave SSH individual cuya parte pública autoriza el administrador.

## Esquema operativo

- **Antigravity** es la interfaz y el agente instructor del colaborador.
- **ASTRA MCP** expone `astra_status`, `astra_execute`, `astra_cycle_submit`,
  `astra_job`, `astra_client_validate` y las demás herramientas.
- **Codex CLI** formula, sintetiza, revisa y analiza.
- **`agy` CLI** propone una mirada independiente y navega la investigación.
- **Claude Code CLI** traduce la conjetura en un validador y lo corrige.
- **ASTRUM** ejecuta la validación científica especializada y pesada.

Aunque el colaborador use la aplicación gráfica de Antigravity como asistente,
también debe instalar y autenticar `agy`: ASTRA lo invoca internamente como uno
de sus tres modelos.

## Instalación resumida

La aplicación actual de Antigravity requiere Apple Silicon y macOS 12 o más
nuevo. Instalar Homebrew, el cliente standalone de Tailscale y luego:

```bash
brew install git python@3.12 node maxima
npm install -g @openai/codex
npm install -g @anthropic-ai/claude-code
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Autenticar con las cuentas propias:

```bash
codex login
claude
agy
```

Clonar desde el repositorio corporativo y ejecutar el instalador:

```bash
mkdir -p ~/Dev
cd ~/Dev
git clone https://github.com/AstrumDrive/ASTRA.git
cd ASTRA
bash install_macos.sh
```

El instalador crea `venv/`, instala las dependencias científicas y MCP, genera
`.env` sin secretos y registra ASTRA como MCP únicamente para ese workspace de
Antigravity.

## Acceso individual a ASTRUM

En la Mac del colaborador:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/astra_astrum_ed25519 -C "astra-colaborador"
cat ~/.ssh/astra_astrum_ed25519.pub
```

Debe enviarse al administrador solamente el contenido de `.pub`. El
administrador autoriza esa clave pública y comunica por un canal privado el
usuario y host Tailscale. La clave privada nunca abandona la Mac.

Crear `~/.ssh/config`:

```sshconfig
Host astrum
    HostName HOST_TAILSCALE
    User USUARIO_ASTRUM
    IdentityFile ~/.ssh/astra_astrum_ed25519
    IdentitiesOnly yes
    ProxyCommand tailscale nc %h %p
```

Probar y configurar `.env`:

```bash
chmod 700 ~/.ssh
chmod 600 ~/.ssh/astra_astrum_ed25519 ~/.ssh/config
ssh astrum 'hostname; ~/astra-worker/astra_engine.sh list'
```

```dotenv
ASTRA_REMOTE_HOST=astrum
ASTRA_REMOTE_SSH_OPTIONS=
```

La lista de `astra_engine.sh` es la fuente correcta para los motores del
clúster; `which sage` no los encuentra porque viven en entornos administrados
separados.

## Verificación antes de gastar cuota

```bash
venv/bin/python scripts/astra_doctor.py --remote
remote/check_remote_oracle.sh
venv/bin/python -m pytest -q
```

Luego abrir el directorio ASTRA en Antigravity, ir a **Settings →
Customizations → MCP Servers**, refrescar y comprobar que aparece `astra`.
Pegar el protocolo de
`docs/onboarding/ANTIGRAVITY_INSTRUCTOR_PROMPT_EN.md` en una tarea nueva.

El primer ensayo deliberativo debe ser una afirmación estrecha y falsable con
`astra_cycle_submit`; el agente consulta el `job_id` con `astra_job`. No conviene
usar un artículo entero como primera prueba.

## Lectura correcta del resultado

El instructor debe separar siempre:

- `job.status`: finalización operativa.
- `oracle_verdict`: resultado del cálculo ejecutable.
- `atomic_status`: estado de la conjetura acotada.
- `goal_coverage` y `scientific_status`: cobertura real del objetivo amplio.

Un trabajo terminado y un `PASS` numérico no convierten automáticamente todo el
objetivo o un artículo en validado.

La guía inglesa contiene los pasos completos, actualizaciones, uso opcional de
paquetes locales y la interfaz web: `ASTRA_MACOS_INSTALL_EN.md`.
