import os
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, Container
from textual.widgets import Header, Footer, Input, Button, Label, RichLog, OptionList, TabbedContent, TabPane
from textual.binding import Binding
from rich.text import Text
import git
from git.exc import InvalidGitRepositoryError

class GitTUIProApp(App):
    """Cliente TUI Avanzado de Git con Textual."""
    
    CSS = """
    Screen { background: $surface; }
    #main-container { height: 100%; }
    #left-sidebar { width: 35%; height: 100%; border-right: solid $primary; padding: 1; }
    #right-content { width: 65%; height: 100%; padding: 1; }
    
    .panel-title { text-style: bold; color: $accent; margin-bottom: 1; }
    .panel { border: round $secondary; height: 1fr; }
    
    /* Área de Staging */
    #staging-area { height: 35%; layout: horizontal; }
    .stage-list { width: 50%; height: 100%; border: round $panel; margin: 0 1; }
    
    /* Controles Superiores */
    #action-bar { layout: horizontal; height: auto; margin-bottom: 1; }
    .action-btn { margin-right: 1; min-width: 15; }
    
    /* Commit area */
    #commit-panel { height: auto; layout: horizontal; margin-top: 1; margin-bottom: 1;}
    #commit-input { width: 75%; }
    #btn-commit { width: 25%; margin-left: 1; }
    
    /* Graph */
    #graph-log { height: 1fr; border: round $secondary; }
    """

    BINDINGS = [
        Binding("q", "quit", "Salir"),
        Binding("r", "refresh_all", "Forzar Refresco")
    ]

    def __init__(self):
        super().__init__()
        self.last_status = ""
        try:
            self.repo = git.Repo(os.getcwd())
            self.is_repo = True
        except InvalidGitRepositoryError:
            self.is_repo = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        if not self.is_repo:
            yield Label("[red]¡No estás en un repositorio Git válido![/red]")
            return

        with Horizontal(id="main-container"):
            # PANEL IZQUIERDO (Ramas y Acciones)
            with Vertical(id="left-sidebar"):
                # Barra de acciones extra
                with Horizontal(id="action-bar"):
                    yield Button("Remotes", id="btn-remotes", classes="action-btn")
                    yield Button("Stash", id="btn-stash", classes="action-btn", variant="warning")
                    yield Button("Rebase", id="btn-rebase", classes="action-btn", variant="error")

                with TabbedContent(initial="tab-local"):
                    with TabPane("Locales", id="tab-local"):
                        yield OptionList(id="list-branches-local", classes="panel")
                    with TabPane("Remotas", id="tab-remote"):
                        yield OptionList(id="list-branches-remote", classes="panel")

            # PANEL DERECHO (Staging, Commits y Grafo)
            with Vertical(id="right-content"):
                yield Label("Área de Staging (Enter para mover archivos)", classes="panel-title")
                
                with Horizontal(id="staging-area"):
                    with Vertical(classes="stage-list"):
                        yield Label("📝 Unstaged (Changes)")
                        yield OptionList(id="list-unstaged")
                    
                    with Vertical(classes="stage-list"):
                        yield Label("✅ Staged (To Commit)")
                        yield OptionList(id="list-staged")

                with Horizontal(id="commit-panel"):
                    yield Input(placeholder="Escribe el mensaje del commit...", id="commit-input")
                    yield Button("Hacer Commit", id="btn-commit", variant="success")

                yield Label("Git Graph (Historial Limpio)", classes="panel-title")
                yield RichLog(id="graph-log", wrap=False)

        yield Footer()

    def on_mount(self) -> None:
        if self.is_repo:
            self.refresh_all()
            # AUTO-REFRESCO: Comprueba cambios cada 3 segundos
            self.set_interval(3.0, self.auto_check_status)

    # --- LÓGICA DE ACTUALIZACIÓN ---

    def auto_check_status(self):
        """Detecta cambios automáticamente sin parpadear la UI si no hay novedades."""
        if not self.is_repo: return
        current_status = self.repo.git.status("-s")
        if current_status != self.last_status:
            self.last_status = current_status
            self.update_staging()
            self.update_graph()

    def action_refresh_all(self):
        self.refresh_all()

    def refresh_all(self):
        self.update_branches()
        self.update_staging()
        self.update_graph()

    def update_branches(self):
        # Locales
        lst_local = self.query_one("#list-branches-local", OptionList)
        lst_local.clear_options()
        for branch in self.repo.heads:
            marker = "🟢 " if branch == self.repo.active_branch else "  "
            lst_local.add_option(f"{marker}{branch.name}")

        # Remotas
        lst_remote = self.query_one("#list-branches-remote", OptionList)
        lst_remote.clear_options()
        for remote in self.repo.remotes:
            for ref in remote.refs:
                lst_remote.add_option(f"☁️ {ref.name}")

    def update_staging(self):
        """Actualiza las listas de archivos unstaged y staged."""
        un_list = self.query_one("#list-unstaged", OptionList)
        st_list = self.query_one("#list-staged", OptionList)
        
        un_list.clear_options()
        st_list.clear_options()

        # Archivos modificados/eliminados (unstaged) y untracked
        unstaged = [item.a_path for item in self.repo.index.diff(None)]
        untracked = self.repo.untracked_files
        
        for file in set(unstaged + untracked):
            un_list.add_option(f"+ {file}") # Símbolo '+' para añadir

        # Archivos listos para commit (staged)
        # diff('HEAD') falla si no hay commits iniciales, lo manejamos:
        try:
            staged = [item.a_path for item in self.repo.index.diff('HEAD')]
            for file in staged:
                st_list.add_option(f"- {file}") # Símbolo '-' para quitar
        except git.exc.BadName:
            pass # Repositorio totalmente vacío

    def update_graph(self):
        """Genera un grafo a color y limpio."""
        log_widget = self.query_one("#graph-log", RichLog)
        log_widget.clear()
        try:
            # Comando mágico de git log para grafos a color y limpios
            graph_cmd = self.repo.git.log(
                '--graph', 
                '--color=always', # Forzamos códigos ANSI
                '--format=%C(auto)%h%d %s %C(black)%C(bold)%cr', 
                '--all', 
                '-n', '30'
            )
            # Text.from_ansi convierte los colores de Git para que Textual los renderice
            log_widget.write(Text.from_ansi(graph_cmd))
        except Exception as e:
            log_widget.write(f"No hay historial suficiente: {e}")

    # --- INTERACCIONES ---

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Maneja el Enter en las listas para hacer stage/unstage archivo por archivo."""
        file_path = str(event.option.prompt)[2:] # Quitamos el "+ " o "- " del inicio
        
        if event.control.id == "list-unstaged":
            # Hacer Stage
            self.repo.git.add(file_path)
        elif event.control.id == "list-staged":
            # Hacer Unstage (Restore)
            self.repo.git.restore('--staged', file_path)
            
        self.update_staging() # Refrescamos UI inmediatamente

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-commit":
            input_widget = self.query_one("#commit-input", Input)
            if input_widget.value:
                try:
                    self.repo.index.commit(input_widget.value)
                    input_widget.value = ""
                    self.refresh_all()
                except Exception as e:
                    self.app.notify(f"Error al hacer commit: {e}", severity="error")
        
        elif event.button.id in ["btn-remotes", "btn-stash", "btn-rebase"]:
            # Aquí iría la llamada a pantallas modales (ModalScreen)
            self.notify("Función en desarrollo. Requiere una pantalla modal interactiva.", title="Aviso")

if __name__ == "__main__":
    app = GitTUIProApp()
    app.run()