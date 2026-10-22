"""Monkey-patch for a CrewAI 1.14.4 bug where HTTPS MCP tool names are sanitized
on discovery but the sanitized name is then sent back to the server, so any
server tool whose name contains hyphens (e.g. Context7's `resolve-library-id`)
becomes unreachable. Re-verify on crewai upgrade.

Importing this module applies the patch as a side effect.
"""
import asyncio
from typing import Any, cast

from crewai.mcp.tool_resolver import MCPToolResolver
from crewai.tools.base_tool import BaseTool
from crewai.tools.mcp_tool_wrapper import MCPToolWrapper
from crewai.utilities.string_utils import sanitize_tool_name


def _resolve_external(self, mcp_ref: str) -> list[BaseTool]:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    if "#" in mcp_ref:
        server_url, specific_tool = mcp_ref.split("#", 1)
    else:
        server_url, specific_tool = mcp_ref, None

    server_params = {"url": server_url}
    server_name = self._extract_server_name(server_url)
    sanitized_specific = sanitize_tool_name(specific_tool) if specific_tool else None

    async def _list_mcp_tools() -> list[Any]:
        async with streamablehttp_client(server_url) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return list((await session.list_tools()).tools)

    try:
        mcp_tools = asyncio.run(_list_mcp_tools())
    except Exception as e:
        self._logger.log("warning", f"Failed to connect to MCP server {server_url}: {e}")
        return []

    tools: list[BaseTool] = []
    for mcp_tool in mcp_tools:
        sanitized = sanitize_tool_name(mcp_tool.name)
        if sanitized_specific and sanitized != sanitized_specific:
            continue
        args_schema = None
        if getattr(mcp_tool, "inputSchema", None):
            args_schema = self._json_schema_to_pydantic(sanitized, mcp_tool.inputSchema)
        schema = {
            "description": getattr(mcp_tool, "description", ""),
            "args_schema": args_schema,
        }
        try:
            wrapper = MCPToolWrapper(
                mcp_server_params=server_params,
                tool_name=sanitized,
                tool_schema=schema,
                server_name=server_name,
            )
            # Preserve the unsanitized server-side name so call_tool reaches the real tool.
            wrapper._original_tool_name = mcp_tool.name
            tools.append(wrapper)
        except Exception as e:
            self._logger.log("warning", f"Failed to create MCP tool wrapper for {sanitized}: {e}")

    return cast(list[BaseTool], tools)


MCPToolResolver._resolve_external = _resolve_external


# --- Anthropic prompt caching ------------------------------------------------------------------
# CrewAI 1.14.4 never sends `cache_control`, so every tool-loop iteration pays full price for the whole
# history it re-sends (cache tokens were 0 in every cost report). The Messages API supports automatic
# caching through a single top-level `cache_control` field: the breakpoint moves forward as the
# conversation grows and cache reads cost a fraction of normal input. The SDK in use has no keyword
# for it, so it goes through `extra_body`. Set ANTHROPIC_PROMPT_CACHE=0 to turn it off.
import functools
import os

from anthropic.resources.messages import AsyncMessages, Messages


def _with_prompt_cache(original):
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        body = dict(kwargs.get("extra_body") or {})
        body.setdefault("cache_control", {"type": "ephemeral"})
        kwargs["extra_body"] = body
        return original(self, *args, **kwargs)

    wrapper._prompt_cache_patched = True
    return wrapper


if os.environ.get("ANTHROPIC_PROMPT_CACHE", "1") != "0":
    for _cls in (Messages, AsyncMessages):
        for _name in ("create", "stream"):
            if not getattr(getattr(_cls, _name), "_prompt_cache_patched", False):
                setattr(_cls, _name, _with_prompt_cache(getattr(_cls, _name)))


# --- Forced final answer when max_iter is reached ---------------------------------------------------
# CrewAI appends its "give your final answer now" instruction as an *assistant* message (a prefill).
# Recent Claude models reject that with a 400 ("This model does not support assistant message prefill.
# The conversation must end with a user message"), which crashed the whole run when an agent used up its
# iterations. The same instruction is sent here as a user message.
from crewai.agents import crew_agent_executor
from crewai.utilities import agent_utils


def _handle_max_iterations_exceeded(formatted_answer, printer, messages, llm, callbacks, verbose=True):
    if verbose:
        printer.print(content="Maximum iterations reached. Requesting final answer.", color="yellow")

    instruction = agent_utils.I18N_DEFAULT.errors("force_final_answer")
    if formatted_answer and hasattr(formatted_answer, "text"):
        instruction = formatted_answer.text + f"\n{instruction}"
    messages.append(agent_utils.format_message_for_llm(instruction, role="user"))

    answer = llm.call(messages, callbacks=callbacks)
    if answer is None or answer == "":
        if verbose:
            printer.print(content="Received None or empty response from LLM call.", color="red")
        raise ValueError("Invalid response from LLM call - None or empty.")

    formatted = agent_utils.format_answer(answer=answer)
    if isinstance(formatted, agent_utils.AgentFinish):
        return formatted
    return agent_utils.AgentFinish(thought=formatted.thought, output=formatted.text, text=formatted.text)


agent_utils.handle_max_iterations_exceeded = _handle_max_iterations_exceeded
crew_agent_executor.handle_max_iterations_exceeded = _handle_max_iterations_exceeded
