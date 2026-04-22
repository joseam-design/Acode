import os
import re
import git
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import (
    Header, Footer, Input, Button, Label,
    RichLog, OptionList, TabbedContent, TabPane, Select
)
from textual.screen import ModalScreen
from rich.text import Text


# ══════════════════════════════════════════════════════════
#  MODAL: LOGIN GITHUB
# ══════════════════════════════════════════════════════════
class GitHubLoginScreen(ModalScreen):
    CSS = """
    GitHubLoginScreen { align: center middle; }
    #login-dialog {
        padding: 2 3; background: $surface; border: double $primary;
        width: 60; height: auto;
    }
    #login-title  { text-align: center; text-style: bold; color: $primary; margin-bottom: 1; }
    #login-sub    { text-align: center; color: $text-muted; margin-bottom: 1; }
    .fl           { margin-top: 1; color: $text; }
    #login-btns   { margin-top: 2; height: auto; align: center middle; }
    #save-btn     { width: 14; margin-right: 2; }
    #cancel-btn   { width: 14; }
    """
    def compose(self) -> ComposeResult:
        with Vertical(id="login-dialog"):
            yield Label("🔐  GitHub Login", id="login-title")
            yield Label("Necesario para pull/push con repos privados", id="login-sub")
            yield Label("Usuario de GitHub:", classes="fl")
            yield Input(placeholder="tu-usuario", id="user-input")
            yield Label("Personal Access Token (PAT):", classes="fl")
            yield Input(placeholder="ghp_xxxxxxxxxxxxxxxxxxxx", password=True, id="token-input")
            yield Label("ℹ️  Settings → Developer settings → Personal access tokens", classes="fl")
            with Horizontal(id="login-btns"):
                yield Button("💾 Guardar",  variant="success", id="save-btn")
                yield Button("✖ Cancelar", variant="error",   id="cancel-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save-btn":
            token = self.query_one("#token-input", Input).value.strip()
            user  = self.query_one("#user-input",  Input).value.strip()
            if token and user:
                self.dismiss({"token": token, "user": user})
            else:
                self.notify("⚠️  Rellena usuario y token", severity="warning")
        else:
            self.dismiss(None)


# ══════════════════════════════════════════════════════════
#  MODAL: ACCIÓN DE BRANCH (checkout / rebase)
# ══════════════════════════════════════════════════════════
class BranchActionScreen(ModalScreen):
    CSS = """
    BranchActionScreen { align: center middle; }
    #ba-dialog {
        padding: 2 3; background: $surface; border: round $accent;
        width: 50; height: auto;
    }
    #ba-title { text-align: center; text-style: bold; color: $accent; margin-bottom: 1; }
    .ba-btn   { width: 100%; margin-bottom: 1; }
    """
    def __init__(self, branch_name: str):
        super().__init__()
        self.branch_name = branch_name

    def compose(self) -> ComposeResult:
        with Vertical(id="ba-dialog"):
            yield Label(f"🏷  {self.branch_name}", id="ba-title")
            yield Button("🔀 Checkout  (cambiar a esta rama)", id="ba-checkout", variant="primary", classes="ba-btn")
            yield Button("🔁 Rebase sobre esta rama",          id="ba-rebase",   variant="warning", classes="ba-btn")
            yield Button("✖ Cancelar",                         id="ba-cancel",   variant="default", classes="ba-btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if   event.button.id == "ba-checkout": self.dismiss("checkout")
        elif event.button.id == "ba-rebase":   self.dismiss("rebase")
        else:                                  self.dismiss(None)


# ══════════════════════════════════════════════════════════
#  MODAL: PANEL "MÁS OPCIONES"
# ══════════════════════════════════════════════════════════
class MoreOptionsScreen(ModalScreen):
    CSS = """
    MoreOptionsScreen { align: right middle; }
    #more-panel {
        padding: 1 2; background: $surface; border-left: double $primary;
        width: 45; height: 100%;
    }
    #more-title   { text-align: center; text-style: bold; color: $primary; margin-bottom: 1; }
    .section-hdr  { text-style: bold; color: $accent; margin-top: 1; margin-bottom: 1; }
    .more-btn     { width: 100%; margin-bottom: 1; }
    .more-input   { width: 100%; margin-bottom: 1; }
    #close-btn    { width: 100%; margin-top: 1; }
    """

    def __init__(self, remotes: list):
        super().__init__()
        self._remotes = remotes

    def compose(self) -> ComposeResult:
        with Vertical(id="more-panel"):
            yield Label("⚙  Más Opciones", id="more-title")

            yield Label("── Sincronización ──────────────", classes="section-hdr")
            yield Button("📡 Fetch (todos los remotos)", id="mo-fetch",  variant="primary", classes="more-btn")
            yield Button("🔄 Sync  (pull + push)",       id="mo-sync",   variant="success", classes="more-btn")

            yield Label("── Stash ───────────────────────", classes="section-hdr")
            yield Button("📦 Guardar Stash",             id="mo-stash",  variant="warning", classes="more-btn")
            yield Button("📤 Aplicar último Stash",      id="mo-pop",    variant="warning", classes="more-btn")
            yield Button("🗑  Borrar último Stash",       id="mo-sdrop",  variant="error",   classes="more-btn")

            yield Label("── Clonar repositorio ──────────", classes="section-hdr")
            yield Input(placeholder="https://github.com/…/repo.git",        id="clone-url", classes="more-input")
            yield Input(placeholder="Directorio destino (vacío = actual)",   id="clone-dir", classes="more-input")
            yield Button("🧬 Clonar",                    id="mo-clone",  variant="primary", classes="more-btn")

            yield Label("── Gestión de Remotos ──────────", classes="section-hdr")
            yield Input(placeholder="Nombre  (ej: upstream)",  id="remote-name", classes="more-input")
            yield Input(placeholder="URL del remoto",          id="remote-url",  classes="more-input")
            yield Button("➕ Add Remote",                id="mo-radd",   variant="success", classes="more-btn")

            remote_opts = [(r, r) for r in self._remotes] if self._remotes else [("(sin remotos)", "__none__")]
            yield Select(remote_opts, id="remote-sel", prompt="Selecciona remoto a eliminar")
            yield Button("➖ Remove Remote",             id="mo-rrem",   variant="error",   classes="more-btn")

            yield Button("✖ Cerrar",                    id="close-btn", variant="default")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id
        if bid == "close-btn":
            self.dismiss(None)
            return
        result = {"action": bid}
        if bid == "mo-clone":
            result["url"] = self.query_one("#clone-url",  Input).value.strip()
            result["dir"] = self.query_one("#clone-dir",  Input).value.strip()
        elif bid == "mo-radd":
            result["name"] = self.query_one("#remote-name", Input).value.strip()
            result["url"]  = self.query_one("#remote-url",  Input).value.strip()
        elif bid == "mo-rrem":
            sel = self.query_one("#remote-sel", Select)
            result["name"] = str(sel.value) if sel.value else ""
        self.dismiss(result)


# ══════════════════════════════════════════════════════════
#  APLICACIÓN PRINCIPAL
# ══════════════════════════════════════════════════════════
class GitTUIUltimate(App):

    CSS = """
    /* ── Layout ── */
    #main-container { height: 1fr; }
    #left-sidebar   { width: 34%; height: 100%; border-right: solid $primary; padding: 1; }
    #right-content  { width: 66%; height: 100%; padding: 1; }

    /* ── Botones: dos filas compactas ── */
    #action-rows    { height: auto; margin-bottom: 1; }
    #row1           { height: 3; margin-bottom: 1; }
    #row2           { height: 3; }
    #btn-login      { width: 12; margin-right: 1; }
    #btn-pull       { width: 8;  margin-right: 1; }
    #btn-push       { width: 8; }
    #btn-stash      { width: 12; margin-right: 1; }
    #btn-more       { width: 8; }

    /* ── Ramas ── */
    #list-local     { height: 1fr; }
    #list-remote    { height: 1fr; }

    /* ── Staging ── */
    #staging-area   { height: 38%; margin-bottom: 1; }
    .stage-col      { width: 1fr; height: 100%; border: round $secondary; padding: 1; margin: 0 1; }
    .stage-label    { text-style: bold; margin-bottom: 1; }

    /* ── Commit ── */
    #commit-panel   { height: 5; margin-bottom: 1; align: left middle; }
    #commit-input   { width: 1fr; margin-right: 1; }
    #btn-commit     { width: 12; }

    /* ── Graph ── */
    #graph-label    { text-style: bold; margin-bottom: 1; }
    #graph-log      { height: 1fr; border: round $secondary; }
    """

    BINDINGS = [
        Binding("q", "quit",    "Salir"),
        Binding("r", "refresh", "Refrescar"),
        Binding("m", "more",    "Más"),
    ]

    BOT_PATTERNS = [
        r'dependabot', r'renovate', r'github-actions', r'\bbot\b',
        r'snyk-', r'auto-update', r'mergify',
    ]
    INTERNAL_PATTERNS = [
        r'/HEAD$', r'gh-readonly-queue', r'merge-queue',
        r'refs/pull/', r'__',
    ]

    def __init__(self):
        super().__init__()
        self.github_token = None
        self.github_user  = None
        try:
            self.repo    = git.Repo(os.getcwd(), search_parent_directories=True)
            self.is_repo = True
        except Exception:
            self.is_repo = False

    # ── Composición ──────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main-container"):

            with Vertical(id="left-sidebar"):
                with Vertical(id="action-rows"):
                    with Horizontal(id="row1"):
                        yield Button("🔑 Login", id="btn-login", variant="primary")
                        yield Button("⬇ Pull",   id="btn-pull",  variant="warning")
                        yield Button("⬆ Push",   id="btn-push",  variant="success")
                    with Horizontal(id="row2"):
                        yield Button("📦 Stash", id="btn-stash", variant="default")
                        yield Button("⚙ Más",   id="btn-more",  variant="primary")

                with TabbedContent():
                    with TabPane("Locales"):
                        yield OptionList(id="list-local")
                    with TabPane("Remotas"):
                        yield OptionList(id="list-remote")

            with Vertical(id="right-content"):
                with Horizontal(id="staging-area"):
                    with Vertical(classes="stage-col"):
                        yield Label("📂 Sin stagear  (clic → stagear)", classes="stage-label")
                        yield OptionList(id="list-unstaged")
                    with Vertical(classes="stage-col"):
                        yield Label("✅ Staged  (clic → destagear)", classes="stage-label")
                        yield OptionList(id="list-staged")

                with Horizontal(id="commit-panel"):
                    yield Input(placeholder="Mensaje del commit…", id="commit-input")
                    yield Button("💬 Commit", id="btn-commit", variant="primary")

                yield Label("📈 Git Graph", id="graph-label")
                yield RichLog(id="graph-log", highlight=True)

        yield Footer()

    # ── Ciclo de vida ────────────────────────────────────────────────
    def on_mount(self) -> None:
        if self.is_repo:
            self.refresh_ui()
            self.set_interval(5.0, self.refresh_ui)
        else:
            self.notify("⚠️  No se detectó repositorio Git", severity="warning")

    def action_refresh(self) -> None: self.refresh_ui()
    def action_more(self) -> None:    self._open_more()

    def refresh_ui(self) -> None:
        self.update_branches()
        self.update_staging()
        self.update_graph()

    # ── Ramas ────────────────────────────────────────────────────────
    def _is_bot(self, name: str) -> bool:
        return any(re.search(p, name.lower()) for p in self.BOT_PATTERNS)

    def _is_internal(self, name: str) -> bool:
        return any(re.search(p, name) for p in self.INTERNAL_PATTERNS)

    def update_branches(self) -> None:
        local_list = self.query_one("#list-local", OptionList)
        local_list.clear_options()
        try:
            current = self.repo.active_branch.name
        except Exception:
            current = ""
        for b in self.repo.heads:
            icon = "▶ " if b.name == current else "  "
            local_list.add_option(f"{icon}🏷  {b.name}")

        remote_list = self.query_one("#list-remote", OptionList)
        remote_list.clear_options()
        try:
            shown = [
                ref.name for ref in self.repo.remotes.origin.refs
                if not self._is_internal(ref.name) and not self._is_bot(ref.name)
            ]
            for n in shown:
                remote_list.add_option(f"☁️  {n}")
            if not shown:
                remote_list.add_option("(sin ramas remotas visibles)")
        except Exception:
            remote_list.add_option("⚠️  Sin remoto 'origin'")

    # ── Staging ──────────────────────────────────────────────────────
    def update_staging(self) -> None:
        un = self.query_one("#list-unstaged", OptionList)
        st = self.query_one("#list-staged",   OptionList)
        un.clear_options(); st.clear_options()
        for f in [i.a_path for i in self.repo.index.diff(None)] + self.repo.untracked_files:
            un.add_option(f"📄 {f}")
        try:
            for i in self.repo.index.diff("HEAD"):
                st.add_option(f"✅ {i.a_path}")
        except Exception:
            pass

    # ── Graph ─────────────────────────────────────────────────────────
    def update_graph(self) -> None:
        w = self.query_one("#graph-log", RichLog)
        w.clear()
        try:
            g = self.repo.git.log(
                "--graph", "--color=always",
                "--format=%C(auto)%h %C(bold blue)%an%C(reset) %s %C(green)(%cr)%C(reset)",
                "-n", "20",
            )
            w.write(Text.from_ansi(g))
        except Exception as e:
            w.write(f"[red]{e}[/red]")

    # ── URL autenticada ───────────────────────────────────────────────
    def _auth_url(self, remote: str = "origin"):
        if not (self.github_token and self.github_user):
            return None
        try:
            url = self.repo.remote(remote).url
            if url.startswith("https://"):
                return url.replace("https://", f"https://{self.github_user}:{self.github_token}@", 1)
        except Exception:
            return None

    def _remote_names(self) -> list:
        try:    return [r.name for r in self.repo.remotes]
        except: return []

    # ── Más opciones ─────────────────────────────────────────────────
    def _open_more(self) -> None:
        def handle(result):
            if not result:
                return
            a = result.get("action", "")

            if a == "mo-fetch":
                try:
                    self.repo.git.fetch("--all")
                    self.notify("📡  Fetch completado"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Fetch: {e}", severity="error")

            elif a == "mo-sync":
                try:
                    auth = self._auth_url()
                    self.repo.git.pull(auth) if auth else self.repo.git.pull()
                    branch = self.repo.active_branch.name
                    auth = self._auth_url()
                    self.repo.git.push(auth, branch) if auth else self.repo.git.push()
                    self.notify("🔄  Sync completado"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Sync: {e}", severity="error")

            elif a == "mo-stash":
                try:
                    self.repo.git.stash("push", "-m", "stash desde TUI")
                    self.notify("📦  Stash guardado"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Stash: {e}", severity="error")

            elif a == "mo-pop":
                try:
                    self.repo.git.stash("pop")
                    self.notify("📤  Stash aplicado"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Stash pop: {e}", severity="error")

            elif a == "mo-sdrop":
                try:
                    self.repo.git.stash("drop")
                    self.notify("🗑  Stash eliminado")
                except Exception as e:
                    self.notify(f"❌  Stash drop: {e}", severity="error")

            elif a == "mo-clone":
                url = result.get("url", "")
                dst = result.get("dir", "") or os.getcwd()
                if not url:
                    self.notify("⚠️  Introduce una URL", severity="warning"); return
                try:
                    git.Repo.clone_from(url, dst)
                    self.notify(f"🧬  Clonado en {dst}")
                except Exception as e:
                    self.notify(f"❌  Clone: {e}", severity="error")

            elif a == "mo-radd":
                name = result.get("name", "")
                url  = result.get("url",  "")
                if not name or not url:
                    self.notify("⚠️  Nombre y URL obligatorios", severity="warning"); return
                try:
                    self.repo.create_remote(name, url)
                    self.notify(f"➕  Remote '{name}' añadido"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Add remote: {e}", severity="error")

            elif a == "mo-rrem":
                name = result.get("name", "")
                if not name or name == "__none__":
                    self.notify("⚠️  Selecciona un remoto", severity="warning"); return
                try:
                    self.repo.delete_remote(name)
                    self.notify(f"➖  Remote '{name}' eliminado"); self.refresh_ui()
                except Exception as e:
                    self.notify(f"❌  Remove remote: {e}", severity="error")

        self.push_screen(MoreOptionsScreen(self._remote_names()), handle)

    # ── Botones ───────────────────────────────────────────────────────
    async def on_button_pressed(self, event: Button.Pressed) -> None:
        bid = event.button.id

        if bid == "btn-login":
            def hc(r):
                if r:
                    self.github_token = r["token"]
                    self.github_user  = r["user"]
                    self.notify(f"✅  Sesión para '{self.github_user}'")
            self.push_screen(GitHubLoginScreen(), hc)

        elif bid == "btn-pull":
            if not self.is_repo: self.notify("⚠️  No hay repo", severity="warning"); return
            try:
                auth = self._auth_url()
                self.repo.git.pull(auth) if auth else self.repo.git.pull()
                self.notify("⬇  Pull completado"); self.refresh_ui()
            except Exception as e:
                self.notify(f"❌  Pull: {e}", severity="error")

        elif bid == "btn-push":
            if not self.is_repo: self.notify("⚠️  No hay repo", severity="warning"); return
            try:
                auth   = self._auth_url()
                branch = self.repo.active_branch.name
                self.repo.git.push(auth, branch) if auth else self.repo.git.push()
                self.notify("⬆  Push completado")
            except Exception as e:
                self.notify(f"❌  Push: {e}", severity="error")

        elif bid == "btn-stash":
            if not self.is_repo: self.notify("⚠️  No hay repo", severity="warning"); return
            try:
                self.repo.git.stash("push", "-m", "stash desde TUI")
                self.notify("📦  Stash guardado"); self.refresh_ui()
            except Exception as e:
                self.notify(f"❌  Stash: {e}", severity="error")

        elif bid == "btn-more":
            self._open_more()

        elif bid == "btn-commit":
            if not self.is_repo: self.notify("⚠️  No hay repo", severity="warning"); return
            inp = self.query_one("#commit-input", Input)
            msg = inp.value.strip()
            if not msg: self.notify("⚠️  Escribe un mensaje", severity="warning"); return
            try:
                self.repo.index.commit(msg)
                inp.value = ""
                self.notify(f"💬  Commit: '{msg}'"); self.refresh_ui()
            except Exception as e:
                self.notify(f"❌  Commit: {e}", severity="error")

    # ── Selección en listas ──────────────────────────────────────────
    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        raw  = str(event.option.prompt)
        path = raw.split(" ", 1)[-1].strip()
        eid  = event.control.id

        if eid == "list-unstaged":
            try:
                self.repo.git.add(path)
                self.notify(f"✅  Stageado: {path}")
            except Exception as e:
                self.notify(f"❌  {e}", severity="error")
            self.refresh_ui()

        elif eid == "list-staged":
            try:
                self.repo.git.restore("--staged", path)
                self.notify(f"↩️  Destageado: {path}")
            except Exception as e:
                self.notify(f"❌  {e}", severity="error")
            self.refresh_ui()

        elif eid == "list-local":
            # Limpiar prefijos de icono para obtener el nombre puro
            branch = re.sub(r'^[▶\s🏷️\s]+', '', path).strip()
            def handle_action(action):
                if not action: return
                if action == "checkout":
                    try:
                        self.repo.git.checkout(branch)
                        self.notify(f"🔀  Checkout → '{branch}'"); self.refresh_ui()
                    except Exception as e:
                        self.notify(f"❌  Checkout: {e}", severity="error")
                elif action == "rebase":
                    try:
                        self.repo.git.rebase(branch)
                        self.notify(f"🔁  Rebase sobre '{branch}'"); self.refresh_ui()
                    except Exception as e:
                        self.notify(f"❌  Rebase: {e}", severity="error")
            self.push_screen(BranchActionScreen(branch), handle_action)


# ══════════════════════════════════════════════════════════
if __name__ == "__main__":
    GitTUIUltimate().run()