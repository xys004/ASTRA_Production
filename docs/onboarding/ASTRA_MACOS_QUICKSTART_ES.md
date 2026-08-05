# Inicio rápido de ASTRA en una Mac

Esta hoja resume el alta. La explicación completa está en
`ASTRA_MACOS_INSTALL_ES.md` y `ASTRA_MACOS_INSTALL_EN.md`.

## 1. Preparar la Mac

ASTRA funciona como estación completa en una Mac Apple Silicon. Instala
Homebrew y el cliente standalone de Tailscale. Después:

```bash
brew install git python@3.12 node maxima
npm install -g @openai/codex
npm install -g @anthropic-ai/claude-code
curl -fsSL https://antigravity.google/cli/install.sh | bash
```

Si `agy` no aparece en el terminal:

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

Inicia sesión con tus propias cuentas:

```bash
codex login
claude
agy
```

## 2. Instalar ASTRA

```bash
mkdir -p ~/Dev
cd ~/Dev
git clone https://github.com/AstrumDrive/ASTRA.git
cd ASTRA
bash install_macos.sh
```

El instalador crea el entorno Python, instala los validadores y registra el MCP
de ASTRA únicamente para este workspace de Antigravity.

## 3. Conectar ASTRUM

Usa siempre tu propia identidad SSH. Si todavía no tienes una clave dedicada:

```bash
ssh-keygen -t ed25519 -f ~/.ssh/astra_astrum_ed25519 -C "astra-colaborador"
cat ~/.ssh/astra_astrum_ed25519.pub
```

Comparte solamente el contenido de `.pub` con el administrador. Nunca envíes la
clave privada. Si ya tienes un alias `astrum` funcional en `~/.ssh/config`,
puedes reutilizarlo. En `.env` configura:

```dotenv
ASTRA_REMOTE_HOST=astrum
ASTRA_REMOTE_SSH_OPTIONS=
```

## 4. Verificar sin gastar cuota de modelos

```bash
venv/bin/python scripts/astra_doctor.py --remote
remote/check_remote_oracle.sh
venv/bin/python -m pytest -q
```

## 5. Usar Antigravity como instructor

Abre la carpeta ASTRA en Antigravity. Ve a **Settings → Customizations → MCP
Servers**, pulsa **Refresh** y confirma que aparece `astra`. Pega en una tarea
nueva el contenido de `ANTIGRAVITY_INSTRUCTOR_PROMPT_EN.md`.

Pídele primero:

1. ejecutar `astra_capacity`;
2. ejecutar `astra_status`;
3. ejecutar `astra_engines`;
4. verificar un cálculo pequeño con `astra_execute`.

Para una investigación real usa `astra_cycle_submit` y consulta el `job_id` con
`astra_job`. Deben distinguirse siempre la finalización del trabajo, el veredicto
del oráculo, el resultado de la conjetura acotada y la cobertura del objetivo
general.

## Seguridad

No subas ni envíes `.env`, claves privadas, tokens de los CLI o configuración
personal de Tailscale. Los tres CLI conservan sus credenciales en sus propios
almacenes; ASTRA no necesita copiarlas a `.env`.
