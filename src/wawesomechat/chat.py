from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import logging
import traceback
import os
import sys
from pathlib import Path
from typing import Any, Iterable, List, Optional


try:  # Pyodide runtime provides the `js` module.
    import js  # type: ignore
    from pyodide.ffi import create_proxy
except ModuleNotFoundError:  # pragma: no cover - desktop import before Pyodide bootstraps
    js = None  # type: ignore

    def create_proxy(callback):  # type: ignore
        raise RuntimeError("create_proxy is only available inside the Pyodide runtime")

from wapyt.cardpanel import CardPanelConfig, CardPanelCardConfig
from wapyt.chat import ChatConfig, ChatAgentConfig, ChatMessageConfig
from wapyt.layout import MainWindow, Layout, LayoutConfig, CellConfig
from wapyt.modal import ModalWindow, ModalConfig
from wapyt.resourceboard import ResourceBoardConfig, ResourceItem
from wapyt.tabwidget import TabWidgetConfig, TabConfig

_PROXY_IMPORT_ERROR = None
_STORAGE_IMPORT_ERROR = None

try:
    from multiaiproxy import multiaiproxy as _OpenAIProxy
except Exception as exc:  # pragma: no cover - backend import optional in Pyodide
    OpenAIProxy = None
    _PROXY_IMPORT_ERROR = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
else:
    OpenAIProxy = _OpenAIProxy

try:
    from provider_admin import provider_admin as ProviderAdminBackend
except Exception:  # pragma: no cover - optional in non-Pyodide environments
    ProviderAdminBackend = None

try:
    from storage import ChatStorage as _ChatStorage
except Exception as exc:  # pragma: no cover - SQLAlchemy optional in Pyodide
    ChatStorage = None
    _STORAGE_IMPORT_ERROR = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
else:
    ChatStorage = _ChatStorage

from config import settings_from_env
from provider_catalog import DEFAULT_PROVIDER_CATALOG, DEFAULT_PROVIDER_SCHEMAS, DEFAULT_PROVIDER_SECRETS


SYSTEM_PROMPT = """
    Code Generation Instructions
!!!!IMPORTANT THIS SECTION IS FOR HTML GENERATION!!!
<SECTION>
HTML Generation
When asked to generate a page or similar HTML content:

Format: Use artifact blocks with the following syntax:
less
Copy code
::::Artifact Dashboard Snapshot | renderer=iframe | language=html
[HTML content here]
::::Artifact
Trigger: Only generate HTML artifacts when explicitly asked to "generate a page" or similar request
</SECTION>

!You're absolutely right! Here's the updated section:

!!!IMPORTANT THIS SECTION IS FOR PYTHON DIRECT CODE GENERATION JUST TO PRINT EXAMPLE CONSOLE NOT FOR APPS!!!
<SECTION>
Python Generation
When generating Python code:

Format: Use artifact blocks with the following syntax:
::::Artifact [Title] | language=python
[Python code here]
::::Artifact

Critical Python Rules:
NEVER use markdown code blocks (```python). ALWAYS use artifact blocks instead.
NEVER use if __name__ == "__main__": (dunder name main) in any Python code.
ALWAYS include visible output - ensure every Python script produces output that will display when run.
No interactive elements - only static generation, no user input required.
ALWAYS close the artifact block with the proper end tag
Package Installation
For Python packages not in standard library, use this simple synchronous approach:

import js
import asyncio

async def pushdown():
    js.pyodide.loadPackage("micropip")
    import micropip
    await micropip.install('package_name')

asyncio.run(pushdown())

def install_and_run():
    # Import and use the packages
    import package_name
    
    # Your main code here
    print("Package installed and code executed successfully!")
    return result

# Call the function and use the result
result = install_and_run()
print(result)

IMPORTANT: Do NOT use asyncio.run(), async/await, or event loop management in Pyodide environment. Use micropip.install() synchronously inside a regular function.

General Rules
Always close artifact blocks properly with the end tag
Only generate artifacts when explicitly requested
Ensure all generated code is complete and functional
Python code must always produce visible output
Use synchronous micropip.install() approach for package installation
</SECTION>

!!!!IMPORTANT THIS SECTION IS FOR PYTHON WEB APPS WITH DHXPYT LIKE SINGLE PAGE APPS!!!
<SECTION>
You are a UI-building agent. Produce one self-contained HTML file that runs in-browser with pytincture.js and dhxpyt (Pyodide). Build UIs only with dhxpyt components and documented events. Use the Capability Registry to select components and verify parameters and methods. Do not invent methods.

Output and bootstrap

Output exactly one artifact: index.html (complete HTML, opens directly).
Include <script src="https://cdn.jsdelivr.net/npm/@pytincture/runtime@0.9.22/dist/pytincture.min.js"></script> in head.
Include <script type="text/json" id="micropip-libs"> with only the Python packages you actually use (e.g., ["faker"]).
Put all Python code in a single <script type="text/python">.
Do not write any manual startup code. A MainWindow subclass definition is sufficient; pytincture.js auto-runs it.
Core structure

Define class QuickstartApp(MainWindow).
In QuickstartApp.load_ui:
Optionally self.set_theme("dark" or "light").
Create one or more Layout subclasses to build the UI.
Attach your root layout with self.attach("mainwindow", layout.layout).
Implement all UI with dhxpyt components only.
Use create_proxy for events and make handlers instance methods.
Registry-driven constraints and validations

Only use classes, config keys, methods, and events present in the Capability Registry. Do not assume undocumented APIs.
Before referencing a method, validate it exists in the registry. If not present, do not use it.
Example: Do not use grid.data or grid.parse unless the registry explicitly lists them. If not listed, use the Safe Widget Refresh pattern below.
Safe widget refresh pattern (prevents grid/data/parse errors)

Never rely on undocumented “data” or “parse” properties/methods on widgets.
Use a stable container cell:
Create a container layout and a dedicated cell (e.g., grid_cell) to host a widget instance.
To refresh the widget, call the same add_* method again with the same cell id; the framework will reattach/replace the widget in that cell.
Do not remove the cell or reuse a non-existing cell id; keep ids stable.
Keep state in instance variables (e.g., self.rows), not globals.
Stable IDs and layout rules

Every cell id must be unique within its layout and remain stable. Don’t delete/recreate cells during runtime; reattach widgets to the same cell instead.
If you need to swap content, nest layouts and attach into a dedicated content cell (e.g., content_container -> content_cell).
When using a collapsible sidebar, set the layout cell width to "auto"; define sidebar width in the SidebarConfig if needed.
Sidebar specifics

For separators, use SeparatorConfig (not NavItemConfig with type="separator").
For collapsible behavior to work:
In layout, CellConfig(id="sidebar", width="auto")
In SidebarConfig, you may set width="250" (string) to control expanded width.
Use sidebar.on_click(create_proxy(handler)) and implement handler accordingly.
Grid selection and actions

If GridConfig supports selection, set selection="row" (and multiselection=True if needed) as documented in the registry.
To identify selected rows, use documented selection accessors from the registry (e.g., get_selected_cells()).
If the registry does not document a selection accessor, approximate by tracking selection via events (e.g., on_cell_click) and maintaining self.selected_ids.
Event wiring

Only wire events that the registry documents (e.g., on_click, on_cell_click).
Handlers must match expected signatures; if the registry lists (id, event) for a toolbar click, implement def on_toolbar_click(self, id, event).
Data and packages

All data generation/processing must be client-side. Use Faker or DuckDB only if needed; list them in micropip-libs.
Do not add unused packages to micropip-libs.
Do not do these

Do not call undocumented properties or methods (e.g., grid.data, grid.parse) unless present in registry.
Do not remove or recreate layout cells by id at runtime and then re-add with the same id (causes attach to None).
Do not guess parameters (e.g., NavItemConfig(type="separator")). Use the exact config classes from the registry.
Self-checks before returning artifact

All add_* calls attach to cells that are defined in the LayoutConfig tree.
For collapsible sidebar, the sidebar cell width is "auto".
All methods used exist in the registry for the chosen component.
Widget refresh is done by re-adding the widget to the same stable cell, not via undocumented methods.
No globals for app state; use instance variables.
Updated starter template (uses safe refresh, stable IDs, proper sidebar, no undocumented grid methods)

<!DOCTYPE html> <html lang="en"> <head> <meta charset="UTF-8"/> <meta name="viewport" content="width=device-width, initial-scale=1.0"/> <title>DHXPYT App</title> <script src="https://cdn.jsdelivr.net/npm/@pytincture/runtime@0.9.22/dist/pytincture.min.js"></script> </head> <body> <div id="maindiv" style="width: 100%; height: 100vh;"></div> <script type="text/json" id="micropip-libs"> ["faker"] </script> <script type="text/python"> import traceback import random from pyodide.ffi import create_proxy from dhxpyt.layout import MainWindow, Layout, LayoutConfig, CellConfig from dhxpyt.grid import GridConfig, GridColumnConfig from dhxpyt.toolbar import ButtonConfig, ToolbarConfig from dhxpyt.sidebar import NavItemConfig, SidebarConfig, SeparatorConfig from faker import Faker fake = Faker() def make_people(n=20): roles = ['Developer', 'Designer', 'Manager', 'Analyst'] return [ { "id": i, "name": fake.name(), "email": fake.email(), "city": fake.city(), "role": random.choice(roles) } for i in range(1, n+1) ] class AppMain(Layout): layout_config = LayoutConfig( type="line", cols=[ CellConfig(id="sidebar", width="auto"), # auto for proper collapse CellConfig(id="content") ] ) def load_ui(self): try: # State self.rows = make_people() self.current_view = "all" self.selected_ids = set() # Sidebar items = [ NavItemConfig(id="hamburger", icon="mdi mdi-menu"), NavItemConfig(id="all", value="All People", icon="mdi mdi-account-group"), NavItemConfig(id="developers", value="Developers", icon="mdi mdi-code-tags"), NavItemConfig(id="designers", value="Designers", icon="mdi mdi-palette"), NavItemConfig(id="managers", value="Managers", icon="mdi mdi-briefcase"), NavItemConfig(id="analysts", value="Analysts", icon="mdi mdi-chart-line"), SeparatorConfig(id="sep"), NavItemConfig(id="stats", value="Statistics", icon="mdi mdi-chart-bar") ] self.sidebar = self.add_sidebar( id="sidebar", sidebar_config=SidebarConfig(data=items, collapsed=False, width="250") ) self.sidebar.on_click(create_proxy(self.on_sidebar_click)) # Content area: toolbar + grid container content_cfg = LayoutConfig( type="line", rows=[CellConfig(id="toolbar", height="auto"), CellConfig(id="grid_container")] ) self.content = self.add_layout("content", content_cfg) self.toolbar = self.content.add_toolbar( id="toolbar", toolbar_config=ToolbarConfig(data=[ ButtonConfig(id="refresh", value="Refresh", icon="mdi mdi-refresh"), ButtonConfig(id="add", value="Add Person", icon="mdi mdi-plus"), ButtonConfig(id="delete", value="Delete Selected", icon="mdi mdi-delete") ]) ) self.toolbar.on_click(create_proxy(self.on_toolbar_click)) # Dedicated, stable cell for the grid grid_host_cfg = LayoutConfig(type="line", rows=[CellConfig(id="grid_cell")]) self.grid_host = self.content.add_layout("grid_container", grid_host_cfg) # Initial grid self.render_grid() except Exception as e: print("UI error:", e) print(''.join(traceback.format_exception(e))) def filtered_rows(self): v = self.current_view if v == "all": return self.rows role_map = { "developers": "Developer", "designers": "Designer", "managers": "Manager", "analysts": "Analyst" } role = role_map.get(v) return [r for r in self.rows if r["role"] == role] if role else self.rows def render_grid(self): try: cols = [ GridColumnConfig(id="id", width=70, header=[{"text": "ID"}]), GridColumnConfig(id="name", width=200, header=[{"text": "Name"}]), GridColumnConfig(id="email", width=250, header=[{"text": "Email"}]), GridColumnConfig(id="city", width=150, header=[{"text": "City"}]), GridColumnConfig(id="role", width=150, header=[{"text": "Role"}]) ] data = self.filtered_rows() # Safe refresh: re-add the grid into the same stable cell id self.grid = self.grid_host.add_grid( id="grid_cell", grid_config=GridConfig( columns=cols, data=data, selection="row", multiselection=True ) ) # Event wiring per registry (example: on_cell_click) self.grid.on_cell_click(create_proxy(self.on_cell_click)) except Exception as e: print("Grid render error:", e) print(''.join(traceback.format_exception(e))) def on_sidebar_click(self, id, event): try: if id == "hamburger": self.sidebar.toggle() elif id in ["all", "developers", "designers", "managers", "analysts"]: self.current_view = id self.render_grid() elif id == "stats": self.show_statistics() except Exception as e: print("Sidebar error:", e) def show_statistics(self): try: role_counts = {} for r in self.rows: role_counts[r["role"]] = role_counts.get(r["role"], 0) + 1 print("=== People Stats ===") print(f"Total: {len(self.rows)}") for k in sorted(role_counts.keys()): print(f"{k}s: {role_counts[k]}") except Exception as e: print("Stats error:", e) def on_cell_click(self, row, column, event): try: rid = row.get("id") if rid in self.selected_ids: self.selected_ids.remove(rid) else: self.selected_ids.add(rid) print(f"Clicked row {rid}. Selected IDs: {sorted(self.selected_ids)}") except Exception as e: print("Cell click error:", e) def on_toolbar_click(self, id, event): try: if id == "refresh": self.rows = make_people() self.selected_ids.clear() self.render_grid() elif id == "add": new_id = max([r["id"] for r in self.rows] + [0]) + 1 self.rows.append({ "id": new_id, "name": fake.name(), "email": fake.email(), "city": fake.city(), "role": random.choice(['Developer', 'Designer', 'Manager', 'Analyst']) }) self.render_grid() print(f"Added person {new_id}") elif id == "delete": # Preferred approach: use a documented selection API (e.g., get_selected_cells()) if present in registry. # Fallback here is our own selected_ids set from on_cell_click. if self.selected_ids: self.rows = [r for r in self.rows if r["id"] not in self.selected_ids] self.selected_ids.clear() self.render_grid() print("Deleted selected rows") else: print("No selection to delete") except Exception as e: print("Toolbar error:", e) print(''.join(traceback.format_exception(e))) class QuickstartApp(MainWindow): def load_ui(self): try: self.set_theme("dark") self.main_layout = AppMain(parent=self) self.attach("mainwindow", self.main_layout.layout) except Exception as e: print("Main load error:", e) print(''.join(traceback.format_exception(e))) </script> </body> </html>
Why this prevents prior issues

No undocumented grid methods: We do not call grid.data or grid.parse. We refresh by re-adding the grid into a stable cell.
Stable cell/ID usage: We never remove cells. grid_cell exists permanently as an anchor; add_grid replaces the widget in that cell.
Sidebar separator: Uses SeparatorConfig instead of an invalid type param on NavItemConfig.
Sidebar collapse: Sidebar cell width="auto" so it collapses correctly; sidebar widget’s width is set via SidebarConfig.
Selection: Uses documented config fields; if selection accessors are undocumented, the template tracks selection via on_cell_click. If the registry provides get_selected_cells, use it instead.
State management: Stored as instance variables, not globals, avoiding cross-scope surprises.
You can drop this into your agent as the new system/context plus the template. The agent then composes additional widgets by:

Verifying each against the Capability Registry,
Importing only documented classes,
Adding them into stable cells,
Refreshing them with the same safe reattach pattern if they need data updates.

use python_code_mapping.txt that is in your search documents instead of trying to guess
don't add extra tabs to the code since its python and formatting matters a lot
</SECTION>
"""

