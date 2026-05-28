"""OpenTelemetry-backed logs surface for the Introspection SDK.

:class:`IntrospectionLogs` is an independent surface (separate from
:class:`~introspection_sdk.IntrospectionClient`) that emits structured
log records over OTLP for the Introspection backend. It owns a
``LoggerProvider`` and exposes the ergonomic ``track`` / ``feedback`` /
``identify`` helpers, plus baggage context managers
(``set_baggage`` / ``set_agent`` / ``set_conversation`` /
``set_user_id`` / ``set_anonymous_id``).

Example::

    from introspection_sdk import IntrospectionLogs

    logs = IntrospectionLogs(token="intro_xxx", service_name="my-app")
    with logs.identify("user_42"):
        logs.track("Button Clicked", {"button_id": "submit"})
        logs.feedback("thumbs_up", conversation_id="conv_456")
    logs.shutdown()
"""

from __future__ import annotations

__all__ = ["IntrospectionLogs"]

import json
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
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

from introspection_sdk.otel.types import (
    Attr,
    Baggage,
    EventName,
    FeedbackProperties,
)
from introspection_sdk.types import _generate_message_id
from introspection_sdk.utils import logger
from introspection_sdk.version import VERSION

if TYPE_CHECKING:
    from opentelemetry.sdk._logs.export import LogRecordExporter


@dataclass
class _GenAiContext:
    """Gen AI context extracted from baggage."""

    conversation_id: str | None = None
    previous_response_id: str | None = None
    agent_name: str | None = None
    agent_id: str | None = None


@dataclass
class _IdentityContext:
    """Identity context extracted from baggage."""

    user_id: str | None = None
    anonymous_id: str | None = None


