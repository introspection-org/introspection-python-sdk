"""Introspection Client for Python.

Provides an API for tracking events and feedback using OTLP Logs.
"""

__all__ = ["IntrospectionClient"]

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from opentelemetry import baggage, context
from opentelemetry._logs import SeverityNumber
from opentelemetry.exporter.otlp.proto.http._log_exporter import (
    OTLPLogExporter,
)
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.semconv.resource import (
    ResourceAttributes,  # ty: ignore[deprecated]  # OpenTelemetry deprecated ResourceAttributes but new API not available yet
)

from introspection_sdk.config import AdvancedOptions
from introspection_sdk.types import (
    Attr,
    Baggage,
    EventName,
    FeedbackProperties,
    _generate_message_id,
)
from introspection_sdk.utils import logger
from introspection_sdk.version import VERSION


@dataclass
class GenAiContext:
    """Gen AI context extracted from span or baggage."""

    conversation_id: str | None = None
    """The current conversation/session identifier."""

    previous_response_id: str | None = None
    """ID of the previous model response for continuity."""

    agent_name: str | None = None
    """Name of the active agent."""

    agent_id: str | None = None
    """Unique identifier of the active agent."""


@dataclass
class IdentityContext:
    """Identity context extracted from span or baggage."""

    user_id: str | None = None
    """Authenticated user identifier."""

    anonymous_id: str | None = None
    """Anonymous/device identifier."""


