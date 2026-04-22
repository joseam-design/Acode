import os
import re
import git
from git.exc import InvalidGitRepositoryError
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Input, Button, Label,
    RichLog, OptionList, TabbedContent, TabPane
)
from textual.screen import ModalScreen
from rich.text import Text


# ─────────────────────────────────────────────
#  PANTALLA MODAL DE LOGIN  (mejorada)
# ─────────────────────────────────────────────
class GitHubLoginScreen(ModalScreen):
    """Modal para configurar credenciales de GitHub."""

    CSS = """
    GitHubLoginScreen {
        align: center middle;
    }
    #login-dialog {
        padding: 2 3;
        background: $surface;
        border: double $primary;
        width: 60;
        height: auto;
    }
    #login-title {
        text-align: center;
        text-style: bold;
        color: $primary;
        margin-bottom: 1;
    }
    #login-subtitle {
        text-align: center;
        color: $text-muted;
        margin-bottom: 1;
    }
    .field-label {
        margin-top: 1;
        color: $text;
    }
    #login-buttons {
        margin-top: 2;
        height: auto;
        align: center middle;
    }
    #save-btn   { width: 16; margin-right: 2; }
    #cancel-btn { width: 16; }
    """

    def compose(self) -> ComposeResult:
        with Vertical(id="login-dialog"):
            yield Label("🔐  GitHub Login", id="login-title")
            yield Label("Necesario para pull/push con repos privados", id="login-subtitle")

            yield Label("Usuario de GitHub:", classes="field-label")
            yield Input(placeholder="tu-usuario", id="user-input")

            yield Label("Personal Access Token (PAT):", classes="field-label")
            yield Input(
                placeholder="ghp_xxxxxxxxxxxxxxxxxxxx",
                password=True,
                id="token-input",
            )

            yield Label(
                "ℹ️  Genera tu PAT en Settings → Developer → Tokens",
                classes="field-label",
            )

            with Horizontal(id="login-buttons"):
                yield Button("💾 Guardar", variant="success", id="save-btn")
                yield Button("✖ Cancelar", variant="error", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            token = self.query_one("#token-input", Input).value.strip()
            user = self.query_one("#user-input", Input).value.strip()
            if token and user:
                self.dismiss({"token": token, "user": user})
            else:
                self.notify("⚠️  Rellena usuario y token", severity="warning")
        else:
            self.dismiss(None)


# ─────────────────────────────────────────────
#  APLICACIÓN PRINCIPAL
# ─────────────────────────────────────────────
class GitTUIUltimate(App):

    CSS = """
    /* ── Layout principal ── */
    #main-container   { height: 1fr; }
    #left-sidebar     { width: 35%; height: 100%; border-right: solid $primary; padding: 1; }
    #right-content    { width: 65%; height: 100%; padding: 1; }

    /* ── Barra de acciones (sin solapamiento) ── */
    #action-bar       { height: 3; margin-bottom: 1; }
    #btn-login        { width: 18; margin-right: 1; }
    #btn-pull         { width: 10; margin-right: 1; }
    #btn-push         { width: 10; }

    /* ── Listas de ramas ── */
    #list-local       { height: 1fr; }
    #list-remote      { height: 1fr; }

    /* ── Staging area ── */
    #staging-area     { height: 40%; margin-bottom: 1; }
    .stage-col        { width: 1fr; height: 100%; border: round $secondary; padding: 1; margin: 0 1; }
    .stage-label      { text-style: bold; margin-bottom: 1; }

    /* ── Panel de commit (siempre visible, altura fija) ── */
    #commit-panel     { height: 5; margin-bottom: 1; align: left middle; }
    #commit-input     { width: 1fr; margin-right: 1; }
    #btn-commit       { width: 14; }

    /* ── Git graph ── */
    #graph-label      { text-style: bold; margin-bottom: 1; }
    #graph-log        { height: 1fr; border: round $secondary; }
    """

    BINDINGS = [
        Binding("q", "quit",    "Salir"),
        Binding("r", "refresh", "Refrescar"),
    ]

    # Patrones de ramas que NO son del usuario
    BOT_PATTERNS = [
        r'dependabot', r'renovate', r'github-actions', r'\bbot\b',
        r'snyk-', r'auto-update', r'mergify',
    ]
    # Ramas internas de Git/GitHub que no son ramas de trabajo
    INTERNAL_PATTERNS = [
        r'/HEAD$', r'gh-readonly-queue', r'merge-queue',
        r'refs/pull/', r'__',
    ]

    def __init__(self):
        super().__init__()
        self.github_token: str | None = None
        self.github_user: str | None = None
        try:
            self.repo = git.Repo(os.getcwd(), search_parent_directories=True)
            self.is_repo = True
        except Exception:
            self.is_repo = False

    # ── Composición ──────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):

            # IZQUIERDA
            with Vertical(id="left-sidebar"):
                with Horizontal(id="action-bar"):
                    yield Button("🔑 GitHub Login", id="btn-login", variant="primary")
                    yield Button("⬇ Pull",          id="btn-pull",  variant="warning")
                    yield Button("⬆ Push",          id="btn-push",  variant="success")

                with TabbedContent():
                    with TabPane("Locales"):
                        yield OptionList(id="list-local")
                    with TabPane("Remotas"):
                        yield OptionList(id="list-remote")

            # DERECHA
            with Vertical(id="right-content"):

                # Staging
                with Horizontal(id="staging-area"):
                    with Vertical(classes="stage-col"):
                        yield Label("📂 Sin stagear  (clic → stagear)", classes="stage-label")
                        yield OptionList(id="list-unstaged")
                    with Vertical(classes="stage-col"):
                        yield Label("✅ Staged  (clic → destagear)", classes="stage-label")
                        yield OptionList(id="list-staged")

                # Commit
                with Horizontal(id="commit-panel"):
                    yield Input(placeholder="Mensaje del commit…", id="commit-input")
                    yield Button("💬 Commit", id="btn-commit", variant="primary")

                # Graph
                yield Label("📈 Git Graph", id="graph-label")
                yield RichLog(id="graph-log", highlight=True)

        yield Footer()

    # ── Ciclo de vida ────────────────────────────────────────────────
    def on_mount(self) -> None:
        if self.is_repo:
            self.refresh_ui()
            self.set_interval(5.0, self.refresh_ui)
        else:
            self.notify("⚠️  No se detectó repositorio Git en el directorio actual", severity="warning")

    def action_refresh(self) -> None:
        self.refresh_ui()

    def refresh_ui(self) -> None:
        self.update_branches()
        self.update_staging()
        self.update_graph()

    # ── Actualización de ramas ───────────────────────────────────────
    def _is_bot_branch(self, name: str) -> bool:
        lower = name.lower()
        return any(re.search(p, lower) for p in self.BOT_PATTERNS)

    def _is_internal_branch(self, name: str) -> bool:
        return any(re.search(p, name) for p in self.INTERNAL_PATTERNS)

    def update_branches(self) -> None:
        # Locales
        local_list = self.query_one("#list-local", OptionList)
        local_list.clear_options()
        current = self.repo.active_branch.name if self.is_repo else ""
        for b in self.repo.heads:
            icon = "▶ " if b.name == current else "  "
            local_list.add_option(f"{icon}🏷  {b.name}")

        # Remotas: solo ramas reales del usuario
        remote_list = self.query_one("#list-remote", OptionList)
        remote_list.clear_options()
        try:
            filtered = []
            for ref in self.repo.remotes.origin.refs:
                name = ref.name
                if self._is_internal_branch(name):
                    continue
                if self._is_bot_branch(name):
                    continue
                filtered.append(name)

            if filtered:
                for name in filtered:
                    remote_list.add_option(f"☁️  {name}")
            else:
                remote_list.add_option("(no hay ramas remotas visibles)")
        except Exception as e:
            remote_list.add_option(f"⚠️  Sin remoto 'origin': {e}")

    # ── Staging ──────────────────────────────────────────────────────
    def update_staging(self) -> None:
        un = self.query_one("#list-unstaged", OptionList)
        st = self.query_one("#list-staged",   OptionList)
        un.clear_options()
        st.clear_options()

        # Modificados + no rastreados
        unstaged = [i.a_path for i in self.repo.index.diff(None)] + self.repo.untracked_files
        for f in unstaged:
            un.add_option(f"📄 {f}")

        # Staged
        try:
            for i in self.repo.index.diff("HEAD"):
                st.add_option(f"✅ {i.a_path}")
        except Exception:
            pass

    # ── Git graph ────────────────────────────────────────────────────
    def update_graph(self) -> None:
        log_widget = self.query_one("#graph-log", RichLog)
        log_widget.clear()
        try:
            graph = self.repo.git.log(
                "--graph", "--color=always",
                "--format=%C(auto)%h %C(bold blue)%an%C(reset) %s %C(green)(%cr)%C(reset)",
                "-n", "20",
            )
            log_widget.write(Text.from_ansi(graph))
        except Exception as e:
            log_widget.write(f"[red]Error al cargar el grafo: {e}[/red]")

    # ── Autenticar URL remota ─────────────────────────────────────────
    def _authenticated_url(self) -> str | None:
        """Devuelve la URL del remoto con credenciales incrustadas si hay token."""
        if not (self.github_token and self.github_user):
            return None
        try:
            url = self.repo.remotes.origin.url
            # https://github.com/… → https://user:token@github.com/…
            if url.startswith("https://"):
                return url.replace(
                    "https://",
                    f"https://{self.github_user}:{self.github_token}@",
                    1,
                )
        except Exception:
            pass
        return None

    # ── Eventos de botones ───────────────────────────────────────────
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        # ── LOGIN ────────────────────────────────────────────────────
        if btn_id == "btn-login":
            def handle_credentials(result):
                if result:
                    self.github_token = result["token"]
                    self.github_user  = result["user"]
                    self.notify(f"✅  Sesión guardada para '{self.github_user}'")

            self.push_screen(GitHubLoginScreen(), handle_credentials)

        # ── PULL ─────────────────────────────────────────────────────
        elif btn_id == "btn-pull":
            if not self.is_repo:
                self.notify("⚠️  No hay repositorio", severity="warning")
                return
            try:
                auth_url = self._authenticated_url()
                if auth_url:
                    self.repo.git.pull(auth_url)
                else:
                    self.repo.git.pull()
                self.notify("⬇  Pull completado")
                self.refresh_ui()
            except Exception as e:
                self.notify(f"❌  Pull falló: {e}", severity="error")

        # ── PUSH ─────────────────────────────────────────────────────
        elif btn_id == "btn-push":
            if not self.is_repo:
                self.notify("⚠️  No hay repositorio", severity="warning")
                return
            try:
                auth_url = self._authenticated_url()
                if auth_url:
                    branch = self.repo.active_branch.name
                    self.repo.git.push(auth_url, branch)
                else:
                    self.repo.git.push()
                self.notify("⬆  Push completado")
            except Exception as e:
                self.notify(f"❌  Push falló: {e}", severity="error")

        # ── COMMIT ───────────────────────────────────────────────────
        elif btn_id == "btn-commit":
            if not self.is_repo:
                self.notify("⚠️  No hay repositorio", severity="warning")
                return
            msg_input = self.query_one("#commit-input", Input)
            msg = msg_input.value.strip()
            if not msg:
                self.notify("⚠️  Escribe un mensaje de commit", severity="warning")
                return
            try:
                self.repo.index.commit(msg)
                msg_input.value = ""
                self.notify(f"💬  Commit: '{msg}'")
                self.refresh_ui()
            except Exception as e:
                self.notify(f"❌  Commit falló: {e}", severity="error")

    # ── Clic en listas (stagear / destagear) ─────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        # El prefijo tiene 3 chars (emoji + espacio) → recortamos
        raw = str(event.option.prompt)
        path = raw.split(" ", 1)[-1].strip()

        if event.control.id == "list-unstaged":
            try:
                self.repo.git.add(path)
                self.notify(f"✅  Stageado: {path}")
            except Exception as e:
                self.notify(f"❌  Error al stagear: {e}", severity="error")

        elif event.control.id == "list-staged":
            try:
                self.repo.git.restore("--staged", path)
                self.notify(f"↩️  Destageado: {path}")
            except Exception as e:
                self.notify(f"❌  Error al destagear: {e}", severity="error")

        self.refresh_ui()


# ─────────────────────────────────────────────
if __name__ == "__main__":
    GitTUIUltimate().run()