CARD_SECTION_VIEWPORT = "220px"
SESSION_ENV_VAR = "WA_CHAT_SESSION"
HISTORY_LIMIT = 100

LOGGER = logging.getLogger("wawesomechat.ui")
if _PROXY_IMPORT_ERROR:
    LOGGER.warning(
        "MultiAIProxy import failed; backend streaming disabled until resolved.\n%s",
        _PROXY_IMPORT_ERROR,
    )
if _STORAGE_IMPORT_ERROR:
    LOGGER.warning(
        "ChatStorage import failed; persistence disabled until resolved.\n%s",
        _STORAGE_IMPORT_ERROR,
    )


class WAwesomeChat(MainWindow):
    layout_config = LayoutConfig(rows=[CellConfig(id="tabs", grow=1)])

    def __init__(self):
        super().__init__()
        self._chat_widget = None
        self._session_id = os.getenv(SESSION_ENV_VAR, "local")
        self._storage = self._init_storage()
        if self._storage is None:
            self._log(logging.INFO, "Storage unavailable; chat transcripts will not be persisted")
        else:
            self._log(logging.INFO, f"Storage initialised for session '{self._session_id}'")
        self._history_buffer: List[ChatMessageConfig] = []
        self._openai_proxy: Optional[Any] = None  # type: ignore[name-defined]
        self._system_prompt = SYSTEM_PROMPT
        self._default_model = os.getenv("CHAT_DEMO_DEFAULT_MODEL", "gpt-4o-mini")
        self._provider_schemas = copy.deepcopy(DEFAULT_PROVIDER_SCHEMAS)
        self._provider_snapshot = None
        self._provider_backend = ProviderAdminBackend() if ProviderAdminBackend else None
        self._base_catalog = self._base_provider_catalog()
        self._default_catalog = self._normalize_provider_catalog(self._base_catalog)
        self._models = self._build_initial_models(self._default_catalog)
        self._provider_catalog = copy.deepcopy(self._default_catalog)
        self._providers = self._load_providers()
        for provider_id in list(self._providers.keys()):
            self._models.setdefault(provider_id, [])
            self._provider_catalog.setdefault(provider_id, [])
        self._active_provider = next(iter(self._providers), None)
        self._users = {
            "alice": {
                "id": "alice",
                "name": "Alice",
                "providers": {"aws", "openai"},
                "models": {"gpt-4o-mini"},
            },
            "ben": {
                "id": "ben",
                "name": "Ben",
                "providers": {"anthropic"},
                "models": {"claude-3-7-sonnet"},
            },
        }
        self._active_user = next(iter(self._users), None)
        self._provider_modal = ModalWindow(ModalConfig(title="Add Provider", width=540, height=520))
        self._model_modal = ModalWindow(ModalConfig(title="Add Model", width=480, height=320))
        self._user_modal = ModalWindow(ModalConfig(title="Add User", width=460, height=320))
        self._provider_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="provider_form", grow=1)], borderless=True, gap="0px"))
        self._model_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="model_form", grow=1)], borderless=True, gap="0px"))
        self._user_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="user_form", grow=1)], borderless=True, gap="0px"))
        self._provider_modal.set_content(self._provider_modal_layout.layout)
        self._model_modal.set_content(self._model_modal_layout.layout)
        self._user_modal.set_content(self._user_modal_layout.layout)
        self._provider_cards_widget = None
        self._model_cards_widget = None
        self._user_access_board = None
        self._active_user_provider = None
        self.set_theme("dark")
        fallback_catalog = self._provider_catalog or self._default_catalog
        self._available_models = self._flatten_model_catalog(fallback_catalog)
        self._load_previous_history()

    def load_ui(self):
        snapshot = self._fetch_provider_snapshot()
        if snapshot:
            updated_providers = self._apply_snapshot(snapshot)
            if updated_providers:
                self._providers = updated_providers
                for provider_id in list(self._providers.keys()):
                    self._models.setdefault(provider_id, [])
                    self._provider_catalog.setdefault(provider_id, [])

        agent = ChatAgentConfig(
            name="BriskChatter",
            tagline="Wapyt-native assistant",
            avatar="https://avatars.githubusercontent.com/u/6344670?v=4",
        )
        welcome = ChatMessageConfig(
            role="assistant",
            name="BriskChatter",
            content="Welcome to the wAwesomeChat workspace. Ask me anything!",
            timestamp=dt.datetime.utcnow().isoformat(),
        )
        tabs = self.add_tabwidget(
            "tabs",
            TabWidgetConfig(
                tabs=[
                    TabConfig(id="chat", title="Chat"),
                    TabConfig(id="admin", title="Providers"),
                    TabConfig(id="users", title="Users"),
                ],
                active="chat",
            ),
        )
        chat_layout = Layout(LayoutConfig(rows=[CellConfig(id="chat_body", grow=1)], borderless=True, gap="0px"))
        tabs.attach("chat", chat_layout.layout)
        self._ensure_proxy()
        provider_catalog = copy.deepcopy(self._provider_catalog)
        available_models = self._flatten_model_catalog(provider_catalog or self._default_catalog)
        if self._openai_proxy:
            try:
                remote_catalog = self._openai_proxy.get_available_models() or {}
                remote_catalog = self._normalize_provider_catalog(remote_catalog)
                flattened = self._flatten_model_catalog(remote_catalog)
                if remote_catalog and flattened:
                    provider_catalog = remote_catalog
                    available_models = flattened
                    self._log(logging.INFO, "Loaded provider catalog from backend proxy")
            except Exception as exc:  # pragma: no cover - diagnostics only
                self._log(logging.WARNING, f"Unable to load provider catalog: {exc}\n{_format_exception(exc)}")
        if not provider_catalog:
            provider_catalog = self._default_catalog
            available_models = self._flatten_model_catalog(provider_catalog)
            self._log(logging.INFO, "No stored provider catalog; using in-memory defaults")
        for provider_id in provider_catalog.keys():
            self._ensure_provider_entry(provider_id)
        self._models.update(self._build_initial_models(provider_catalog))
        self._available_models = available_models
        self._provider_catalog = copy.deepcopy(provider_catalog)
        chat_extra = {"models": available_models}
        if provider_catalog:
            chat_extra["providerConfig"] = {"providers": provider_catalog}
        initial_messages = self._history_buffer[:] if self._history_buffer else [welcome]
        self._history_buffer.clear()
        self._chat_widget = chat_layout.add_chat(
            "chat_body",
            ChatConfig(
                agent=agent,
                messages=initial_messages,
                storage_key="wawesomechat",
                layout_mode="advanced",
                layout_density="comfortable",
                auto_append_user_messages=False,
                extra=chat_extra,
            ),
        )
        self._chat_widget.on_send(self.handle_send)
        admin_layout = Layout(
            LayoutConfig(
                rows=[
                    CellConfig(id="provider_cards", header="Providers", height="260px"),
                    CellConfig(id="provider_models", header="Models", height="260px"),
                ],
                borderless=True,
                gap="6px",
            )
        )
        tabs.attach("admin", admin_layout.layout)
        self._build_admin_panel(admin_layout)
        users_layout = Layout(
            LayoutConfig(
                rows=[
                    CellConfig(id="user_list", height="45%"),
                    CellConfig(id="user_access", grow=1),
                ],
                borderless=True,
                gap="0px",
            )
        )
        tabs.attach("users", users_layout.layout)
        self._build_users_panel(users_layout)

    # ------------------------------------------------------------------ Provider data helpers

    def _parse_provider_config(self, raw):
        if not raw:
            return {}
        if isinstance(raw, dict):
            return raw
        try:
            parsed = json.loads(raw)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _catalog_from_provider_items(self, provider_items):
        catalog = {}
        for item in provider_items or []:
            slug = item.get("slug") or item.get("id")
            provider_id = self._normalize_provider_id(slug or "")
            models = item.get("models")
            config = self._parse_provider_config(item.get("config"))
            models = models or config.get("models")
            if provider_id and models:
                catalog[provider_id] = models
        return catalog

    def _default_secrets_for(self, provider_type: Optional[str]):
        if not provider_type:
            return {}
        key = self._denormalize_provider_id(provider_type)
        if key in DEFAULT_PROVIDER_SECRETS:
            return DEFAULT_PROVIDER_SECRETS[key]
        return DEFAULT_PROVIDER_SECRETS.get(provider_type, {})

    def _default_models_for_provider(self, provider_type: Optional[str]):
        if not provider_type:
            return None
        slug = self._denormalize_provider_id(provider_type)
        schema = self._provider_schemas.get(slug) or self._provider_schemas.get(provider_type)
        if not schema:
            return None
        config = schema.get("config") or {}
        models = None
        if isinstance(config, dict):
            if "models" in config:
                models = config.get("models")
            elif slug in config:
                models = config.get(slug)
        return copy.deepcopy(models)

    def _delete_provider(self, provider_id: Optional[str]):
        if not provider_id or provider_id not in self._providers:
            return
        if self._models.get(provider_id):
            self._log(logging.INFO, f"Provider '{provider_id}' cannot be deleted while models exist")
            return
        provider = self._providers.get(provider_id)
        slug = provider.get("slug") if provider else None
        try:
            self._provider_backend_call("delete_provider", arg={"slug": slug or provider_id})
        except Exception as exc:
            self._log(logging.WARNING, f"Unable to delete provider '{provider_id}': {exc}")
        self._providers.pop(provider_id, None)
        self._provider_catalog.pop(provider_id, None)
        self._models.pop(provider_id, None)
        for user in self._users.values():
            if provider_id in user.get("providers", set()):
                user["providers"].discard(provider_id)
            # also drop any models that belonged to this provider
            user["models"] = {m for m in user.get("models", set()) if m in self._flatten_model_catalog(self._provider_catalog)}
        if self._active_provider == provider_id:
            self._active_provider = next(iter(self._providers), None)
        self._refresh_provider_cards()
        self._refresh_model_cards()
        self._refresh_user_access_board(select_provider=self._active_provider)
        self._update_chat_models()

    def _rebuild_available_models(self):
        self._available_models = self._flatten_model_catalog(self._provider_catalog or self._default_catalog)

    def _update_chat_models(self):
        self._rebuild_available_models()
        if not self._chat_widget:
            return
        extra = {"models": self._available_models}
        if self._provider_catalog:
            extra["providerConfig"] = {"providers": self._provider_catalog}
        try:
            if hasattr(self._chat_widget, "set_extra"):
                self._chat_widget.set_extra(extra)
                return
            if hasattr(self._chat_widget, "update_extra"):
                self._chat_widget.update_extra(extra)
                return
            if hasattr(self._chat_widget, "set_models"):
                self._chat_widget.set_models(self._available_models)
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to push updated model list to chat widget: {exc}")

    def _default_provider_entries(self):
        return {
            "aws": self._build_provider_entry(
                provider_id="aws",
                title="AWS Bedrock",
                status="Healthy",
                slug="aws_bedrock",
                pill="AWS",
                icon_class="mdi-aws",
                service="aws_bedrock",
                region=DEFAULT_PROVIDER_SCHEMAS.get("aws_bedrock", {}).get("region"),
                provider_type="aws_bedrock",
                secrets=self._default_secrets_for("aws_bedrock"),
            ),
            "anthropic": self._build_provider_entry(
                provider_id="anthropic",
                title="Anthropic",
                status="Limited",
                slug="anthropic",
                pill="Anthropic",
                icon_class="mdi-brain",
                service="anthropic",
                region=DEFAULT_PROVIDER_SCHEMAS.get("anthropic", {}).get("region"),
                provider_type="anthropic",
                secrets=self._default_secrets_for("anthropic"),
            ),
            "openai": self._build_provider_entry(
                provider_id="openai",
                title="OpenAI",
                status="Healthy",
                slug="openai",
                pill="OpenAI",
                icon_class="mdi-robot-excited",
                service="openai",
                region=DEFAULT_PROVIDER_SCHEMAS.get("openai", {}).get("region"),
                provider_type="openai",
                secrets=self._default_secrets_for("openai"),
            ),
            "google": self._build_provider_entry(
                provider_id="google",
                title="Google Vertex",
                status="Preview",
                slug="google",
                pill="Google",
                icon_class="mdi-google",
                service="google",
                region=DEFAULT_PROVIDER_SCHEMAS.get("google", {}).get("region"),
                provider_type="google",
                secrets=self._default_secrets_for("google"),
            ),
            "xai": self._build_provider_entry(
                provider_id="xai",
                title="xAI Grok",
                status="Healthy",
                slug="xai",
                pill="xAI",
                icon_class="mdi-alpha-x-circle",
                service="xai",
                region=DEFAULT_PROVIDER_SCHEMAS.get("xai", {}).get("region"),
                provider_type="xai",
                secrets=self._default_secrets_for("xai"),
            ),
        }

    def _load_providers(self):
        snapshot = self._provider_snapshot or self._fetch_provider_snapshot()
        if snapshot:
            providers = self._apply_snapshot(snapshot)
            if providers:
                return providers
        if not self._storage:
            return self._default_provider_entries()
        providers = {}
        try:
            records = self._storage.list_providers()
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to load providers from storage: {exc}\n{_format_exception(exc)}")
        else:
            for record in records:
                provider_id = self._normalize_provider_id(record.slug)
                config = self._parse_provider_config(record.config)
                provider_type = config.get("type") or record.service or record.slug
                secrets = config.get("secrets") or self._default_secrets_for(provider_type)
                settings = config.get("settings") or {}
                region = settings.get("region") or record.region
                pill = config.get("pill")
                icon_class = config.get("iconClass")
                providers[provider_id] = self._build_provider_entry(
                    provider_id=provider_id,
                    title=record.title or provider_id.capitalize(),
                    status=config.get("status") or "Healthy",
                    slug=record.slug,
                    service=record.service,
                    region=region,
                    provider_type=provider_type,
                    secrets=secrets,
                    settings=settings,
                    pill=pill,
                    icon_class=icon_class,
                )
                models = config.get("models")
                if models and provider_id not in self._provider_catalog:
                    self._provider_catalog[provider_id] = models
        return providers or self._default_provider_entries()

    def _base_provider_catalog(self):
        storage_catalog = self._catalog_from_storage()
        if storage_catalog:
            return storage_catalog
        return copy.deepcopy(DEFAULT_PROVIDER_CATALOG)

    def _catalog_from_storage(self):
        snapshot = self._provider_snapshot or self._fetch_provider_snapshot()
        if snapshot:
            catalog = snapshot.get("catalog") or self._catalog_from_provider_items(snapshot.get("providers"))
            if catalog:
                self._log(logging.INFO, "Loaded provider catalog from backend storage")
                return catalog
        if not self._storage or not hasattr(self._storage, "provider_catalog"):
            return {}
        try:
            catalog = self._storage.provider_catalog()
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to load provider catalog from storage: {exc}\n{_format_exception(exc)}")
            return {}
        if catalog:
            self._log(logging.INFO, "Loaded provider catalog from storage")
        return catalog

    def _fetch_provider_snapshot(self):
        snapshot = self._provider_backend_call("get_provider_snapshot")
        if snapshot is None and self._storage:
            try:
                catalog = self._storage.provider_catalog()
            except Exception as exc:
                self._log(logging.WARNING, f"Unable to load provider catalog from storage: {exc}\n{_format_exception(exc)}")
                catalog = {}
            providers = []
            if hasattr(self._storage, "list_providers"):
                try:
                    providers = [
                        {
                            "slug": record.slug,
                            "title": record.title,
                            "service": record.service,
                            "region": record.region,
                            "config": record.config,
                        }
                        for record in (self._storage.list_providers() or [])
                    ]
                except Exception as exc:  # pragma: no cover
                    self._log(logging.WARNING, f"Unable to list providers from storage: {exc}\n{_format_exception(exc)}")
            snapshot = {"catalog": catalog, "providers": providers}
        self._provider_snapshot = snapshot
        return snapshot

    def _normalize_provider_catalog(self, raw_catalog):
        if not raw_catalog:
            return {}
        normalized = {}
        for provider_id, data in raw_catalog.items():
            key = self._normalize_provider_id(provider_id)
            normalized[key] = data
        return normalized

    def _providers_from_snapshot(self, provider_items):
        if not provider_items:
            return {}
        providers = {}
        for item in provider_items:
            slug = item.get("slug") or item.get("id")
            provider_id = self._normalize_provider_id(slug or "")
            if not provider_id:
                continue
            config = self._parse_provider_config(item.get("config") or item)
            provider_type = item.get("type") or config.get("type") or item.get("service") or slug
            secrets = item.get("secrets") or config.get("secrets") or self._default_secrets_for(provider_type)
            settings = item.get("settings") or config.get("settings") or {}
            region = item.get("region") or settings.get("region")
            providers[provider_id] = self._build_provider_entry(
                provider_id=provider_id,
                title=item.get("title") or provider_id.capitalize(),
                status=item.get("status") or "Healthy",
                slug=slug,
                service=item.get("service"),
                region=region,
                pill=item.get("pill"),
                icon_class=item.get("iconClass"),
                provider_type=provider_type,
                secrets=secrets,
                settings=settings,
            )
            models = item.get("models") or config.get("models")
            if models:
                self._provider_catalog[provider_id] = models
        return providers

    def _apply_snapshot(self, snapshot):
        if not snapshot:
            return None
        catalog = snapshot.get("catalog") or self._catalog_from_provider_items(snapshot.get("providers"))
        if catalog:
            normalized = self._normalize_provider_catalog(catalog)
            if normalized:
                self._default_catalog = normalized
                self._provider_catalog = copy.deepcopy(normalized)
                self._models = self._build_initial_models(self._provider_catalog)
                self._available_models = self._flatten_model_catalog(self._provider_catalog)
        providers = self._providers_from_snapshot(snapshot.get("providers"))
        self._provider_snapshot = snapshot
        return providers or None

    @staticmethod
    def _normalize_provider_id(slug: str) -> str:
        return "aws" if slug == "aws_bedrock" else slug

    @staticmethod
    def _denormalize_provider_id(provider_id: str) -> str:
        return "aws_bedrock" if provider_id == "aws" else provider_id

    def _build_provider_entry(
        self,
        *,
        provider_id: str,
        title: str,
        status: str,
        slug: Optional[str] = None,
        pill: Optional[str] = None,
        icon_class: Optional[str] = None,
        service: Optional[str] = None,
        region: Optional[str] = None,
        provider_type: Optional[str] = None,
        secrets: Optional[dict] = None,
        settings: Optional[dict] = None,
    ):
        return {
            "id": provider_id,
            "slug": slug or self._denormalize_provider_id(provider_id),
            "title": title,
            "pill": pill or (provider_id[:3].upper() if provider_id else "PRV"),
            "status": status,
            "iconClass": icon_class or self._derive_icon(provider_id),
            "service": service or provider_id,
            "region": region,
            "type": provider_type or service or slug or provider_id,
            "secrets": secrets or {},
            "settings": settings or {},
        }

    def _persist_provider_metadata(self, provider_id: str):
        provider = self._providers.get(provider_id)
        if not provider:
            return
        slug = provider.get("slug") or self._denormalize_provider_id(provider_id)
        models_payload = self._models_payload_for_storage(provider_id)
        try:
            print(
                "[chat] persist_provider",
                "provider_id",
                provider_id,
                "models_list",
                self._models.get(provider_id),
                "catalog_entry",
                self._provider_catalog.get(provider_id),
                "payload",
                models_payload,
            )
        except Exception:
            pass
        payload = {
            "slug": slug,
            "title": provider.get("title") or provider_id.capitalize(),
            "service": provider.get("service") or slug,
            "region": provider.get("region"),
            "status": provider.get("status"),
            "pill": provider.get("pill"),
            "iconClass": provider.get("iconClass"),
            "models": models_payload,
            "type": provider.get("type"),
            "secrets": provider.get("secrets"),
            "settings": provider.get("settings"),
        }
        snapshot = self._provider_backend_call("save_provider", arg=payload)
        if snapshot is None and self._storage and hasattr(self._storage, "upsert_provider"):
            try:
                provider_id_db = self._storage.upsert_provider(
                    slug=slug,
                    title=payload.get("title"),
                    service=payload.get("service"),
                    region=payload.get("region"),
                    config={
                        key: payload.get(key)
                        for key in ("status", "pill", "iconClass", "models", "type", "secrets", "settings")
                        if payload.get(key) is not None
                    },
                )
                secrets = payload.get("secrets") or {}
                if secrets and hasattr(self._storage, "set_provider_secret"):
                    for key_name, key_value in secrets.items():
                        try:
                            self._storage.set_provider_secret(provider_id_db, key_name=key_name, key_value=key_value)
                        except Exception:
                            pass
                catalog = {}
                try:
                    catalog = self._storage.provider_catalog()
                except Exception:
                    catalog = {}
                providers = []
                if hasattr(self._storage, "list_providers"):
                    try:
                        providers = [
                            {
                                "slug": record.slug,
                                "title": record.title,
                                "service": record.service,
                                "region": record.region,
                                "config": record.config,
                            }
                            for record in (self._storage.list_providers() or [])
                        ]
                    except Exception:
                        providers = []
                snapshot = {"catalog": catalog, "providers": providers}
            except Exception as exc:  # pragma: no cover - diagnostics only
                self._log(logging.WARNING, f"Unable to persist provider '{provider_id}' locally: {exc}")
        if not snapshot:
            self._log(logging.WARNING, f"Backend did not return provider snapshot after saving '{provider_id}'")
            return
        updated = self._apply_snapshot(snapshot)
        if updated:
            self._providers = updated
            self._log(logging.INFO, f"Provider '{provider_id}' saved via backend")
            self._update_chat_models()
        else:
            self._log(logging.WARNING, f"Backend snapshot missing provider data after saving '{provider_id}'")
        return snapshot

    def _provider_backend_call(self, method, arg=None):
        if not self._provider_backend:
            self._log(logging.WARNING, f"Provider backend unavailable for '{method}'")
            return None
        try:
            fn = getattr(self._provider_backend, method)
        except Exception as exc:
            self._log(logging.WARNING, f"Backend method '{method}' missing: {exc}")
            return None
        try:
            result = fn(arg) if arg is not None else fn()
            if method.startswith("save") or method.startswith("delete"):
                self._log(logging.INFO, f"Backend call '{method}' ok")
            return result
        except Exception as exc:
            self._log(logging.WARNING, f"Backend call '{method}' failed: {exc}")
            return None

    def _model_groups_for_provider(self, provider_id: str):
        entry = self._provider_catalog.get(provider_id)
        if not isinstance(entry, dict):
            return []
        groups = [key for key, value in entry.items() if isinstance(value, (list, tuple, set))]
        if "custom" not in groups:
            groups.append("custom")
        return groups

    def _append_model_to_catalog(self, provider_id: str, model_name: str, group: Optional[str] = None):
        entry = self._provider_catalog.get(provider_id)
        if group and not isinstance(entry, dict):
            entry = {}
        if isinstance(entry, dict):
            target_group = (group or "custom").strip() or "custom"
            models = entry.get(target_group)
            if not isinstance(models, list):
                models = []
            if model_name not in models:
                models.append(model_name)
            entry[target_group] = models
            try:
                print(
                    f"[chat] append_model provider={provider_id} group={target_group} "
                    f"model_name={model_name} models={entry[target_group]}"
                )
            except Exception:
                pass
        else:
            if not isinstance(entry, list):
                entry = []
            if model_name not in entry:
                entry.append(model_name)
        self._provider_catalog[provider_id] = entry

    def _models_payload_for_storage(self, provider_id: str):
        entry = self._provider_catalog.get(provider_id)
        models_list = self._models.get(provider_id, [])
        if isinstance(entry, dict):
            # Ensure any models in the flat list are represented; drop into 'custom' group.
            flat = set()
            for vals in entry.values():
                if isinstance(vals, (list, tuple, set)):
                    flat.update(vals)
            missing = [m for m in models_list if isinstance(m, str) and m not in flat]
            if missing:
                entry.setdefault("custom", [])
                for m in missing:
                    if m not in entry["custom"]:
                        entry["custom"].append(m)
            return entry
        if entry:
            return entry
        return models_list

    def _build_initial_models(self, catalog):
        models = {}
        for provider_id, provider_models in catalog.items():
            flattened = []
            if isinstance(provider_models, dict):
                for entry in provider_models.values():
                    if isinstance(entry, (list, tuple, set)):
                        flattened.extend([model for model in entry if isinstance(model, str)])
            elif isinstance(provider_models, (list, tuple, set)):
                flattened.extend([model for model in provider_models if isinstance(model, str)])
            if flattened:
                models[provider_id] = flattened
        return models

    def _ensure_provider_entry(self, provider_id):
        if provider_id in self._providers:
            return
        schema_key = self._denormalize_provider_id(provider_id)
        self._providers[provider_id] = self._build_provider_entry(
            provider_id=provider_id,
            title=provider_id.capitalize(),
            status="Healthy",
            provider_type=schema_key,
            secrets=self._default_secrets_for(schema_key),
        )

    def _build_admin_panel(self, container_layout):
        provider_cards = CardPanelConfig(
            title="Model Providers",
            description="Add or select a provider to manage its models.",
            add_button_text="Add Provider",
            viewport_height=CARD_SECTION_VIEWPORT,
            card_columns=max(5, len(self._providers)),
            card_min_height=120,
            card_height=150,
            card_gap=12,
            card_template={
                "class": "card-card provider-card",
                "children": [
                    {
                        "class": "card-head",
                        "children": [
                            {
                                "class": "card-icon",
                                "html": "<i class='mdi {extra.iconClass}' aria-hidden='true'></i>",
                            },
                            {
                                "children": [
                                    {"tag": "h3", "class": "card-title", "text": "{title}"},
                                    {"tag": "p", "class": "card-sub", "text": "{subtitle}"},
                                    {"tag": "span", "class": "card-status-pill", "text": "{extra.status}"},
                                ]
                            },
                        ],
                    },
                    {
                        "class": "card-foot",
                        "children": [
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Select",
                                "attrs": {"data-card-action": "select"},
                            },
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Edit",
                                "attrs": {"data-card-action": "edit"},
                            },
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Delete",
                                "attrs": {"data-card-action": "delete"},
                            },
                        ],
                    },
                ],
            },
            cards=self._provider_cards(),
        )
        self._provider_cards_widget = container_layout.add_cardpanel("provider_cards", provider_cards)
        self._provider_cards_widget.on_card_click(self._handle_provider_selection)
        self._provider_cards_widget.on_action(self._handle_provider_card_action)
        self._provider_cards_widget.on_add(lambda: self._show_provider_modal())

        model_cards = CardPanelConfig(
            title="Provider Models",
            description="Models available for the selected provider.",
            add_button_text="Add Model",
            card_columns=4,
            card_min_height=110,
            card_height=130,
            card_gap=10,
            viewport_height="220px",
            cards=self._model_cards(),
            card_template={
                "class": "card-card model-card",
                "children": [
                    {
                        "class": "card-head",
                        "children": [
                            {
                                "class": "card-icon",
                                "html": "<i class='mdi {extra.iconClass}' aria-hidden='true'></i>",
                            },
                            {
                                "children": [
                                    {"tag": "h3", "class": "card-title", "text": "{title}"},
                                    {"tag": "p", "class": "card-sub", "text": "{subtitle}"},
                                ]
                            },
                        ],
                    },
                    {
                        "class": "card-foot",
                        "children": [
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Delete",
                                "attrs": {"data-card-action": "delete"},
                            },
                        ],
                    },
                ],
            },
        )
        self._model_cards_widget = container_layout.add_cardpanel("provider_models", model_cards)
        self._model_cards_widget.on_add(lambda: self._show_model_modal())
        self._model_cards_widget.on_action(self._handle_model_card_action)
        self._refresh_model_cards()

    def _build_users_panel(self, container_layout):
        user_cards = CardPanelConfig(
            title="Workspace Users",
            description="Manage user access to providers and models.",
            add_button_text="Add User",
            card_columns=4,
            viewport_height=CARD_SECTION_VIEWPORT,
            card_min_height=130,
            card_template={
                "class": "card-card",
                "children": [
                    {"class": "card-head", "children": [
                        {"class": "card-icon", "text": "{title[:1]}"},
                            {
                                "children": [
                                    {"tag": "h3", "class": "card-title", "text": "{title}"},
                                    {"tag": "p", "class": "card-sub", "text": "{extra.details}"},
                                ]
                            },
                    ]},
                    {
                        "class": "card-foot",
                        "children": [
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Select",
                                "attrs": {"data-card-action": "select"},
                            },
                            {
                                "tag": "button",
                                "class": "card-action",
                                "text": "Edit",
                                "attrs": {"data-card-action": "edit"},
                            },
                        ],
                    },
                ],
            },
            cards=self._user_cards(),
        )
        users_widget = container_layout.add_cardpanel("user_list", user_cards)
        users_widget.on_card_click(self._handle_user_selection)
        users_widget.on_action(self._handle_user_card_action)
        users_widget.on_add(lambda: self._show_user_modal())
        self._users_widget = users_widget

        board_config = ResourceBoardConfig(
            title="Provider Access",
            empty_state="Select a user to manage provider and model access.",
            items=self._user_access_items(),
            selected_id=self._active_user_provider,
            detail_template="""
                <div class="provider-detail">
                    <div class="provider-detail-head">
                        <div>
                            <h2>{title}</h2>
                            <p class="provider-detail-sub">{subtitle}</p>
                        </div>
                        <div class="provider-detail-actions">
                            <span class="provider-detail-status">{status}</span>
                            <button class="rb-secondary" data-rb-action="toggle-provider" data-provider-id="{id}">{toggleLabel}</button>
                        </div>
                    </div>
                    <div class="provider-detail-body">
                        <strong>Models</strong>
                        <div class="provider-detail-models">{modelsHtml}</div>
                    </div>
                </div>
            """,
        )
        self._user_access_board = container_layout.add_resourceboard("user_access", board_config)
        self._user_access_board.on_select(self._handle_user_access_selection)
        self._user_access_board.on_action(self._handle_user_access_action)
        self._refresh_user_access_board()

    def _provider_cards(self):
        cards = []
        for provider_id, provider in self._providers.items():
            model_count = len(self._models.get(provider_id, []))
            suffix = "model" if model_count == 1 else "models"
            cards.append(
                CardPanelCardConfig(
                    id=provider_id,
                    title=provider["title"],
                    subtitle=f"{model_count} {suffix}",
                    pill=provider["pill"],
                    extra={
                        "details": f"{provider['status']} - {model_count} {suffix}",
                        "status": provider["status"],
                        "iconClass": provider.get("iconClass", "mdi-view-grid"),
                    },
                )
            )
        return cards

    def _model_cards(self):
        if not self._active_provider or self._active_provider not in self._providers:
            return []
        provider = self._providers[self._active_provider]
        models = self._models.get(self._active_provider, [])
        subtitles = []
        for model_id in models:
            group = self._model_group_for_model(self._active_provider, model_id)
            subtitle_parts = [provider["title"]]
            if group:
                subtitle_parts.append(group.replace("_", " ").title())
            subtitle_parts.append(provider["status"])
            subtitles.append(" - ".join(part for part in subtitle_parts if part))
        return [
            CardPanelCardConfig(
                id=f"{self._active_provider}:{model_id}",
                title=model_id,
                subtitle=subtitles[idx] if idx < len(subtitles) else f"{provider['title']} - {provider['status']}",
                extra={"iconClass": provider.get("iconClass", "mdi-chip")},
            )
            for idx, model_id in enumerate(models)
        ]

    def _model_group_for_model(self, provider_id: str, model_name: str) -> Optional[str]:
        catalog_entry = self._provider_catalog.get(provider_id)
        if not isinstance(catalog_entry, dict):
            return None
        for group, entries in catalog_entry.items():
            if isinstance(entries, (list, tuple, set)) and model_name in entries:
                return group
        return None

    def _refresh_provider_cards(self):
        if self._provider_cards_widget:
            self._provider_cards_widget.load(self._provider_cards())

    def _refresh_model_cards(self):
        if self._model_cards_widget:
            self._model_cards_widget.load(self._model_cards())

    def _handle_provider_card_action(self, payload):
        payload = payload or {}
        provider_id = payload.get("cardId")
        action = payload.get("action")
        if action == "edit":
            provider = self._providers.get(provider_id)
            if provider:
                self._show_provider_modal(provider)
            return
        if action == "delete":
            self._delete_provider(provider_id)
            return
        if provider_id:
            self._handle_provider_selection(provider_id)

    def _handle_provider_selection(self, payload):
        provider_id = payload
        if isinstance(payload, dict):
            provider_id = payload.get("cardId") or payload.get("id")
        if not provider_id or provider_id not in self._providers:
            return
        self._active_provider = provider_id
        self._refresh_model_cards()

    def _load_models(self, provider_id):
        # models already stored in self._models; refreshing board detail is enough
        if provider_id:
            self._active_provider = provider_id
        self._refresh_provider_cards()
        self._refresh_model_cards()
        self._refresh_user_access_board(select_provider=provider_id)
        self._update_chat_models()

    def _derive_icon(self, provider_id: str) -> str:
        if not provider_id:
            return "mdi-view-grid"
        first = provider_id[0].lower()
        if "a" <= first <= "z":
            return f"mdi-alpha-{first}-circle"
        return "mdi-view-grid"

    def _show_provider_modal(self, provider=None):
        self._provider_modal.set_title("Add Provider" if provider is None else f"Edit {provider['id']}")
        provider_type = (provider or {}).get("type") or (provider or {}).get("slug") or "openai"
        provider_slug = (provider or {}).get("slug") or self._denormalize_provider_id((provider or {}).get("id", ""))
        secrets_prefill = (provider or {}).get("secrets") or {}

        # Build the type dropdown and secret templates from schemas
        schema_options = []
        secret_templates = []
        for slug, schema in self._provider_schemas.items():
            option_selected = " selected" if slug == provider_type else ""
            service_value = schema.get("service") or slug
            region_value = schema.get("region") or ""
            title_value = schema.get("title") or slug.title()
            schema_options.append(
                f"<option value=\"{slug}\" data-service=\"{service_value}\" data-region=\"{region_value}\"{option_selected}>{title_value}</option>"
            )
            secrets = DEFAULT_PROVIDER_SECRETS.get(slug, {})
            fields = []
            if secrets:
                for key_name, env_var in secrets.items():
                    existing_value = secrets_prefill.get(key_name, env_var) if slug == provider_type else env_var
                    fields.append(
                        f"<label>Secret name for {key_name}"
                        f"<input name=\"secret_{key_name}\" data-secret-name=\"{key_name}\" type=\"text\" "
                        f"style=\"width:100%;padding:8px;\" value=\"{existing_value}\" placeholder=\"{env_var}\" />"
                        f"</label>"
                    )
            else:
                fields.append("<p class=\"provider-secret-hint\">No secrets required for this provider.</p>")
            secret_templates.append(f"<template data-provider=\"{slug}\">{''.join(fields)}</template>")

        form_html = f"""
        <form id="provider-form" style="display:flex;flex-direction:column;gap:12px;">
            <label>Provider Type
                <select name="provider_type" id="provider_type" style="width:100%;padding:8px;">
                    {''.join(schema_options)}
                </select>
            </label>
            <label>Provider ID
                <input name="provider_id" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Service Slug
                <input name="provider_slug" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Service Name
                <input name="provider_service" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Region (optional)
                <input name="provider_region" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Title
                <input name="provider_title" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Status
                <input name="provider_status" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Pill (label text)
                <input name="provider_pill" type="text" style="width:100%;padding:8px;" placeholder="e.g. OpenAI" />
            </label>
            <label>Icon class (mdi-*)
                <input name="provider_icon" type="text" style="width:100%;padding:8px;" placeholder="e.g. mdi-robot-excited" />
            </label>
            <div style="padding:8px 0;">
                <strong>Secret names</strong>
                <p style="margin:4px 0 8px 0;color:#cbd5e1;font-size:12px;">Enter the environment variable names that hold each secret. Values are read from the environment at runtime.</p>
                <div id="provider-secrets"></div>
                <div id="provider-secrets-templates" style="display:none;">{''.join(secret_templates)}</div>
            </div>
            <div style="display:flex;justify-content:flex-end;gap:8px;">
                <button type="button" id="cancel-provider" style="padding:8px 12px;">Cancel</button>
                <button type="submit" style="padding:8px 12px;background:#2563eb;color:#fff;border:none;border-radius:8px;">Save</button>
            </div>
        </form>
        """
        self._provider_modal_layout.attach_html("provider_form", form_html)

        form = js.document.getElementById("provider-form")
        cancel = js.document.getElementById("cancel-provider")
        secrets_container = js.document.getElementById("provider-secrets")
        secrets_templates = js.document.getElementById("provider-secrets-templates")

        if provider:
            form.provider_id.value = provider["id"]
            form.provider_id.disabled = True
            form.provider_title.value = provider.get("title") or ""
            form.provider_status.value = provider.get("status") or "Healthy"
            form.provider_slug.value = provider_slug or provider["slug"]
            form.provider_service.value = provider.get("service") or provider_slug or provider["id"]
            form.provider_region.value = provider.get("region") or provider.get("settings", {}).get("region") or ""
            form.provider_pill.value = provider.get("pill") or ""
            form.provider_icon.value = provider.get("iconClass") or ""
        else:
            form.provider_slug.value = provider_slug or ""
            form.provider_service.value = ""
            form.provider_region.value = self._provider_schemas.get(provider_type, {}).get("region") or ""

        def render_secrets(provider_slug):
            if not secrets_container or not secrets_templates:
                return
            secrets_container.innerHTML = ""
            template = secrets_templates.querySelector(f"template[data-provider='{provider_slug}']")
            if template and template.content:
                secrets_container.appendChild(template.content.cloneNode(True))

        def on_type_change(event):
            option = event.target.options.item(event.target.selectedIndex)
            provider_slug_value = option.getAttribute("data-service") or option.value
            default_region = option.getAttribute("data-region") or ""
            if not form.provider_slug.value:
                form.provider_slug.value = provider_slug_value
            if not form.provider_service.value:
                form.provider_service.value = provider_slug_value
            if not form.provider_region.value and default_region:
                form.provider_region.value = default_region
            render_secrets(option.value)

        form.provider_type.addEventListener("change", create_proxy(on_type_change))
        render_secrets(provider_type)

        def submit_handler(event):
            event.preventDefault()
            payload = {
                "id": form.provider_id.value.strip(),
                "title": form.provider_title.value.strip(),
                "status": form.provider_status.value.strip() or "Healthy",
                "type": form.provider_type.value.strip() or provider_type,
                "slug": form.provider_slug.value.strip(),
                "service": form.provider_service.value.strip(),
                "region": form.provider_region.value.strip(),
                "pill": form.provider_pill.value.strip(),
                "iconClass": form.provider_icon.value.strip(),
            }
            if not payload["id"]:
                return
            existing = self._providers.get(payload["id"], {})
            slug = payload["slug"] or existing.get("slug") or self._denormalize_provider_id(payload["id"])
            service = payload["service"] or existing.get("service") or slug
            region = payload["region"] or existing.get("region") or self._provider_schemas.get(payload["type"], {}).get("region")
            icon_class = existing.get("iconClass")
            pill = existing.get("pill")
            secrets = {}
            secret_inputs = form.querySelectorAll("[data-secret-name]") if hasattr(form, "querySelectorAll") else []
            try:
                for field in secret_inputs or []:
                    key_name = field.getAttribute("data-secret-name")
                    value = field.value.strip()
                    if key_name and value:
                        secrets[key_name] = value
            except Exception:
                pass
            settings = existing.get("settings", {}).copy() if isinstance(existing.get("settings"), dict) else {}
            if region:
                settings["region"] = region
            self._providers[payload["id"]] = self._build_provider_entry(
                provider_id=payload["id"],
                title=payload["title"] or payload["id"],
                status=payload["status"],
                slug=slug,
                service=service,
                region=region,
                icon_class=payload["iconClass"] or icon_class,
                pill=payload["pill"] or pill,
                provider_type=payload["type"],
                secrets=secrets or self._default_secrets_for(payload["type"]),
                settings=settings,
            )
            self._active_provider = payload["id"]
            if payload["id"] not in self._provider_catalog or not self._provider_catalog.get(payload["id"]):
                default_models = self._default_models_for_provider(payload["type"])
                if default_models:
                    self._provider_catalog[payload["id"]] = default_models
                    seeded = self._build_initial_models({payload["id"]: default_models})
                    if seeded.get(payload["id"]):
                        self._models[payload["id"]] = seeded[payload["id"]]
            self._models.setdefault(payload["id"], [])
            self._provider_catalog.setdefault(payload["id"], [])
            self._persist_provider_metadata(payload["id"])
            self._refresh_provider_cards()
            self._refresh_model_cards()
            self._refresh_user_access_board(select_provider=payload["id"])
            self._update_chat_models()
            self._provider_modal.hide()

        form.addEventListener("submit", create_proxy(submit_handler))
        cancel.addEventListener("click", create_proxy(lambda *_: self._provider_modal.hide()))
        self._provider_modal.show()

    def _show_model_modal(self):
        if not self._active_provider:
            self._show_provider_modal()
            return
        self._model_modal.set_title(f"Add model to {self._active_provider}")
        model_groups = self._model_groups_for_provider(self._active_provider)
        default_group = "anthropic" if "anthropic" in model_groups else (model_groups[0] if model_groups else None)
        group_select_html = ""
        if model_groups:
            options = []
            for group in model_groups:
                selected_attr = " selected" if group == default_group else ""
                label = group.replace("_", " ").title()
                options.append(f"<option value=\"{group}\"{selected_attr}>{label}</option>")
            group_select_html = f"""
            <label>Model subgroup
                <select name="model_group" id="model_group" style="width:100%;padding:8px;">
                    {''.join(options)}
                </select>
                <p style="margin:4px 0 0;color:#cbd5e1;font-size:12px;">Pick the upstream provider/collection for this model (e.g. Anthropic on Bedrock).</p>
            </label>
            """

        form_html = f"""
        <form id="model-form" style="display:flex;flex-direction:column;gap:12px;">
            <label>Model name
                <input name="model_name" type="text" style="width:100%;padding:8px;" />
            </label>
            {group_select_html}
            <div style="display:flex;justify-content:flex-end;gap:8px;">
                <button type="button" id="cancel-model" style="padding:8px 12px;">Cancel</button>
                <button type="submit" style="padding:8px 12px;background:#2563eb;color:#fff;border:none;border-radius:8px;">Add</button>
            </div>
        </form>
        """
        self._model_modal_layout.attach_html("model_form", form_html)
        form = js.document.getElementById("model-form")
        cancel = js.document.getElementById("cancel-model")

        def submit_handler(event):
            event.preventDefault()
            name = form.model_name.value.strip()
            if not name:
                return
            selected_group = None
            try:
                selected_group = form.model_group.value.strip()
            except Exception:
                selected_group = None
            models = self._models.setdefault(self._active_provider, [])
            if name in models:
                try:
                    js.window.alert(f"Model '{name}' already exists for {self._active_provider}")
                except Exception:
                    pass
                self._log(logging.WARNING, f"Model '{name}' already exists for provider '{self._active_provider}'")
                return
            models.append(name)
            self._append_model_to_catalog(self._active_provider, name, group=selected_group)
            try:
                print(
                    "[chat] model_submit",
                    "provider",
                    self._active_provider,
                    "group",
                    selected_group,
                    "models",
                    self._models.get(self._active_provider),
                    "catalog",
                    self._provider_catalog.get(self._active_provider),
                )
            except Exception:
                pass
            snapshot = self._persist_provider_metadata(self._active_provider)
            saved_ok = True
            if isinstance(snapshot, dict):
                try:
                    catalog_snapshot = snapshot.get("catalog") or self._catalog_from_provider_items(snapshot.get("providers"))
                    normalized_catalog = self._normalize_provider_catalog(catalog_snapshot or {})
                    saved_models = self._build_initial_models(normalized_catalog).get(self._active_provider, [])
                    if name not in (saved_models or []):
                        saved_ok = False
                except Exception:
                    saved_ok = True
            if not saved_ok:
                self._log(
                    logging.WARNING,
                    f"Model '{name}' not confirmed in backend after save for provider '{self._active_provider}'",
                )
                try:
                    js.window.alert(f"Model '{name}' was not confirmed saved for {self._active_provider}. Please try again.")
                except Exception:
                    pass
            self._load_models(self._active_provider)
            self._model_modal.hide()

        form.addEventListener("submit", create_proxy(submit_handler))
        cancel.addEventListener("click", create_proxy(lambda *_: self._model_modal.hide()))
        self._model_modal.show()

    def _ensure_proxy(self):
        if self._openai_proxy is not None:
            return
        if OpenAIProxy is None:
            details = _PROXY_IMPORT_ERROR or "Ensure backend dependencies are installed."
            self._log(logging.WARNING, f"MultiAI proxy class unavailable; backend streaming disabled.\n{details}")
            return
        try:
            self._openai_proxy = OpenAIProxy()
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.ERROR, f"Unable to initialise MultiAI proxy: {exc}\n{_format_exception(exc)}")
            self._openai_proxy = None
        else:
            self._log(logging.INFO, "MultiAI proxy initialised successfully")

    def _init_storage(self):
        if ChatStorage is None:
            self._log(logging.INFO, "ChatStorage dependency unavailable; persistence disabled")
            return None
        try:
            settings = settings_from_env()
            return ChatStorage(settings.database)
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.ERROR, f"Unable to initialise storage: {exc}\n{_format_exception(exc)}")
            return None

    def _load_previous_history(self):
        if not self._storage:
            return
        try:
            records = self._storage.history(self._session_id, limit=HISTORY_LIMIT)
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to load history: {exc}\n{_format_exception(exc)}")
            return
        ordered = list(reversed(records))
        for record in ordered:
            message = self._record_to_message(record)
            if message:
                self._history_buffer.append(message)
        if ordered:
            self._log(logging.INFO, f"Loaded {len(ordered)} historical messages for session '{self._session_id}'")
        else:
            self._log(logging.INFO, f"No stored history for session '{self._session_id}'")

    def _record_to_message(self, record):
        try:
            timestamp = record.created_at.isoformat()
        except Exception:  # pragma: no cover
            timestamp = dt.datetime.utcnow().isoformat()
        return ChatMessageConfig(
            role=record.role,
            content=record.content,
            name="BriskChatter" if record.role == "assistant" else None,
            timestamp=timestamp,
        )

    def _persist_message(
        self,
        *,
        role: str,
        content: str,
        model: Optional[str],
        provider: Optional[str],
    ) -> None:
        if not self._storage or not content:
            return
        try:
            self._storage.record_message(
                session_id=self._session_id,
                role=role,
                content=content,
                model=model,
                provider=provider,
            )
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to persist message: {exc}\n{_format_exception(exc)}")

    def _identify_provider(self, model: Optional[str]) -> Optional[str]:
        if not model or not self._openai_proxy:
            return None
        try:
            info = self._openai_proxy.get_model_info(model)
            return info.get("provider")
        except Exception:
            return None

    def _log(self, level: int, message: str) -> None:
        LOGGER.log(level, message)

    def _flatten_model_catalog(self, catalog):
        if not isinstance(catalog, dict) or not catalog:
            catalog = self._default_catalog
        flattened = set()
        for provider_values in catalog.values():
            if isinstance(provider_values, dict):
                for models in provider_values.values():
                    if isinstance(models, (list, tuple, set)):
                        flattened.update(model for model in models if isinstance(model, str))
            elif isinstance(provider_values, (list, tuple, set)):
                flattened.update(model for model in provider_values if isinstance(model, str))
        flattened.add(self._default_model)
        return sorted(flattened)

    def _resolve_selected_model(self):
        if not self._chat_widget or not hasattr(self._chat_widget, "get_chats"):
            return self._default_model
        try:
            chats = self._chat_widget.get_chats()
            active = next((chat for chat in chats if chat.get("isActive")), None)
            if active and active.get("model"):
                return active["model"]
        except Exception as exc:  # pragma: no cover - diagnostics only
            self._log(logging.WARNING, f"Unable to determine active model: {exc}")
        return self._default_model

    def _build_backend_history(self, prompt: str, response_id: str):
        if self._chat_widget and hasattr(self._chat_widget, "build_history"):
            history = self._chat_widget.build_history(
                system_prompt=self._system_prompt,
                exclude_ids={response_id},
            )
        else:
            history = [{"role": "system", "content": self._system_prompt}]
        if not any(msg.get("role") == "user" and msg.get("content") == prompt for msg in history):
            history.append({"role": "user", "content": prompt})
        return history

    async def _stream_backend(self, prompt: str, model: str):
        if not self._chat_widget or not self._openai_proxy:
            return
        self._log(logging.INFO, f"Streaming via backend model '{model}'")
        assistant_message = ChatMessageConfig(
            role="assistant",
            name="BriskChatter",
            content="",
            streaming=True,
        )
        response_id = self._chat_widget.start_stream(assistant_message)
        history = self._build_backend_history(prompt, response_id)
        provider = self._identify_provider(model)
        model_info = None
        try:
            if hasattr(self._openai_proxy, "get_model_info"):
                try:
                    model_info = self._openai_proxy.get_model_info(model)
                    provider = model_info.get("provider") or provider
                except Exception:  # pragma: no cover - diagnostics
                    model_info = None
            self._log(logging.DEBUG, f"Resolved provider '{provider}' for model '{model}'")
            stream = self._openai_proxy.chat_stream(
                history,
                model=model,
            )
            if hasattr(self._chat_widget, "consume_stream"):
                tracked_stream = self._track_stream(stream, model=model, provider=provider)
                self._chat_widget.consume_stream(response_id, tracked_stream)
            else:  # pragma: no cover - fallback path
                collected = []
                async for chunk in stream:
                    text = getattr(chunk, "text", None) or chunk
                    if isinstance(text, str):
                        collected.append(text)
                        self._chat_widget.append_stream(response_id, text)
                self._chat_widget.finish_stream(response_id)
                self._persist_message(
                    role="assistant",
                    content="".join(collected).strip(),
                    model=model,
                    provider=provider,
                )
        except Exception as exc:
            self._chat_widget.append_stream(response_id, f"Backend error: {exc}")
            self._chat_widget.finish_stream(response_id)
            self._log(logging.ERROR, f"Backend streaming error: {exc}\n{_format_exception(exc)}")

    def _track_stream(
        self,
        stream,
        *,
        model=None,
        provider=None,
    ):
        async def generator():
            collected: List[str] = []
            async for chunk in stream:
                text = getattr(chunk, "text", None)
                if isinstance(text, str):
                    collected.append(text)
                elif isinstance(chunk, str):
                    collected.append(chunk)
                yield chunk
            final_text = "".join(collected).strip()
            if final_text:
                self._persist_message(
                    role="assistant",
                    content=final_text,
                    model=model,
                    provider=provider,
                )

        return generator()

    def _user_cards(self):
        return [
            CardPanelCardConfig(
                id=user["id"],
                title=user["name"],
                pill="User",
                extra={"details": f"{len(user['providers'])} providers"},
            )
            for user in self._users.values()
        ]

    def _handle_user_card_action(self, payload):
        user_id = payload.get("cardId")
        action = payload.get("action")
        if not user_id:
            return
        if action == "edit":
            user = self._users.get(user_id)
            if user:
                self._show_user_modal(user)
            return
        self._active_user = user_id
        self._refresh_user_access_board()

    def _handle_user_selection(self, payload):
        user_id = payload.get("cardId")
        if not user_id:
            return
        self._active_user = user_id
        self._refresh_user_access_board()

    def _user_access_items(self):
        if not self._active_user or self._active_user not in self._users:
            return []
        user = self._users[self._active_user]
        items = []
        for provider_id, provider in self._providers.items():
            models = self._models.get(provider_id, [])
            is_enabled = provider_id in user["providers"]
            toggle_label = "Disable Provider" if is_enabled else "Enable Provider"
            models_html = []
            for model_id in models:
                selected = "true" if model_id in user["models"] else "false"
                models_html.append(
                    f"<button class='provider-chip' data-rb-action='toggle-model' "
                    f"data-provider-id='{provider_id}' data-model-id='{model_id}' data-selected='{selected}'>"
                    f"{model_id}</button>"
                )
            if not models_html:
                models_html.append("<span class='provider-empty'>No models yet</span>")
            items.append(
                ResourceItem(
                    id=provider_id,
                    title=provider["title"],
                    subtitle=f"{len(models)} models available - {provider['status']}",
                    status="Enabled" if is_enabled else "Disabled",
                    extra={
                        "modelsHtml": "".join(models_html),
                        "toggleLabel": toggle_label,
                    },
                )
            )
        return items

    def _refresh_user_access_board(self, select_provider: Optional[str] = None):
        if not self._user_access_board:
            return
        items = self._user_access_items()
        self._user_access_board.set_items(items)
        available_ids = []
        for item in items:
            if hasattr(item, "id"):
                available_ids.append(item.id)
            elif isinstance(item, dict) and item.get("id"):
                available_ids.append(item["id"])
        target_id = select_provider or self._active_user_provider
        if target_id not in available_ids:
            target_id = available_ids[0] if available_ids else None
        self._active_user_provider = target_id
        self._user_access_board.select(target_id)

    def _handle_user_access_selection(self, payload):
        if not payload:
            return
        provider_id = payload.get("id")
        if provider_id in self._providers:
            self._active_user_provider = provider_id

    def _handle_user_access_action(self, payload):
        if not payload or not self._active_user or self._active_user not in self._users:
            return
        action = payload.get("action")
        data = payload.get("data") or {}
        provider_id = data.get("providerId") or payload.get("id")
        if not provider_id or provider_id not in self._providers:
            return
        user = self._users[self._active_user]
        if action == "toggle-provider":
            if provider_id in user["providers"]:
                user["providers"].discard(provider_id)
                user["models"] = {model for model in user["models"] if model not in self._models.get(provider_id, [])}
            else:
                user["providers"].add(provider_id)
            self._users_widget.load(self._user_cards())
            self._refresh_user_access_board(select_provider=provider_id)
            return
        if action == "toggle-model":
            model_id = data.get("modelId")
            if not model_id:
                return
            if provider_id not in user["providers"]:
                user["providers"].add(provider_id)
            if model_id in user["models"]:
                user["models"].remove(model_id)
            else:
                user["models"].add(model_id)
            self._users_widget.load(self._user_cards())
            self._refresh_user_access_board(select_provider=provider_id)

    def _handle_model_card_action(self, payload):
        payload = payload or {}
        card_id = payload.get("cardId") or payload.get("id")
        action = payload.get("action")
        if action != "delete" or not card_id or ":" not in card_id:
            return
        provider_id, model_id = card_id.split(":", 1)
        if provider_id not in self._providers:
            return
        models = self._models.get(provider_id, [])
        if model_id in models:
            self._models[provider_id] = [m for m in models if m != model_id]
        entry = self._provider_catalog.get(provider_id)
        if isinstance(entry, dict):
            for key in list(entry.keys()):
                bucket = entry.get(key)
                if isinstance(bucket, list) and model_id in bucket:
                    entry[key] = [m for m in bucket if m != model_id]
            entry["custom"] = [m for m in entry.get("custom", []) if m != model_id]
        elif isinstance(entry, list):
            self._provider_catalog[provider_id] = [m for m in entry if m != model_id]
        for user in self._users.values():
            if model_id in user.get("models", set()):
                user["models"].discard(model_id)
        self._persist_provider_metadata(provider_id)
        self._load_models(provider_id)
        # After deletion, if provider has no models and was selected for deletion, allow provider removal
        if not self._models.get(provider_id):
            self._refresh_provider_cards()

    def _show_user_modal(self, user=None):
        self._user_modal.set_title("Add User" if user is None else f"Edit {user['id']}")
        form_html = """
        <form id="user-form" style="display:flex;flex-direction:column;gap:12px;">
            <label>User ID
                <input name="user_id" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Name
                <input name="user_name" type="text" style="width:100%;padding:8px;" />
            </label>
            <div style="display:flex;justify-content:flex-end;gap:8px;">
                <button type="button" id="cancel-user" style="padding:8px 12px;">Cancel</button>
                <button type="submit" style="padding:8px 12px;background:#2563eb;color:#fff;border:none;border-radius:8px;">Save</button>
            </div>
        </form>
        """
        self._user_modal_layout.attach_html("user_form", form_html)
        form = js.document.getElementById("user-form")
        cancel = js.document.getElementById("cancel-user")
        if user:
            form.user_id.value = user["id"]
            form.user_id.disabled = True
            form.user_name.value = user["name"]

        def submit_handler(event):
            event.preventDefault()
            payload = {
                "id": form.user_id.value.strip(),
                "name": form.user_name.value.strip() or form.user_id.value.strip(),
            }
            if not payload["id"]:
                return
            record = self._users.setdefault(payload["id"], {"providers": set(), "models": set()})
            record.update({"id": payload["id"], "name": payload["name"]})
            if "providers" not in record:
                record["providers"] = set()
            if "models" not in record:
                record["models"] = set()
            self._users_widget.load(self._user_cards())
            self._active_user = payload["id"]
            self._refresh_user_access_board()
            self._user_modal.hide()

        form.addEventListener("submit", create_proxy(submit_handler))
        cancel.addEventListener("click", create_proxy(lambda *_: self._user_modal.hide()))
        self._user_modal.show()

    def handle_send(self, payload):
        """
        Echo the inbound prompt locally or forward it to the backend proxy when available.
        """
        if not payload or not self._chat_widget:
            return
        prompt = payload.get("text", "").strip()
        if not prompt:
            return
        selected_model = self._resolve_selected_model()
        user_msg = ChatMessageConfig(
            role="user",
            content=prompt,
            timestamp=dt.datetime.utcnow().isoformat(),
        )
        self._chat_widget.add_message(user_msg)
        self._persist_message(
            role="user",
            content=prompt,
            model=selected_model,
            provider=self._identify_provider(selected_model),
        )
        if self._openai_proxy:
            self._log(logging.INFO, f"Dispatching prompt via backend model '{selected_model}'")
            asyncio.ensure_future(self._stream_backend(prompt, selected_model))
        else:
            self._log(logging.INFO, "Backend proxy unavailable; using local echo responder")
            asyncio.ensure_future(self._stream_response(prompt, selected_model))

    async def _stream_response(self, prompt: str, model: str):
        self._log(logging.INFO, "Starting local echo response stream")
        streaming_id = self._chat_widget.start_stream(
            ChatMessageConfig(role="assistant", content="", streaming=True)
        )
        for chunk in f"You said: {prompt}".split():
            await asyncio.sleep(0.15)
            self._chat_widget.append_stream(streaming_id, f"{chunk} ")
        closing_text = "\nReady for the next prompt."
        self._chat_widget.finish_stream(streaming_id, closing_text)
        self._persist_message(
            role="assistant",
            content=f"You said: {prompt} {closing_text}",
            model=model,
            provider="local",
        )
        self._log(logging.INFO, "Local echo response completed")

def _format_exception(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


if __name__ == "__main__" and sys.platform != "emscripten":
    from pytincture import launch_service

    launch_service(modules_folder=str(Path(__file__).resolve().parent))