class IntrospectionClient:
    """Client for tracking events and feedback using OTLP Logs.

    Identity and context are managed via OpenTelemetry baggage using context
    managers that automatically clean up when exiting.

    Example:
        ```python
        from introspection_sdk import IntrospectionClient

        client = IntrospectionClient()

        # Track a custom event
        client.track("Button Clicked", {"button_id": "submit"})

        # Track feedback with explicit context
        client.feedback(
            "thumbs_up",
            conversation_id="conv_456",
            previous_response_id="msg_123",
        )

        # Context propagation via baggage - identity and gen_ai context
        # are automatically inherited by subsequent calls
        with client.set_user_id("user_123"):
            with client.set_conversation("conv_456"):
                with client.set_agent("support-bot"):
                    # All calls inherit user, conversation, and agent context
                    client.feedback("thumbs_up")

        # Or use identify for user with traits
        with client.identify("user_123", traits={"plan": "pro"}):
            client.feedback("thumbs_up")  # inherits identity

        # Flush pending events before shutdown
        client.shutdown()
        ```
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        base_url: str | None = None,
        flush_interval_ms: int = 5000,
        max_batch_size: int = 100,
        advanced: AdvancedOptions | None = None,
    ):
        """Initialize the Introspection client.

        Args:
            token: Authentication token (env: INTROSPECTION_TOKEN)
            service_name: Service name for telemetry (env: INTROSPECTION_SERVICE_NAME,
                default: "introspection-client")
            base_url: API base URL (env: INTROSPECTION_BASE_URL,
                default: "https://otel.introspection.dev")
            flush_interval_ms: Flush interval in milliseconds (default: 5000)
            max_batch_size: Maximum batch size before auto-flush (default: 100)
            advanced: Advanced options for configuration and testing.
                If provided, uses values from AdvancedOptions for flush_interval_ms and max_batch_size.
                Individual parameters (base_url, token, service_name) still take precedence when provided.
        """
        # Use defaults if not provided
        self._advanced = advanced or AdvancedOptions()

        # Individual parameters take precedence over advanced options for backward compatibility
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._service_name = service_name or os.getenv(
            "INTROSPECTION_SERVICE_NAME", "introspection-client"
        )
        # base_url: individual param > advanced > env var > default
        self._base_url = (
            base_url
            or self._advanced.base_url
            or os.getenv(
                "INTROSPECTION_BASE_URL", "https://otel.introspection.dev"
            )
        )
        # flush_interval_ms and max_batch_size: use individual params if advanced not provided,
        # otherwise use advanced values (individual params with defaults can't be distinguished from defaults)
        if advanced is None:
            self._flush_interval_ms = flush_interval_ms
            self._max_batch_size = max_batch_size
        else:
            # If advanced is provided, use its values
            self._flush_interval_ms = self._advanced.flush_interval_ms
            self._max_batch_size = self._advanced.max_batch_size

        if not self._token:
            logger.warning(
                "IntrospectionClient: No token provided. Events will not be sent."
            )

        # Use custom exporter if provided, otherwise create default OTLP exporter
        if self._advanced.log_exporter:
            exporter = self._advanced.log_exporter
        else:
            # Construct endpoint URL for logs
            if self._base_url.endswith("/v1/logs"):
                endpoint = self._base_url
            else:
                endpoint = urljoin(self._base_url.rstrip("/") + "/", "v1/logs")

            logger.info(
                f"IntrospectionClient initialized: service={self._service_name}, endpoint={endpoint}"
            )

            # Build headers
            headers = {"Authorization": f"Bearer {self._token}"}
            if self._advanced.additional_headers:
                headers.update(self._advanced.additional_headers)

            # Create OTLP log exporter
            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers=headers,
            )

        # Create batch processor
        processor = BatchLogRecordProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=self._max_batch_size,
            schedule_delay_millis=self._flush_interval_ms,
        )

        # Create resource with service name
        resource = Resource.create(
            {ResourceAttributes.SERVICE_NAME: self._service_name}  # ty: ignore[deprecated]  # OpenTelemetry deprecated ResourceAttributes but new API not available yet
        )

        # Create logger provider with resource
        self._logger_provider = LoggerProvider(resource=resource)
        self._logger_provider.add_log_record_processor(processor)

        # Get logger
        self._otel_logger = self._logger_provider.get_logger(
            "introspection-sdk",
            VERSION,
        )

        # User traits (for identify calls)
        self._traits: dict[str, Any] = {}

    def _get_timestamp(self) -> int:
        """Get current timestamp in nanoseconds since epoch.

        Returns:
            Timestamp in nanoseconds (OpenTelemetry standard format)
        """
        return time.time_ns()

    def _build_attributes(
        self,
        event_name: str,
        *,
        properties: dict[str, Any] | None = None,
        traits: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        previous_response_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Build log record attributes.

        Args:
            event_name: The event name (e.g., "introspection.feedback", "identify")
            properties: Event properties (prefixed with "properties.")
            traits: User traits for identify events (prefixed with "context.traits.")
            conversation_id: Optional conversation ID
            previous_response_id: Optional previous response ID
            event_id: Optional event ID (generated if not provided)

        Returns:
            Flat attribute dict ready for an OTel log record.
        """
        # OTel-style core fields
        attributes: dict[str, Any] = {
            Attr.EVENT_NAME: event_name,
            Attr.EVENT_ID: event_id or _generate_message_id(),
        }

        # Identity from span/baggage context
        identity_ctx = self._get_identity_from_context()
        user_id = identity_ctx.user_id
        anonymous_id = identity_ctx.anonymous_id

        # Gen AI context from baggage
        gen_ai_ctx = self._get_gen_ai_from_context()

        # Identity
        if user_id:
            attributes[Attr.USER_ID] = user_id
        if anonymous_id:
            attributes[Attr.ANONYMOUS_ID] = anonymous_id

        # Gen AI context (OTel semantic conventions)
        # Explicit params override baggage context
        final_conversation_id = conversation_id or gen_ai_ctx.conversation_id
        final_previous_response_id = (
            previous_response_id or gen_ai_ctx.previous_response_id
        )

        if final_conversation_id:
            attributes[Attr.CONVERSATION_ID] = final_conversation_id
        if final_previous_response_id:
            attributes[Attr.PREVIOUS_RESPONSE_ID] = final_previous_response_id
        if gen_ai_ctx.agent_name:
            attributes[Attr.AGENT_NAME] = gen_ai_ctx.agent_name
        if gen_ai_ctx.agent_id:
            attributes[Attr.AGENT_ID] = gen_ai_ctx.agent_id

        # Add properties (flattened with "properties." prefix)
        if properties:
            for key, value in properties.items():
                if value is not None:
                    attr_key = f"{Attr.PROPERTIES_PREFIX}{key}"
                    if isinstance(value, str | int | float | bool):
                        attributes[attr_key] = value
                    else:
                        attributes[attr_key] = json.dumps(value)

        # Add traits (flattened with "context.traits." prefix)
        if traits:
            for key, value in traits.items():
                if value is not None:
                    attr_key = f"{Attr.TRAITS_PREFIX}{key}"
                    if isinstance(value, str | int | float | bool):
                        attributes[attr_key] = value
                    else:
                        attributes[attr_key] = json.dumps(value)

        return attributes

    def _get_gen_ai_from_context(self) -> GenAiContext:
        """Extract gen_ai attributes from baggage context.

        Returns:
            GenAiContext with conversation_id, previous_response_id,
            agent_name, and agent_id
        """
        # Get from baggage
        conversation_id = baggage.get_baggage(Baggage.CONVERSATION_ID)
        previous_response_id = baggage.get_baggage(
            Baggage.PREVIOUS_RESPONSE_ID
        )
        agent_name = baggage.get_baggage(Baggage.AGENT_NAME)
        agent_id = baggage.get_baggage(Baggage.AGENT_ID)

        return GenAiContext(
            conversation_id=str(conversation_id) if conversation_id else None,
            previous_response_id=(
                str(previous_response_id) if previous_response_id else None
            ),
            agent_name=str(agent_name) if agent_name else None,
            agent_id=str(agent_id) if agent_id else None,
        )

    def _get_identity_from_context(self) -> IdentityContext:
        """Extract identity attributes from baggage context.

        Returns:
            IdentityContext with user_id and anonymous_id
        """
        # Get from baggage
        user_id = baggage.get_baggage(Baggage.USER_ID)
        anonymous_id = baggage.get_baggage(Baggage.ANONYMOUS_ID)

        return IdentityContext(
            user_id=str(user_id) if user_id else None,
            anonymous_id=str(anonymous_id) if anonymous_id else None,
        )

    @contextmanager
    def set_baggage(self, **values: str) -> Iterator[None]:
        """Context manager that attaches key/value pairs as OpenTelemetry baggage.

        The baggage is automatically detached when exiting the context.
        Use this for setting identity and gen_ai context that propagates
        to all child spans.

        Args:
            **values: Key/value pairs to attach as baggage.

        Yields:
            None. Baggage is active for the duration of the ``with`` block.

        Example:
            ```python
            with client.set_baggage(**{"identity.user_id": "user_123"}):
                # All spans and calls within this block will have this baggage
                client.feedback("thumbs_up")
            ```
        """
        current_context = context.get_current()
        for key, value in values.items():
            if not isinstance(value, str):
                value = json.dumps(value) if value is not None else ""
            current_context = baggage.set_baggage(key, value, current_context)
        token = context.attach(current_context)
        try:
            yield
        finally:
            context.detach(token)

    def _build_feedback_attributes(
        self,
        props: FeedbackProperties,
        conversation_id: str | None = None,
        previous_response_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
        """Build attributes for feedback events."""
        return self._build_attributes(
            EventName.FEEDBACK,
            properties=props.to_dict(),
            conversation_id=conversation_id,
            previous_response_id=previous_response_id,
            event_id=event_id,
        )

    def track(
        self,
        event_name: str,
        properties: dict[str, Any] | None = None,
        *,
        event_id: str | None = None,
    ) -> None:
        """Track a custom event.

        Args:
            event_name: Event name (e.g., "Button Clicked")
            properties: Event properties
            event_id: Optional event ID (generated if not provided)

        Example:
            ```python
            client.track("Button Clicked", {"button_id": "submit"})
            ```
        """
        attributes = self._build_attributes(
            event_name, properties=properties, event_id=event_id
        )

        self._otel_logger.emit(
            timestamp=self._get_timestamp(),
            context=context.get_current(),
            severity_number=SeverityNumber.INFO,
            attributes=attributes,
        )

        logger.debug(f"Tracked: {event_name}")

    def feedback(
        self,
        name: str,
        *,
        comments: str | None = None,
        conversation_id: str | None = None,
        previous_response_id: str | None = None,
        event_id: str | None = None,
        **extra: Any,
    ) -> None:
        """Track feedback on a message or response.

        Args:
            name: Feedback name/action (e.g., "thumbs_up", "thumbs_down")
            comments: User's comments
            conversation_id: Conversation/session ID (falls back to baggage)
            previous_response_id: ID of the response being given feedback on
            event_id: Optional event ID (generated if not provided)
            **extra: Additional custom properties

        Note:
            Identity is resolved from span/baggage context.
            previous_response_id must be explicit; conversation_id falls back
            to baggage context.

        Example:
            ```python
            # Use context managers for identity and gen_ai context
            with client.set_user_id("user_123"):
                # Simple feedback
                client.feedback("thumbs_down", comments="Answer was off topic")

                # With conversation context
                with client.set_conversation(conv_id):
                    client.feedback("thumbs_up")
            ```
        """
        props = FeedbackProperties(
            name=name,
            comments=comments,
            extra=extra,
        )

        attributes = self._build_feedback_attributes(
            props,
            conversation_id=conversation_id,
            previous_response_id=previous_response_id,
            event_id=event_id,
        )

        self._otel_logger.emit(
            timestamp=self._get_timestamp(),
            context=context.get_current(),
            severity_number=SeverityNumber.INFO,
            attributes=attributes,
        )

        logger.debug(f"Feedback: {props.name}")

    @contextmanager
    def identify(
        self,
        user_id: str,
        traits: dict[str, Any] | None = None,
        anonymous_id: str | None = None,
        event_id: str | None = None,
    ) -> Iterator[None]:
        """Context manager to identify a user and their traits.

        Sets identity as baggage that propagates to all child spans within the context.

        Args:
            user_id: The user's unique identifier
            traits: Optional user traits (email, name, plan, etc.)
            anonymous_id: Optional anonymous ID to associate
            event_id: Optional event ID (generated if not provided)

        Yields:
            None. Identity baggage is active for the duration of the
            ``with`` block and automatically detached on exit.

        Example:
            ```python
            with client.identify("user_123", traits={"plan": "pro"}):
                client.feedback("thumbs_up")  # inherits identity
            ```
        """
        if traits:
            self._traits.update(traits)

        # Build baggage values
        baggage_values: dict[str, str] = {Baggage.USER_ID: user_id}
        if anonymous_id:
            baggage_values[Baggage.ANONYMOUS_ID] = anonymous_id

        with self.set_baggage(**baggage_values):
            # Emit identify event within the baggage context
            attributes = self._build_attributes(
                EventName.IDENTIFY, traits=traits, event_id=event_id
            )

            self._otel_logger.emit(
                timestamp=self._get_timestamp(),
                context=context.get_current(),
                severity_number=SeverityNumber.INFO,
                attributes=attributes,
            )

            logger.debug(f"Identified: {user_id}")
            yield

    @contextmanager
    def set_agent(
        self, agent_name: str, agent_id: str | None = None
    ) -> Iterator[None]:
        """Context manager to set the agent context as baggage.

        Sets gen_ai.agent.name and optionally gen_ai.agent.id as baggage
        that propagates to all child spans within the context.

        Args:
            agent_name: Name of the agent
            agent_id: Optional unique identifier for the agent

        Yields:
            None. Agent baggage is active for the duration of the ``with`` block.

        Example:
            ```python
            with client.set_agent("support-bot", agent_id="agent_123"):
                # All spans within this block will have agent context
                client.feedback("thumbs_up")
            ```
        """
        baggage_values: dict[str, str] = {Baggage.AGENT_NAME: agent_name}
        if agent_id:
            baggage_values[Baggage.AGENT_ID] = agent_id
        with self.set_baggage(**baggage_values):
            yield

    @contextmanager
    def set_conversation(
        self,
        conversation_id: str | None = None,
        previous_response_id: str | None = None,
    ) -> Iterator[None]:
        """Context manager to set the conversation context as baggage.

        Sets gen_ai.conversation.id and/or gen_ai.request.previous_response_id
        as baggage that propagates to all child spans within the context.

        Args:
            conversation_id: Unique identifier for the conversation (optional)
            previous_response_id: Previous response ID for continuity (optional)

        Yields:
            None. Conversation baggage is active for the duration of the
            ``with`` block.

        Example:
            ```python
            # Simple conversation context
            with client.set_conversation("conv_456"):
                client.feedback("thumbs_up")

            # With previous response for conversation continuity
            with client.set_conversation("conv_456", "resp_123"):
                client.feedback("thumbs_up")

            # Just previous_response_id when already in a conversation
            with client.set_conversation("conv_456"):
                with client.set_conversation(previous_response_id="resp_1"):
                    client.feedback("thumbs_up")
            ```
        """
        values = {}
        if conversation_id:
            values[Baggage.CONVERSATION_ID] = conversation_id
        if previous_response_id:
            values[Baggage.PREVIOUS_RESPONSE_ID] = previous_response_id
        with self.set_baggage(**values):
            yield

    @contextmanager
    def set_user_id(self, user_id: str) -> Iterator[None]:
        """Context manager to set the user ID as baggage.

        Sets identity.user_id as baggage that propagates to all
        child spans within the context.

        Args:
            user_id: User identifier

        Yields:
            None. User ID baggage is active for the duration of the ``with`` block.

        Example:
            ```python
            with client.set_user_id("user_123"):
                # All spans within this block will have user context
                client.feedback("thumbs_up")
            ```
        """
        with self.set_baggage(**{Baggage.USER_ID: user_id}):
            yield

    @contextmanager
    def set_anonymous_id(self, anonymous_id: str) -> Iterator[None]:
        """Context manager to set the anonymous ID as baggage.

        Sets identity.anonymous_id as baggage that propagates to all
        child spans within the context.

        Args:
            anonymous_id: Anonymous identifier

        Yields:
            None. Anonymous ID baggage is active for the duration of the
            ``with`` block.

        Example:
            ```python
            with client.set_anonymous_id("anon_789"):
                # All spans within this block will have anonymous context
                client.track("Page View")
            ```
        """
        with self.set_baggage(**{Baggage.ANONYMOUS_ID: anonymous_id}):
            yield

    def get_anonymous_id(self) -> str | None:
        """Get the current anonymous ID from baggage context.

        Returns:
            The anonymous ID from current baggage, or None if not set.
        """
        value = baggage.get_baggage(Baggage.ANONYMOUS_ID)
        return str(value) if value else None

    def get_user_id(self) -> str | None:
        """Get the current user ID from baggage context.

        Returns:
            The user ID from current baggage, or None if not set.
        """
        value = baggage.get_baggage(Baggage.USER_ID)
        return str(value) if value else None

    def reset(self) -> None:
        """Reset client state (e.g., on logout).

        Note: This only resets stored traits. Identity and context are now
        managed via baggage context managers (set_user_id, set_anonymous_id, etc.)
        which automatically clean up when exiting their context.
        """
        self._traits = {}
        logger.debug("Client state reset")

    def flush(self, timeout_ms: int = 30000) -> bool:
        """Flush all pending events.

        Args:
            timeout_ms: Timeout in milliseconds. Use 0 for non-blocking flush
                       (doesn't wait for completion).

        Returns:
            True if flush was successful
        """
        logger.info("Flushing IntrospectionClient")
        return self._logger_provider.force_flush(timeout_ms)

    def shutdown(self) -> None:
        """Shutdown the client and flush pending events."""
        logger.info("Shutting down IntrospectionClient")
        self._logger_provider.shutdown()
