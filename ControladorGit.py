import os
import git
from git.exc import InvalidGitRepositoryError
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, Grid
from textual.widgets import Header, Footer, Input, Button, Label, RichLog, OptionList, TabbedContent, TabPane
from textual.screen import ModalScreen
from rich.text import Text

# --- PANTALLA MODAL DE LOGIN ---
class GitHubLoginScreen(ModalScreen):
    """Pantalla emergente para configurar GitHub."""
    def compose(self) -> ComposeResult:
        with Vertical(id="login-dialog"):
            yield Label("Configuración de GitHub", id="login-title")
            yield Label("Introduce tu Personal Access Token (PAT):")
            yield Input(placeholder="ghp_xxxxxxxxxxxx", password=True, id="token-input")
            with Horizontal():
                yield Button("Guardar", variant="success", id="save-btn")
                yield Button("Cancelar", variant="error", id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            token = self.query_one("#token-input", Input).value
            self.dismiss(token) # Devuelve el token a la app principal
        else:
            self.dismiss(None)

# --- APLICACIÓN PRINCIPAL ---
class GitTUIUltimate(App):
    CSS = """
    #main-container { height: 100%; }
    #left-sidebar { width: 35%; height: 100%; border-right: solid $primary; padding: 1; }
    #right-content { width: 65%; height: 100%; padding: 1; }
    
    .panel { border: round $secondary; height: 1fr; margin-bottom: 1; }
    #staging-area { height: 30%; layout: horizontal; }
    .stage-list { width: 50%; height: 100%; border: round $panel; margin: 0 1; }
    
    #action-bar { height: auto; margin-bottom: 1; }
    .action-btn { margin-right: 1; }
    
    #commit-panel { height: auto; layout: horizontal; margin: 1 0; }
    
    /* Estilo del Modal */
    #login-dialog {
        padding: 2;
        background: $surface;
        border: thick $primary;
        width: 50;
        height: auto;
        align: center middle;
    }
    #login-title { text-align: center; text-style: bold; margin-bottom: 1; }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("r", "refresh", "Refrescar")
    ]

    def __init__(self):
        super().__init__()
        self.github_token = None
        try:
            self.repo = git.Repo(os.getcwd())
            self.is_repo = True
        except:
            self.is_repo = False

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):
            # IZQUIERDA
            with Vertical(id="left-sidebar"):
                with Horizontal(id="action-bar"):
                    yield Button("Login GitHub", id="btn-login", variant="primary", classes="action-btn")
                    yield Button("Pull", id="btn-pull", variant="warning", classes="action-btn")
                    yield Button("Push", id="btn-push", variant="success", classes="action-btn")

                with TabbedContent():
                    with TabPane("Locales"):
                        yield OptionList(id="list-local")
                    with TabPane("Remotas (Sin Bots)"):
                        yield OptionList(id="list-remote")

            # DERECHA
            with Vertical(id="right-content"):
                with Horizontal(id="staging-area"):
                    with Vertical(classes="stage-list"):
                        yield Label("Changes")
                        yield OptionList(id="list-unstaged")
                    with Vertical(classes="stage-list"):
                        yield Label("Staged")
                        yield OptionList(id="list-staged")

                with Horizontal(id="commit-panel"):
                    yield Input(placeholder="Mensaje...", id="commit-input")
                    yield Button("Commit", id="btn-commit")

                yield Label("Git Graph")
                yield RichLog(id="graph-log", highlight=True)
        yield Footer()

    def on_mount(self):
        if self.is_repo:
            self.refresh_ui()
            self.set_interval(5.0, self.refresh_ui)

    def refresh_ui(self):
        self.update_branches()
        self.update_staging()
        self.update_graph()

    def update_branches(self):
        # Filtrar Bots
        bot_keywords = ['bot', 'dependabot', 'renovate', 'github-actions']
        
        # Locales
        l = self.query_one("#list-local", OptionList)
        l.clear_options()
        for b in self.repo.heads:
            l.add_option(f"🏷️ {b.name}")

        # Remotas filtradas
        r = self.query_one("#list-remote", OptionList)
        r.clear_options()
        try:
            for ref in self.repo.remotes.origin.refs:
                if not any(kw in ref.name.lower() for kw in bot_keywords):
                    r.add_option(f"☁️ {ref.name}")
        except:
            r.add_option("No se detectó remoto 'origin'")

    def update_staging(self):
        un = self.query_one("#list-unstaged", OptionList)
        st = self.query_one("#list-staged", OptionList)
        un.clear_options(); st.clear_options()

        for f in [i.a_path for i in self.repo.index.diff(None)] + self.repo.untracked_files:
            un.add_option(f"+ {f}")
        try:
            for f in [i.a_path for i in self.repo.index.diff('HEAD')]:
                st.add_option(f"- {f}")
        except: pass

    def update_graph(self):
        log = self.query_one("#graph-log", RichLog)
        log.clear()
        graph = self.repo.git.log('--graph', '--color=always', '--format=%C(auto)%h %s', '-n', '15')
        log.write(Text.from_ansi(graph))

    # --- EVENTOS ---
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-login":
            def handle_token(token):
                if token:
                    self.github_token = token
                    self.notify("Token guardado correctamente")
            
            self.push_screen(GitHubLoginScreen(), handle_token)

        elif event.button.id == "btn-pull":
            try:
                self.repo.remotes.origin.pull()
                self.notify("Pull completado")
                self.refresh_ui()
            except Exception as e:
                self.notify(f"Error Pull: {e}", severity="error")

        elif event.button.id == "btn-push":
            try:
                self.repo.remotes.origin.push()
                self.notify("Push completado")
            except Exception as e:
                self.notify(f"Error Push: {e}", severity="error")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        path = str(event.option.prompt)[2:]
        if event.control.id == "list-unstaged":
            self.repo.git.add(path)
        elif event.control.id == "list-staged":
            self.repo.git.restore('--staged', path)
        self.refresh_ui()

if __name__ == "__main__":
    GitTUIUltimate().run()