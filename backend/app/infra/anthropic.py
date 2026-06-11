from __future__ import annotations

import datetime
from typing import Any

import anthropic as anthropic_sdk
from anthropic.types import MessageParam as ChatMessage
from anthropic.types import TextBlock

from app.infra.tracing import current_trace_var

__all__ = ["AnthropicClient", "ChatMessage"]


class AnthropicClient:
    """Thin async wrapper around the Anthropic Messages API.

    Emits a Langfuse generation event on every call when a trace observation
    is active (passed via ``parent`` or the ``current_trace_var`` contextvar).
    """

    def __init__(
        self,
        api_key: str,
        *,
        _client: anthropic_sdk.AsyncAnthropic | None = None,
    ) -> None:
        # _client is injectable so unit tests can pass a mock without patching.
        self._client = _client or anthropic_sdk.AsyncAnthropic(api_key=api_key)

    async def chat(
        self,
        *,
        messages: list[ChatMessage],
        model: str,
        system: str,
        max_tokens: int = 1024,
        span_name: str = "llm.generation",
        parent: Any = None,  # StatefulSpanClient | StatefulTraceClient | None
    ) -> tuple[str, int, int]:
        """Make a single-turn chat completion.

        Returns ``(text, input_tokens, output_tokens)``.

        If *parent* is provided, attaches a Langfuse generation event to it.
        Falls back to ``current_trace_var`` when *parent* is ``None``.
        Only text-block responses are supported; a ``RuntimeError`` is raised
        if the model returns any other content block type.
        """
        t0 = datetime.datetime.now(tz=datetime.UTC)
        response = await self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        t1 = datetime.datetime.now(tz=datetime.UTC)

        block = response.content[0]
        if not isinstance(block, TextBlock):
            raise RuntimeError(
                f"Expected TextBlock from Anthropic, got {type(block).__name__}. "
                "Tool-use and multi-block responses are not supported in this path."
            )
        text: str = block.text
        input_tokens: int = response.usage.input_tokens
        output_tokens: int = response.usage.output_tokens

        obs: Any = parent if parent is not None else current_trace_var.get()
        if obs is not None:
            latency_ms = round((t1 - t0).total_seconds() * 1000, 1)
            obs.generation(
                name=span_name,
                model=model,
                input=messages,
                output=text,
                start_time=t0,
                end_time=t1,
                usage_details={"input": input_tokens, "output": output_tokens},
                metadata={"latency_ms": latency_ms},
            )

        return text, input_tokens, output_tokens