class IntrospectionLogs:
    """OTLP logs surface for ``track`` / ``feedback`` / ``identify``.

    Independent of :class:`~introspection_sdk.IntrospectionClient` —
    construct one wherever you want to emit Introspection events.

    Example::

        logs = IntrospectionLogs(
            token="intro_xxx",
            service_name="my-app",
        )

        logs.track("Button Clicked", {"button_id": "submit"})
        logs.feedback("thumbs_up", conversation_id="conv_456")
        with logs.identify("user_42"):
            logs.track("Page Viewed", {"path": "/pricing"})

        logs.shutdown()
    """

    def __init__(
        self,
        *,
        token: str | None = None,
        service_name: str | None = None,
        base_otel_url: str | None = None,
        project_id: str | None = None,
        additional_headers: dict[str, str] | None = None,
        flush_interval_ms: int = 5000,
        max_batch_size: int = 100,
        log_exporter: LogRecordExporter | None = None,
    ) -> None:
        """Initialize the logs surface.

        Args:
            token: Authentication token
                (env: ``INTROSPECTION_TOKEN``).
            service_name: Service name for telemetry
                (env: ``INTROSPECTION_SERVICE_NAME``,
                default ``"introspection-client"``).
            base_otel_url: OTLP collector base URL
                (env: ``INTROSPECTION_BASE_OTEL_URL``,
                default ``"https://otel.introspection.dev"``).
            project_id: Optional default project id propagated as
                baggage / resource attribute
                (env: ``INTROSPECTION_PROJECT_ID``).
            additional_headers: Extra HTTP headers added to OTLP
                requests.
            flush_interval_ms: OTLP batch flush interval. Default 5000.
            max_batch_size: OTLP max export batch size. Default 100.
            log_exporter: Custom exporter — bypasses OTLP construction.
                Use for tests.
        """
        self._token = token or os.getenv("INTROSPECTION_TOKEN", "")
        self._service_name = service_name or os.getenv(
            "INTROSPECTION_SERVICE_NAME", "introspection-client"
        )
        self._base_otel_url = base_otel_url or os.getenv(
            "INTROSPECTION_BASE_OTEL_URL",
            "https://otel.introspection.dev",
        )
        self._project_id = project_id or os.getenv("INTROSPECTION_PROJECT_ID")
        self._additional_headers = additional_headers
        self._flush_interval_ms = flush_interval_ms
        self._max_batch_size = max_batch_size

        if not self._token:
            logger.warning(
                "IntrospectionLogs: No token provided. "
                "Events will not be sent."
            )

        if log_exporter is not None:
            exporter: LogRecordExporter = log_exporter
        else:
            if self._base_otel_url.endswith("/v1/logs"):
                endpoint = self._base_otel_url
            else:
                endpoint = urljoin(
                    self._base_otel_url.rstrip("/") + "/", "v1/logs"
                )

            logger.info(
                "IntrospectionLogs initialized: "
                f"service={self._service_name}, otlp={endpoint}"
            )

            headers: dict[str, str] = {
                "Authorization": f"Bearer {self._token}"
            }
            if self._additional_headers:
                headers.update(self._additional_headers)

            exporter = OTLPLogExporter(
                endpoint=endpoint,
                headers=headers,
            )

        processor = BatchLogRecordProcessor(
            exporter,
            max_queue_size=2048,
            max_export_batch_size=self._max_batch_size,
            schedule_delay_millis=self._flush_interval_ms,
        )

        resource = Resource.create(
            {
                ResourceAttributes.SERVICE_NAME: self._service_name  # ty: ignore[deprecated]
            }
        )

        self._logger_provider = LoggerProvider(resource=resource)
        self._logger_provider.add_log_record_processor(processor)
        self._otel_logger = self._logger_provider.get_logger(
            "introspection-sdk",
            VERSION,
        )

        self._traits: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # Attribute builders
    # ------------------------------------------------------------------

    def _get_timestamp(self) -> int:
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
        attributes: dict[str, Any] = {
            Attr.EVENT_NAME: event_name,
            Attr.EVENT_ID: event_id or _generate_message_id(),
        }

        identity_ctx = self._get_identity_from_context()
        user_id = identity_ctx.user_id
        anonymous_id = identity_ctx.anonymous_id

        gen_ai_ctx = self._get_gen_ai_from_context()

        if user_id:
            attributes[Attr.USER_ID] = user_id
        if anonymous_id:
            attributes[Attr.ANONYMOUS_ID] = anonymous_id

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

        if properties:
            for key, value in properties.items():
                if value is not None:
                    attr_key = f"{Attr.PROPERTIES_PREFIX}{key}"
                    if isinstance(value, str | int | float | bool):
                        attributes[attr_key] = value
                    else:
                        attributes[attr_key] = json.dumps(value)

        if traits:
            for key, value in traits.items():
                if value is not None:
                    attr_key = f"{Attr.TRAITS_PREFIX}{key}"
                    if isinstance(value, str | int | float | bool):
                        attributes[attr_key] = value
                    else:
                        attributes[attr_key] = json.dumps(value)

        return attributes

    def _get_gen_ai_from_context(self) -> _GenAiContext:
        conversation_id = baggage.get_baggage(Baggage.CONVERSATION_ID)
        previous_response_id = baggage.get_baggage(
            Baggage.PREVIOUS_RESPONSE_ID
        )
        agent_name = baggage.get_baggage(Baggage.AGENT_NAME)
        agent_id = baggage.get_baggage(Baggage.AGENT_ID)
        return _GenAiContext(
            conversation_id=(
                str(conversation_id) if conversation_id else None
            ),
            previous_response_id=(
                str(previous_response_id) if previous_response_id else None
            ),
            agent_name=str(agent_name) if agent_name else None,
            agent_id=str(agent_id) if agent_id else None,
        )

    def _get_identity_from_context(self) -> _IdentityContext:
        user_id = baggage.get_baggage(Baggage.USER_ID)
        anonymous_id = baggage.get_baggage(Baggage.ANONYMOUS_ID)
        return _IdentityContext(
            user_id=str(user_id) if user_id else None,
            anonymous_id=str(anonymous_id) if anonymous_id else None,
        )

    # ------------------------------------------------------------------
    # Baggage context managers
    # ------------------------------------------------------------------

    @contextmanager
    def set_baggage(self, **values: str) -> Iterator[None]:
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

    @contextmanager
    def set_agent(
        self, agent_name: str, agent_id: str | None = None
    ) -> Iterator[None]:
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
        values: dict[str, str] = {}
        if conversation_id:
            values[Baggage.CONVERSATION_ID] = conversation_id
        if previous_response_id:
            values[Baggage.PREVIOUS_RESPONSE_ID] = previous_response_id
        with self.set_baggage(**values):
            yield

    @contextmanager
    def set_user_id(self, user_id: str) -> Iterator[None]:
        with self.set_baggage(**{Baggage.USER_ID: user_id}):
            yield

    @contextmanager
    def set_anonymous_id(self, anonymous_id: str) -> Iterator[None]:
        with self.set_baggage(**{Baggage.ANONYMOUS_ID: anonymous_id}):
            yield

    def get_anonymous_id(self) -> str | None:
        value = baggage.get_baggage(Baggage.ANONYMOUS_ID)
        return str(value) if value else None

    def get_user_id(self) -> str | None:
        value = baggage.get_baggage(Baggage.USER_ID)
        return str(value) if value else None

    # ------------------------------------------------------------------
    # Emit helpers
    # ------------------------------------------------------------------

    def _build_feedback_attributes(
        self,
        props: FeedbackProperties,
        conversation_id: str | None = None,
        previous_response_id: str | None = None,
        event_id: str | None = None,
    ) -> dict[str, Any]:
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
        if traits:
            self._traits.update(traits)

        baggage_values: dict[str, str] = {Baggage.USER_ID: user_id}
        if anonymous_id:
            baggage_values[Baggage.ANONYMOUS_ID] = anonymous_id

        with self.set_baggage(**baggage_values):
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

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def reset(self) -> None:
        self._traits = {}
        logger.debug("IntrospectionLogs state reset")

    def flush(self, timeout_ms: int = 30000) -> bool:
        logger.info("Flushing IntrospectionLogs")
        return self._logger_provider.force_flush(timeout_ms)

    def shutdown(self) -> None:
        logger.info("Shutting down IntrospectionLogs")
        self._logger_provider.shutdown()
