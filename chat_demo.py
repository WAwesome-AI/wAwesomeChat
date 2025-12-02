import asyncio
import datetime as dt
import os
import sys
from typing import Any, Optional

import js
from pyodide.ffi import create_proxy

from wapyt.cardpanel import CardPanelConfig, CardPanelCardConfig
from wapyt.chat import ChatConfig, ChatAgentConfig, ChatMessageConfig
from wapyt.layout import MainWindow, Layout, LayoutConfig, CellConfig
from wapyt.modal import ModalWindow, ModalConfig
from wapyt.resourceboard import ResourceBoardConfig, ResourceItem
from wapyt.tabwidget import TabWidgetConfig, TabConfig

try:
    from .multiaiproxy import multiaiproxy as OpenAIProxy
except ImportError:  # pragma: no cover - fallback for direct execution
    try:
        from wapyt.tests.multiaiproxy import multiaiproxy as OpenAIProxy
    except Exception:  # pragma: no cover - environment without proxy
        OpenAIProxy = None


SYSTEM_PROMPT = (
    "You are Atlas, a helpful workspace assistant. Provide concise, accurate answers and highlight "
    "follow-up steps when useful."
)

CARD_SECTION_VIEWPORT = "220px"


class chat_demo(MainWindow):
    layout_config = LayoutConfig(rows=[CellConfig(id="tabs", grow=1)])

    def __init__(self):
        super().__init__()
        self._chat_widget = None
        self._providers = {
            "aws": {"id": "aws", "title": "AWS Bedrock", "pill": "AWS", "status": "Healthy", "iconClass": "mdi-aws"},
            "anthropic": {"id": "anthropic", "title": "Anthropic", "pill": "Anthropic", "status": "Limited", "iconClass": "mdi-brain"},
            "openai": {"id": "openai", "title": "OpenAI", "pill": "OpenAI", "status": "Healthy", "iconClass": "mdi-robot-excited"},
            "google": {"id": "google", "title": "Google Vertex", "pill": "Google", "status": "Preview", "iconClass": "mdi-google"},
            "xai": {"id": "xai", "title": "xAI Grok", "pill": "xAI", "status": "Healthy", "iconClass": "mdi-alpha-x-circle"},
        }
        self._models = {
            "aws": ["us.anthropic.claude-sonnet-4", "us.amazon.nova-pro-v1"],
            "anthropic": ["claude-3-7-sonnet", "claude-3-5-sonnet"],
            "openai": ["gpt-4o-mini", "gpt-4.1"],
            "google": ["gemini-1.5-flash", "gemini-1.5-pro"],
            "xai": ["grok-3-beta"],
        }
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
        self._provider_modal = ModalWindow(ModalConfig(title="Add Provider", width=540, height=380))
        self._model_modal = ModalWindow(ModalConfig(title="Add Model", width=480, height=320))
        self._user_modal = ModalWindow(ModalConfig(title="Add User", width=460, height=320))
        self._provider_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="provider_form", grow=1)], borderless=True, gap="0px"))
        self._model_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="model_form", grow=1)], borderless=True, gap="0px"))
        self._user_modal_layout = Layout(LayoutConfig(rows=[CellConfig(id="user_form", grow=1)], borderless=True, gap="0px"))
        self._provider_modal.set_content(self._provider_modal_layout.layout)
        self._model_modal.set_content(self._model_modal_layout.layout)
        self._user_modal.set_content(self._user_modal_layout.layout)
        self._openai_proxy: Optional[Any] = None  # type: ignore[name-defined]
        self._system_prompt = SYSTEM_PROMPT
        self._default_model = os.getenv("CHAT_DEMO_DEFAULT_MODEL", "gpt-4o-mini")
        self._available_models = [self._default_model]
        self._provider_catalog = {}
        self._provider_cards_widget = None
        self._model_cards_widget = None
        self._user_access_board = None
        self._active_user_provider = None
        self.set_theme("dark")

    def load_ui(self):
        agent = ChatAgentConfig(
            name="Atlas",
            tagline="Wapyt-native assistant",
            avatar="https://avatars.githubusercontent.com/u/6344670?v=4",
        )
        welcome = ChatMessageConfig(
            role="assistant",
            content="Welcome to the wapyt chat demo. Ask me anything!",
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
        provider_catalog = {}
        available_models = list(self._available_models)
        if self._openai_proxy:
            try:
                provider_catalog = self._openai_proxy.get_available_models() or {}
                flattened = self._flatten_model_catalog(provider_catalog)
                if flattened:
                    available_models = flattened
            except Exception as exc:  # pragma: no cover - diagnostics only
                print(f"[chat_demo] Unable to load provider catalog: {exc}")
        self._available_models = available_models
        self._provider_catalog = provider_catalog
        chat_extra = {"models": available_models}
        if provider_catalog:
            chat_extra["providerConfig"] = {"providers": provider_catalog}
        self._chat_widget = chat_layout.add_chat(
            "chat_body",
            ChatConfig(
                agent=agent,
                messages=[welcome],
                storage_key="wapyt_chat_demo",
                layout_mode="advanced",
                layout_density="comfortable",
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
                ],
            },
        )
        self._model_cards_widget = container_layout.add_cardpanel("provider_models", model_cards)
        self._model_cards_widget.on_add(lambda: self._show_model_modal())
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
        return [
            CardPanelCardConfig(
                id=f"{self._active_provider}:{model_id}",
                title=model_id,
                subtitle=f"{provider['title']} - {provider['status']}",
                extra={"iconClass": provider.get("iconClass", "mdi-chip")},
            )
            for model_id in models
        ]

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

    def _derive_icon(self, provider_id: str) -> str:
        if not provider_id:
            return "mdi-view-grid"
        first = provider_id[0].lower()
        if "a" <= first <= "z":
            return f"mdi-alpha-{first}-circle"
        return "mdi-view-grid"

    def _show_provider_modal(self, provider=None):
        self._provider_modal.set_title("Add Provider" if provider is None else f"Edit {provider['id']}")
        form_html = """
        <form id="provider-form" style="display:flex;flex-direction:column;gap:12px;">
            <label>Provider ID
                <input name="provider_id" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Title
                <input name="provider_title" type="text" style="width:100%;padding:8px;" />
            </label>
            <label>Status
                <input name="provider_status" type="text" style="width:100%;padding:8px;" />
            </label>
            <div style="display:flex;justify-content:flex-end;gap:8px;">
                <button type="button" id="cancel-provider" style="padding:8px 12px;">Cancel</button>
                <button type="submit" style="padding:8px 12px;background:#2563eb;color:#fff;border:none;border-radius:8px;">Save</button>
            </div>
        </form>
        """
        self._provider_modal_layout.attach_html("provider_form", form_html)
        form = js.document.getElementById("provider-form")
        cancel = js.document.getElementById("cancel-provider")
        if provider:
            form.provider_id.value = provider["id"]
            form.provider_id.disabled = True
            form.provider_title.value = provider["title"]
            form.provider_status.value = provider["status"]

        def submit_handler(event):
            event.preventDefault()
            payload = {
                "id": form.provider_id.value.strip(),
                "title": form.provider_title.value.strip(),
                "status": form.provider_status.value.strip() or "Healthy",
            }
            if not payload["id"]:
                return
            self._providers[payload["id"]] = {
                "id": payload["id"],
                "title": payload["title"] or payload["id"],
                "pill": payload["id"].upper(),
                "status": payload["status"],
                "iconClass": self._providers.get(payload["id"], {}).get("iconClass") or self._derive_icon(payload["id"]),
            }
            self._active_provider = payload["id"]
            self._models.setdefault(payload["id"], [])
            self._refresh_provider_cards()
            self._refresh_model_cards()
            self._refresh_user_access_board(select_provider=payload["id"])
            self._provider_modal.hide()

        form.addEventListener("submit", create_proxy(submit_handler))
        cancel.addEventListener("click", create_proxy(lambda *_: self._provider_modal.hide()))
        self._provider_modal.show()

    def _show_model_modal(self):
        if not self._active_provider:
            self._show_provider_modal()
            return
        self._model_modal.set_title(f"Add model to {self._active_provider}")
        form_html = """
        <form id="model-form" style="display:flex;flex-direction:column;gap:12px;">
            <label>Model name
                <input name="model_name" type="text" style="width:100%;padding:8px;" />
            </label>
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
            self._models.setdefault(self._active_provider, []).append(name)
            self._load_models(self._active_provider)
            self._model_modal.hide()

        form.addEventListener("submit", create_proxy(submit_handler))
        cancel.addEventListener("click", create_proxy(lambda *_: self._model_modal.hide()))
        self._model_modal.show()

    def _ensure_proxy(self):
        if self._openai_proxy is not None or OpenAIProxy is None:
            return
        try:
            self._openai_proxy = OpenAIProxy()
        except Exception as exc:  # pragma: no cover - diagnostics only
            print(f"[chat_demo] Unable to initialise MultiAI proxy: {exc}")
            self._openai_proxy = None

    def _flatten_model_catalog(self, catalog):
        if not isinstance(catalog, dict):
            return list(self._available_models)
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
            print(f"[chat_demo] Unable to determine active model: {exc}")
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

    def _stream_backend(self, prompt: str):
        if not self._chat_widget or not self._openai_proxy:
            return
        assistant_message = ChatMessageConfig(
            role="assistant",
            name="Atlas",
            content="",
            streaming=True,
        )
        response_id = self._chat_widget.start_stream(assistant_message)
        history = self._build_backend_history(prompt, response_id)
        try:
            stream = self._openai_proxy.chat_stream(
                history,
                model=self._resolve_selected_model(),
            )
            if hasattr(self._chat_widget, "consume_stream"):
                self._chat_widget.consume_stream(response_id, stream)
            else:  # pragma: no cover - fallback path
                for chunk in stream:
                    text = getattr(chunk, "text", None) or chunk
                    if isinstance(text, str):
                        self._chat_widget.append_stream(response_id, text)
                self._chat_widget.finish_stream(response_id)
        except Exception as exc:
            self._chat_widget.append_stream(response_id, f"Backend error: {exc}")
            self._chat_widget.finish_stream(response_id)

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
        user_msg = ChatMessageConfig(
            role="user",
            content=prompt,
            timestamp=dt.datetime.utcnow().isoformat(),
        )
        self._chat_widget.add_message(user_msg)
        if self._openai_proxy:
            self._stream_backend(prompt)
        else:
            asyncio.ensure_future(self._stream_response(prompt))

    async def _stream_response(self, prompt: str):
        streaming_id = self._chat_widget.start_stream(
            ChatMessageConfig(role="assistant", content="", streaming=True)
        )
        for chunk in f"You said: {prompt}".split():
            await asyncio.sleep(0.15)
            self._chat_widget.append_stream(streaming_id, f"{chunk} ")
        self._chat_widget.finish_stream(streaming_id, "\nReady for the next prompt.")


if __name__ == "__main__" and sys.platform != "emscripten":
    from pytincture import launch_service

    launch_service(modules_folder=".")
