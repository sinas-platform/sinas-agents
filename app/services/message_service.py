"""Message service for chat processing with tool calling."""
import json
import logging
from typing import List, Dict, Any, Optional, AsyncIterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from jinja2 import Template
import jsonschema

from app.models import Chat, Message, Assistant
from app.models.execution import Execution, ExecutionStatus
from app.providers import create_provider
from app.services.webhook_tools import WebhookToolConverter
from app.services.context_tools import ContextTools
from app.services.ontology_tools import OntologyTools
from app.services.mcp import mcp_client
from app.services.execution_engine import executor
from app.core.config import settings

logger = logging.getLogger(__name__)


class MessageService:
    """Service for processing chat messages with LLM and tool calling."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.webhook_converter = WebhookToolConverter()
        self.context_tools = ContextTools()
        self.ontology_tools = OntologyTools()

    async def create_chat_with_assistant(
        self,
        assistant_id: str,
        user_id: str,
        input_data: Dict[str, Any],
        group_id: Optional[str] = None,
        name: Optional[str] = None
    ) -> Chat:
        """
        Create a chat with an assistant using input validation and template rendering.

        Args:
            assistant_id: Assistant to use
            user_id: User ID
            input_data: Input data to validate and use for template rendering
            group_id: Optional group ID
            name: Optional chat name

        Returns:
            Created chat

        Raises:
            ValueError: If input validation fails
        """
        # Get assistant
        result = await self.db.execute(
            select(Assistant).where(Assistant.id == assistant_id)
        )
        assistant = result.scalar_one_or_none()
        if not assistant:
            raise ValueError("Assistant not found")

        # Validate input against assistant's input_schema
        if assistant.input_schema:
            try:
                jsonschema.validate(instance=input_data, schema=assistant.input_schema)
            except jsonschema.ValidationError as e:
                raise ValueError(f"Input validation failed: {e.message}")

        # Create chat
        chat = Chat(
            user_id=user_id,
            group_id=group_id,
            assistant_id=assistant_id,
            title=name or f"Chat with {assistant.name}",
            enabled_webhooks=assistant.enabled_webhooks,
            enabled_mcp_tools=assistant.enabled_mcp_tools,
            enabled_assistants=assistant.enabled_assistants
        )
        self.db.add(chat)
        await self.db.commit()
        await self.db.refresh(chat)

        # Pre-populate with initial_messages if present
        if assistant.initial_messages:
            for msg_data in assistant.initial_messages:
                message = Message(
                    chat_id=chat.id,
                    role=msg_data["role"],
                    content=msg_data["content"]
                )
                self.db.add(message)
            await self.db.commit()

        return chat


    async def _prepare_message_context(
        self,
        chat_id: str,
        user_id: str,
        content: str,
        provider: Optional[str],
        model: Optional[str],
        temperature: float,
        enabled_webhooks: Optional[List[str]],
        disabled_webhooks: Optional[List[str]],
        enabled_mcp_tools: Optional[List[str]],
        disabled_mcp_tools: Optional[List[str]],
        inject_context: bool,
        context_namespaces: Optional[List[str]],
        context_limit: int,
        template_variables: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Prepare message context (shared logic for streaming and non-streaming).

        Returns dict with: chat, user_message, messages, tools, llm_provider,
        provider_name, final_model, final_temperature
        """
        # Get chat
        result = await self.db.execute(
            select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id)
        )
        chat = result.scalar_one_or_none()
        if not chat:
            raise ValueError("Chat not found")

        # Get assistant settings if chat has an assistant
        assistant = None
        if chat.assistant_id:
            from sqlalchemy.orm import joinedload
            result = await self.db.execute(
                select(Assistant)
                .options(joinedload(Assistant.llm_provider))
                .where(Assistant.id == chat.assistant_id)
            )
            assistant = result.scalar_one_or_none()

        # Determine final provider/model/temperature
        # Priority: message params > assistant settings > database default

        # Get provider name (for create_provider call)
        provider_name = None
        if provider:
            provider_name = provider
        elif assistant and assistant.llm_provider_id:
            # Load provider relationship if needed
            if not assistant.llm_provider:
                from app.models import LLMProvider
                result = await self.db.execute(
                    select(LLMProvider).where(LLMProvider.id == assistant.llm_provider_id)
                )
                assistant.llm_provider = result.scalar_one_or_none()
            if assistant.llm_provider:
                provider_name = assistant.llm_provider.name

        # Get model: message param > assistant model > provider default
        final_model = model or (assistant.model if assistant else None)
        if not final_model and assistant and assistant.llm_provider:
            final_model = assistant.llm_provider.default_model

        final_temperature = temperature if temperature != 0.7 else (assistant.temperature if assistant else 0.7)

        # Save user message
        user_message = Message(
            chat_id=chat_id,
            role="user",
            content=content,
            enabled_webhooks=enabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools
        )
        self.db.add(user_message)
        await self.db.commit()
        await self.db.refresh(user_message)

        # Build conversation history
        messages = await self._build_conversation_history(
            chat=chat,
            inject_context=inject_context,
            user_id=user_id,
            context_namespaces=context_namespaces,
            context_limit=context_limit,
            template_variables=template_variables
        )

        # Get available tools
        tools = await self._get_available_tools(
            user_id=user_id,
            chat=chat,
            message_enabled_webhooks=enabled_webhooks,
            message_disabled_webhooks=disabled_webhooks,
            message_enabled_mcp=enabled_mcp_tools,
            message_disabled_mcp=disabled_mcp_tools
        )

        # Create LLM provider
        llm_provider = await create_provider(provider_name, final_model, self.db)

        # If no model specified, use the provider's default model
        if not final_model:
            from app.models import LLMProvider
            # Get the provider config that was used
            if provider_name:
                result = await self.db.execute(
                    select(LLMProvider).where(
                        LLMProvider.name == provider_name,
                        LLMProvider.is_active == True
                    )
                )
            else:
                result = await self.db.execute(
                    select(LLMProvider).where(
                        LLMProvider.is_default == True,
                        LLMProvider.is_active == True
                    )
                )
            provider_config = result.scalar_one_or_none()
            if provider_config:
                final_model = provider_config.default_model

        return {
            "chat": chat,
            "user_message": user_message,
            "messages": messages,
            "tools": tools,
            "llm_provider": llm_provider,
            "provider_name": provider_name,
            "final_model": final_model,
            "final_temperature": final_temperature
        }

    async def send_message(
        self,
        chat_id: str,
        user_id: str,
        user_token: str,
        content: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enabled_webhooks: Optional[List[str]] = None,
        disabled_webhooks: Optional[List[str]] = None,
        enabled_mcp_tools: Optional[List[str]] = None,
        disabled_mcp_tools: Optional[List[str]] = None,
        inject_context: bool = True,
        context_namespaces: Optional[List[str]] = None,
        context_limit: int = 5,
        template_variables: Optional[Dict[str, Any]] = None,
    ) -> Message:
        """Send a message and get LLM response (non-streaming)."""
        # Prepare message context
        prep = await self._prepare_message_context(
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            provider=provider,
            model=model,
            temperature=temperature,
            enabled_webhooks=enabled_webhooks,
            disabled_webhooks=disabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools,
            disabled_mcp_tools=disabled_mcp_tools,
            inject_context=inject_context,
            context_namespaces=context_namespaces,
            context_limit=context_limit,
            template_variables=template_variables
        )

        # Get response from LLM (non-streaming)
        start_time = datetime.now(timezone.utc)
        response = await prep["llm_provider"].complete(
            messages=prep["messages"],
            model=prep["final_model"],
            tools=prep["tools"] if prep["tools"] else None,
            temperature=prep["final_temperature"],
            max_tokens=max_tokens
        )
        end_time = datetime.now(timezone.utc)

        # Log request
        await self._log_request(
            user_id=user_id,
            chat_id=str(chat_id),
            message_id=str(prep["user_message"].id),
            provider=prep["provider_name"],
            model=prep["final_model"],
            messages=prep["messages"],
            response=response,
            latency_ms=int((end_time - start_time).total_seconds() * 1000)
        )

        # Handle tool calls if present
        if response.get("tool_calls"):
            return await self._handle_tool_calls(
                chat_id=chat_id,
                user_id=user_id,
                user_token=user_token,
                messages=prep["messages"],
                tool_calls=response["tool_calls"],
                provider=prep["provider_name"],
                model=prep["final_model"],
                temperature=prep["final_temperature"],
                max_tokens=max_tokens,
                tools=prep["tools"]
            )

        # Save assistant message
        assistant_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=response.get("content", ""),
            enabled_webhooks=enabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools
        )
        self.db.add(assistant_message)
        await self.db.commit()
        await self.db.refresh(assistant_message)

        return assistant_message

    async def send_message_stream(
        self,
        chat_id: str,
        user_id: str,
        user_token: str,
        content: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        enabled_webhooks: Optional[List[str]] = None,
        disabled_webhooks: Optional[List[str]] = None,
        enabled_mcp_tools: Optional[List[str]] = None,
        disabled_mcp_tools: Optional[List[str]] = None,
        inject_context: bool = True,
        context_namespaces: Optional[List[str]] = None,
        context_limit: int = 5,
        template_variables: Optional[Dict[str, Any]] = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Send a message and stream LLM response.

        Yields:
            Dict chunks with response data
        """
        # Prepare message (reuse common logic)
        prep = await self._prepare_message_context(
            chat_id=chat_id,
            user_id=user_id,
            content=content,
            provider=provider,
            model=model,
            temperature=temperature,
            enabled_webhooks=enabled_webhooks,
            disabled_webhooks=disabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools,
            disabled_mcp_tools=disabled_mcp_tools,
            inject_context=inject_context,
            context_namespaces=context_namespaces,
            context_limit=context_limit,
            template_variables=template_variables
        )

        # Stream response
        async for chunk in self._stream_response(
            llm_provider=prep["llm_provider"],
            messages=prep["messages"],
            final_model=prep["final_model"],
            tools=prep["tools"],
            final_temperature=prep["final_temperature"],
            max_tokens=max_tokens,
            chat_id=chat_id,
            user_id=user_id,
            user_token=user_token,
            enabled_webhooks=enabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools,
            provider_name=prep["provider_name"],
        ):
            yield chunk

    async def _stream_response(
        self,
        llm_provider,
        messages: List[Dict[str, Any]],
        final_model: Optional[str],
        tools: Optional[List[Dict[str, Any]]],
        final_temperature: float,
        max_tokens: Optional[int],
        chat_id: str,
        user_id: str,
        user_token: str,
        enabled_webhooks: Optional[List[str]],
        enabled_mcp_tools: Optional[List[str]],
        provider_name: Optional[str],
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream LLM response.

        Yields:
            Dict chunks with response data
        """
        # Stream response
        full_content = ""
        tool_calls_list = []  # Accumulate tool calls by index (OpenAI sends by index)

        async for chunk in llm_provider.stream(
            messages=messages,
            model=final_model,
            tools=tools if tools else None,
            temperature=final_temperature,
            max_tokens=max_tokens
        ):
            if chunk.get("content"):
                full_content += chunk["content"]

            # Accumulate tool calls (streaming sends deltas with index)
            if chunk.get("tool_calls"):
                for tc in chunk["tool_calls"]:
                    # OpenAI sends tool calls with an index property in streaming
                    # First chunk has id/type/name, subsequent chunks have only arguments
                    tc_index = tc.get("index", 0)

                    # Extend list if needed
                    while len(tool_calls_list) <= tc_index:
                        tool_calls_list.append({
                            "id": None,
                            "type": "function",
                            "function": {
                                "name": "",
                                "arguments": ""
                            }
                        })

                    # Update ID, type, name if provided (first chunk)
                    if tc.get("id"):
                        tool_calls_list[tc_index]["id"] = tc["id"]
                    if tc.get("type"):
                        tool_calls_list[tc_index]["type"] = tc["type"]
                    if tc.get("function", {}).get("name"):
                        tool_calls_list[tc_index]["function"]["name"] = tc["function"]["name"]

                    # Accumulate arguments (all chunks)
                    if tc.get("function", {}).get("arguments"):
                        tool_calls_list[tc_index]["function"]["arguments"] += tc["function"]["arguments"]

            yield chunk

        # Use accumulated tool calls
        tool_calls = tool_calls_list if tool_calls_list else []

        # Save assistant message after streaming completes
        assistant_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=full_content if full_content else None,
            tool_calls=tool_calls if tool_calls else None,
            enabled_webhooks=enabled_webhooks,
            enabled_mcp_tools=enabled_mcp_tools
        )
        self.db.add(assistant_message)
        await self.db.commit()

        # Handle tool calls if present
        if tool_calls:
            # Execute tools and get final response (but don't yield it since streaming is done)
            await self._handle_tool_calls(
                chat_id=chat_id,
                user_id=user_id,
                user_token=user_token,
                messages=messages,
                tool_calls=tool_calls,
                provider=provider_name,
                model=final_model,
                temperature=final_temperature,
                max_tokens=max_tokens,
                tools=tools
            )

    async def _build_conversation_history(
        self,
        chat: Chat,
        inject_context: bool = False,
        user_id: Optional[str] = None,
        context_namespaces: Optional[List[str]] = None,
        context_limit: int = 5,
        template_variables: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Build conversation history for LLM with optional context injection.

        Args:
            chat: Chat object
            inject_context: Whether to inject stored context
            user_id: User ID for context retrieval
            context_namespaces: Namespaces to filter context
            context_limit: Max context items to inject
            template_variables: Variables for Jinja2 template rendering in system_prompt

        Returns:
            List of message dicts for LLM
        """
        messages = []

        # Add system prompt from assistant if exists
        system_content = ""
        if chat.assistant_id:
            result = await self.db.execute(
                select(Assistant).where(Assistant.id == chat.assistant_id)
            )
            assistant = result.scalar_one_or_none()
            if assistant and assistant.system_prompt:
                # Render system prompt with Jinja2 if template_variables provided
                if template_variables:
                    try:
                        template = Template(assistant.system_prompt)
                        system_content = template.render(**template_variables)
                    except Exception as e:
                        logger.error(f"Failed to render system prompt template: {e}")
                        system_content = assistant.system_prompt
                else:
                    system_content = assistant.system_prompt

        # Inject relevant context if enabled
        # No assistant = no context injection
        if inject_context and user_id and chat.assistant_id:
            # Determine which namespaces to use:
            # 1. Message-level context_namespaces (most specific)
            # 2. Assistant-level context_namespaces
            final_namespaces = context_namespaces
            if final_namespaces is None:
                result = await self.db.execute(
                    select(Assistant).where(Assistant.id == chat.assistant_id)
                )
                assistant = result.scalar_one_or_none()
                if assistant:
                    final_namespaces = assistant.context_namespaces

            # Context access is opt-in: None or [] means no access
            if final_namespaces is None or len(final_namespaces) == 0:
                # No namespaces = no context injection
                pass
            else:
                relevant_contexts = await ContextTools.get_relevant_contexts(
                    db=self.db,
                    user_id=user_id,
                    assistant_id=str(chat.assistant_id) if chat.assistant_id else None,
                    group_id=str(chat.group_id) if chat.group_id else None,
                    namespaces=final_namespaces,
                    limit=context_limit
                )

                if relevant_contexts:
                    context_section = "\n\n## Stored Context\n"
                    context_section += "The following information has been saved about the user and should inform your responses:\n\n"

                    for ctx in relevant_contexts:
                        context_section += f"**{ctx.namespace}/{ctx.key}**"
                        if ctx.description:
                            context_section += f" - {ctx.description}"
                        context_section += "\n"
                        context_section += f"```json\n{json.dumps(ctx.value, indent=2)}\n```\n\n"

                    if system_content:
                        system_content += context_section
                    else:
                        system_content = context_section.strip()

        if system_content:
            messages.append({
                "role": "system",
                "content": system_content
            })

        # Add chat message history
        result = await self.db.execute(
            select(Message).where(Message.chat_id == chat.id).order_by(Message.created_at)
        )
        chat_messages = result.scalars().all()

        for msg in chat_messages:
            message_dict = {"role": msg.role}

            # Always include content, even if None (required for assistant messages with tool_calls)
            message_dict["content"] = msg.content

            if msg.tool_calls:
                message_dict["tool_calls"] = msg.tool_calls

            if msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id

            if msg.name:
                message_dict["name"] = msg.name

            messages.append(message_dict)

        return messages

    async def _get_assistant_tools(self, assistant_ids: List[str]) -> List[Dict[str, Any]]:
        """Get tool definitions for enabled assistants."""
        tools = []

        for assistant_id in assistant_ids:
            result = await self.db.execute(
                select(Assistant).where(Assistant.id == assistant_id)
            )
            assistant = result.scalar_one_or_none()

            if not assistant or not assistant.is_active:
                continue

            # Build tool definition for this assistant
            tool_def = {
                "type": "function",
                "function": {
                    "name": f"call_assistant_{assistant.name.lower().replace(' ', '_')}",
                    "description": assistant.description or f"Call the {assistant.name} assistant"
                }
            }

            # If assistant has input_schema, use it; otherwise simple string input
            if assistant.input_schema and assistant.input_schema.get("properties"):
                tool_def["function"]["parameters"] = assistant.input_schema
            else:
                # Default: simple prompt/query parameter
                tool_def["function"]["parameters"] = {
                    "type": "object",
                    "properties": {
                        "prompt": {
                            "type": "string",
                            "description": "The prompt or query to send to the assistant"
                        }
                    },
                    "required": ["prompt"]
                }

            tools.append(tool_def)

        return tools

    async def _get_available_tools(
        self,
        user_id: str,
        chat: Chat,
        message_enabled_webhooks: Optional[List[str]],
        message_disabled_webhooks: Optional[List[str]],
        message_enabled_mcp: Optional[List[str]],
        message_disabled_mcp: Optional[List[str]]
    ) -> List[Dict[str, Any]]:
        """Get all available tools (webhooks + MCP + context + ontology + assistants + execution continuation)."""
        tools = []

        # No assistant = no tools
        if not chat.assistant_id:
            return tools

        # Get assistant configuration
        assistant = None
        result = await self.db.execute(
            select(Assistant).where(Assistant.id == chat.assistant_id)
        )
        assistant = result.scalar_one_or_none()
        if not assistant:
            return tools

        # Add context tools (based on assistant's context_namespaces)
        context_tool_defs = await ContextTools.get_tool_definitions(
            db=self.db,
            user_id=user_id,
            assistant_context_namespaces=assistant.context_namespaces
        )
        tools.extend(context_tool_defs)

        # Add ontology tools (filtered by assistant's ontology_namespaces and ontology_concepts)
        ontology_tool_defs = await OntologyTools.get_tool_definitions(
            db=self.db,
            user_id=user_id,
            ontology_namespaces=assistant.ontology_namespaces,
            ontology_concepts=assistant.ontology_concepts
        )
        tools.extend(ontology_tool_defs)

        # Add assistant tools (other assistants this assistant can call)
        assistant_enabled = assistant.enabled_assistants or []
        if assistant_enabled:
            assistant_tools = await self._get_assistant_tools(assistant_enabled)
            tools.extend(assistant_tools)

        # Determine webhook configuration
        # Priority: message override > assistant config
        # Note: Empty list [] means no webhooks, None means all webhooks
        if message_enabled_webhooks is not None:
            webhook_enabled = message_enabled_webhooks
        else:
            webhook_enabled = assistant.enabled_webhooks
        webhook_disabled = message_disabled_webhooks or []

        # Get webhook tools (only if list has items - opt-in)
        if webhook_enabled and len(webhook_enabled) > 0:
            webhook_tools = await self.webhook_converter.get_available_webhooks(
                db=self.db,
                user_id=user_id,
                enabled_webhooks=webhook_enabled,
                disabled_webhooks=webhook_disabled
            )
            tools.extend(webhook_tools)

        # Determine MCP configuration
        # Priority: message override > assistant config
        if message_enabled_mcp is not None:
            mcp_enabled = message_enabled_mcp
        else:
            mcp_enabled = assistant.enabled_mcp_tools

        # Get MCP tools (only if list has items - opt-in)
        if mcp_enabled and len(mcp_enabled) > 0:
            mcp_tools = await mcp_client.get_available_tools(
                enabled_tools=mcp_enabled
            )
            tools.extend(mcp_tools)

        # Check for paused executions belonging to this chat
        result = await self.db.execute(
            select(Execution).where(
                Execution.chat_id == chat.id,
                Execution.status == ExecutionStatus.AWAITING_INPUT
            ).limit(10)
        )
        paused_executions = result.scalars().all()

        if paused_executions:
            # Add continue_execution tool with details about paused executions
            execution_list = "\n".join([
                f"- {ex.execution_id}: {ex.function_name} - {ex.input_prompt}"
                for ex in paused_executions
            ])

            tools.append({
                "type": "function",
                "function": {
                    "name": "continue_execution",
                    "description": f"Continue a paused function execution by providing required input. Currently paused executions:\n{execution_list}",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "execution_id": {
                                "type": "string",
                                "description": "The execution ID to continue",
                                "enum": [ex.execution_id for ex in paused_executions]
                            },
                            "input": {
                                "type": "object",
                                "description": "Input data to provide to the paused execution"
                            }
                        },
                        "required": ["execution_id", "input"]
                    }
                }
            })

        return tools

    async def _execute_assistant_tool(
        self,
        chat: Chat,
        user_id: str,
        user_token: str,
        tool_name: str,
        arguments: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute an assistant tool call by creating a new chat and getting a response."""
        # Extract assistant ID from enabled_assistants based on tool name
        # Tool name format: call_assistant_{name}
        assistant = None
        for assistant_id in chat.enabled_assistants:
            result = await self.db.execute(
                select(Assistant).where(Assistant.id == assistant_id)
            )
            candidate = result.scalar_one_or_none()
            if candidate:
                expected_tool_name = f"call_assistant_{candidate.name.lower().replace(' ', '_')}"
                if expected_tool_name == tool_name:
                    assistant = candidate
                    break

        if not assistant:
            return {"error": f"Assistant not found for tool {tool_name}"}

        # Prepare input data for the assistant
        # If arguments contain just "prompt", send as message content
        # Otherwise, use as input_data for validation
        if "prompt" in arguments and len(arguments) == 1:
            # Simple prompt mode
            input_data = {}
            content = arguments["prompt"]
        else:
            # Structured input mode
            input_data = arguments
            content = json.dumps(arguments)

        # Create a new chat for this assistant call
        try:
            sub_chat = await self.create_chat_with_assistant(
                assistant_id=str(assistant.id),
                user_id=user_id,
                input_data=input_data,
                group_id=str(chat.group_id) if chat.group_id else None,
                name=f"Sub-chat: {assistant.name}"
            )

            # Send message to the assistant
            response_message = await self.send_message(
                chat_id=str(sub_chat.id),
                user_id=user_id,
                user_token=user_token,
                content=content,
                template_variables=input_data
            )

            # Return the assistant's response
            return {
                "assistant_name": assistant.name,
                "response": response_message.content,
                "chat_id": str(sub_chat.id)
            }

        except Exception as e:
            logger.error(f"Failed to execute assistant tool {tool_name}: {e}")
            return {"error": str(e)}

    async def _handle_tool_calls(
        self,
        chat_id: str,
        user_id: str,
        user_token: str,
        messages: List[Dict[str, Any]],
        tool_calls: List[Dict[str, Any]],
        provider: Optional[str],
        model: Optional[str],
        temperature: float,
        max_tokens: Optional[int],
        tools: List[Dict[str, Any]],
        permissions: Optional[Dict[str, bool]] = None
    ) -> Message:
        """Execute tool calls and get final response."""
        # Get permissions if not provided
        if permissions is None:
            from app.core.auth import get_user_permissions
            permissions = await get_user_permissions(self.db, user_id)
        # Save assistant message with tool calls
        assistant_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=None,
            tool_calls=tool_calls
        )
        self.db.add(assistant_message)
        await self.db.commit()

        # Execute each tool call
        for tool_call in tool_calls:
            tool_name = tool_call["function"]["name"]
            arguments_str = tool_call["function"]["arguments"]
            arguments = json.loads(arguments_str) if isinstance(arguments_str, str) else arguments_str

            # Execute tool (context, webhook, MCP, or execution continuation)
            try:
                # Get chat for context
                result_chat = await self.db.execute(
                    select(Chat).where(Chat.id == chat_id)
                )
                chat = result_chat.scalar_one_or_none()

                if tool_name in ["save_context", "retrieve_context", "update_context", "delete_context"]:
                    # Handle context tools
                    result = await ContextTools.execute_tool(
                        db=self.db,
                        tool_name=tool_name,
                        arguments=arguments,
                        user_id=user_id,
                        chat_id=str(chat_id),
                        group_id=str(chat.group_id) if chat and chat.group_id else None,
                        assistant_id=str(chat.assistant_id) if chat and chat.assistant_id else None
                    )
                elif tool_name in ["explore_ontology", "query_ontology_records", "create_ontology_data_record", "update_ontology_data_record"]:
                    # Handle ontology tools
                    result = await OntologyTools.execute_tool(
                        db=self.db,
                        tool_name=tool_name,
                        arguments=arguments,
                        user_id=user_id,
                        group_id=str(chat.group_id) if chat and chat.group_id else None,
                        assistant_id=str(chat.assistant_id) if chat and chat.assistant_id else None,
                        permissions=permissions
                    )
                elif tool_name == "continue_execution":
                    # Handle execution continuation
                    result = await executor.execute_function(
                        function_name="",  # Not needed for resume
                        input_data=arguments["input"],
                        execution_id=arguments["execution_id"],
                        trigger_type="",  # Not needed for resume
                        trigger_id="",  # Not needed for resume
                        user_id=user_id,
                        resume_data=arguments["input"]
                    )
                elif tool_name.startswith("call_assistant_"):
                    # Handle assistant tool calls
                    result = await self._execute_assistant_tool(
                        chat=chat,
                        user_id=user_id,
                        user_token=user_token,
                        tool_name=tool_name,
                        arguments=arguments
                    )
                elif tool_name in mcp_client.tools:
                    result = await mcp_client.execute_tool(tool_name, arguments)
                else:
                    result = await self.webhook_converter.execute_webhook_tool(
                        db=self.db,
                        tool_name=tool_name,
                        arguments=arguments,
                        user_token=user_token,
                        chat_id=str(chat_id)
                    )

                result_content = json.dumps(result) if not isinstance(result, str) else result

            except Exception as e:
                import traceback
                logger.error(f"Tool execution failed: {e}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                result_content = json.dumps({"error": str(e)})

            # Save tool result message
            tool_message = Message(
                chat_id=chat_id,
                role="tool",
                content=result_content,
                tool_call_id=tool_call["id"],
                name=tool_name
            )
            self.db.add(tool_message)

        await self.db.commit()

        # Get final response from LLM with tool results
        # Rebuild messages with tool results
        result = await self.db.execute(
            select(Message).where(Message.chat_id == chat_id).order_by(Message.created_at)
        )
        updated_messages = []
        for msg in result.scalars().all():
            message_dict = {"role": msg.role}
            if msg.content:
                message_dict["content"] = msg.content
            if msg.tool_calls:
                message_dict["tool_calls"] = msg.tool_calls
            if msg.tool_call_id:
                message_dict["tool_call_id"] = msg.tool_call_id
            if msg.name:
                message_dict["name"] = msg.name
            updated_messages.append(message_dict)

        llm_provider = await create_provider(provider, model, self.db)
        final_response = await llm_provider.complete(
            messages=updated_messages,
            model=model,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens
        )

        # Check if the response has more tool calls (for multi-step tool usage)
        if final_response.get("tool_calls"):
            # Recursively handle the next round of tool calls
            return await self._handle_tool_calls(
                chat_id=chat_id,
                user_id=user_id,
                user_token=user_token,
                messages=updated_messages,
                tool_calls=final_response["tool_calls"],
                provider=provider,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools
            )

        # Save final assistant message
        final_message = Message(
            chat_id=chat_id,
            role="assistant",
            content=final_response.get("content", "")
        )
        self.db.add(final_message)
        await self.db.commit()
        await self.db.refresh(final_message)

        return final_message

    async def _log_request(
        self,
        user_id: str,
        chat_id: str,
        message_id: str,
        provider: str,
        model: str,
        messages: List[Dict[str, Any]],
        response: Dict[str, Any],
        latency_ms: int
    ):
        """
        Log LLM request for analytics.

        Note: This is now handled by the global RequestLoggerMiddleware which logs
        all requests to ClickHouse. LLM-specific metadata could be added to request.state
        if needed for more detailed LLM analytics.
        """
        # LLM request logging now handled by middleware
        # Keeping method for backward compatibility but it's a no-op
        pass
