"""Typing Protocols for the data-plane namespaces.

:class:`DataPlaneResources` is the interface the client and the
:class:`~introspection_sdk.runner.Runner` share on the data plane, and
:class:`AsyncDataPlaneResources` its async twin. Each namespace is a
Protocol of its methods too, so code written against these runs with
either handle, and the type checker fails when the two drift apart.

The two differ in credential, not in shape: the client sends its own token
(an API key, a service account or a member's token) and the Runner sends
the session token minted for it. ``runner.connections.create`` takes
``runtime`` as optional, defaulting to the runner's runtime group, which
still satisfies the Protocol, where ``runtime`` is required.
"""

from __future__ import annotations

import builtins
from collections.abc import AsyncIterator, Iterator
from datetime import datetime
from typing import Any, Literal, Protocol, Unpack, runtime_checkable
from uuid import UUID

from introspection_sdk.pagination import AsyncPager, Pager
from introspection_sdk.runner_resources._reads import (
    ArrowPageIterator,
    AsyncArrowPageIterator,
    ReadFormat,
)
from introspection_sdk.runner_resources.automations import MetadataInput
from introspection_sdk.runner_resources.conversations import (
    ConversationExportFormat,
    ConversationExportParams,
    ConversationResolution,
    ConversationSentiment,
)
from introspection_sdk.runner_resources.files import FileLike
from introspection_sdk.runner_resources.tasks import AsyncRunHandle, RunHandle
from introspection_sdk.schemas.agui import AGUIEvent, ResumeEntry
from introspection_sdk.schemas.automations import (
    Automation,
    AutomationKind,
    AutomationTriggerResponse,
    AutomationTriggerType,
)
from introspection_sdk.schemas.connections import Connection, ConnectPage
from introspection_sdk.schemas.conversations import (
    Conversation,
    ConversationItemInclude,
    ConversationSortField,
    SpanStatus,
)
from introspection_sdk.schemas.events import (
    Event,
    EventSortField,
    IntrospectionEventName,
    UnknownEvent,
)
from introspection_sdk.schemas.files import File, FileType
from introspection_sdk.schemas.genai_span import GenAiSpan, GenAiSpanList
from introspection_sdk.schemas.issues import (
    Issue,
    IssueEventReference,
    IssueFile,
    IssueLink,
    IssueMetadataValue,
    IssueOwner,
    IssuePriority,
    IssueSpanReference,
    IssueStatus,
)
from introspection_sdk.schemas.metrics import (
    MetricQueryRequest,
    MetricQueryResponse,
)
from introspection_sdk.schemas.pagination import Paginated
from introspection_sdk.schemas.shares import ResourceShare, ShareResourceType
from introspection_sdk.schemas.tasks import (
    Task,
    TaskCancelRequest,
    TaskCancelResponse,
    TaskCreateResponse,
    TaskFileRef,
    TaskPrompt,
    TaskRepoRequest,
    TaskRun,
    TaskRunKind,
    TaskStatus,
)
from introspection_sdk.schemas.trajectory import Trajectory

__all__ = [
    "AsyncAutomationsResource",
    "AsyncConnectionsResource",
    "AsyncConversationItemsResource",
    "AsyncConversationsResource",
    "AsyncDataPlaneResources",
    "AsyncEventsResource",
    "AsyncFileVersionsResource",
    "AsyncFilesResource",
    "AsyncIssuesResource",
    "AsyncMetricsResource",
    "AsyncSharesResource",
    "AsyncTaskRunsResource",
    "AsyncTasksResource",
    "AutomationsResource",
    "ConnectionsResource",
    "ConversationItemsResource",
    "ConversationsResource",
    "DataPlaneResources",
    "EventsResource",
    "FileVersionsResource",
    "FilesResource",
    "IssuesResource",
    "MetricsResource",
    "SharesResource",
    "TaskRunsResource",
    "TasksResource",
]


@runtime_checkable
class TaskRunsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.tasks.TaskRuns`."""

    def create(
        self,
        task_id: str,
        *,
        prompt: TaskPrompt | dict[str, Any] | None = None,
        kind: TaskRunKind | str | None = None,
        metadata: dict[str, Any] | None = None,
        files: list[TaskFileRef | dict[str, Any]] | None = None,
    ) -> RunHandle: ...

    def resume(
        self, task_id: str, *, resume: list[ResumeEntry | dict[str, Any]]
    ) -> RunHandle: ...

    def get(self, task_id: str, run_id: str) -> TaskRun: ...

    def cancel(
        self,
        task_id: str,
        run_id: str,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse: ...

    def stream(
        self,
        task_id: str,
        run_id: str,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> Iterator[AGUIEvent]: ...


@runtime_checkable
class TasksResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.tasks.Tasks`."""

    @property
    def runs(self) -> TaskRunsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        statuses: builtins.list[str] | None = None,
        require_automation_id: bool | None = None,
        tag: str | None = None,
    ) -> Pager[Task, Paginated[Task]]: ...

    def create(
        self,
        *,
        title: str | None = None,
        prompt: str | None = None,
        agent_name: str | None = None,
        repositories: builtins.list[TaskRepoRequest | dict[str, Any]]
        | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_metadata: dict[str, str] | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
        files: builtins.list[TaskFileRef | dict[str, Any]] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> TaskCreateResponse: ...

    def get(self, task_id: str) -> Task: ...

    def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        is_archived: bool | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> Task: ...

    def delete(self, task_id: str) -> None: ...

    def archive(self, task_id: str) -> None: ...

    def unarchive(self, task_id: str) -> None: ...

    def start(self, *, prompt: str, **kwargs: Any) -> RunHandle: ...


@runtime_checkable
class FileVersionsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.files.FileVersions`."""

    def list(
        self,
        file_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
    ) -> Pager[File, Paginated[File]]: ...

    def get(self, file_id: str, version_id: str) -> File: ...

    def create(
        self,
        file_id: str,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
    ) -> File: ...


@runtime_checkable
class FilesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.files.Files`."""

    @property
    def versions(self) -> FileVersionsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        name: str | None = None,
        file_type: FileType | str | None = None,
        storage_path: str | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> Pager[File, Paginated[File]]: ...

    def upload(
        self,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    def create_text(
        self,
        *,
        name: str,
        content: str,
        mime_type: str = "text/markdown",
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    def get(self, file_id: str) -> File: ...

    def update(
        self,
        file_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    def delete(self, file_id: str) -> None: ...

    def download(self, file_id: str) -> bytes: ...

    def download_stream(self, file_id: str) -> Iterator[bytes]: ...


@runtime_checkable
class ConversationItemsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.conversations.ConversationItems`."""

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lookback_days: int | None = None,
        share_id: str | None = None,
    ) -> Pager[GenAiSpan, GenAiSpanList]: ...

    def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> GenAiSpan: ...


@runtime_checkable
class ConversationsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.conversations.Conversations`."""

    @property
    def items(self) -> ConversationItemsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        conversation_ids: builtins.list[str] | None = None,
        share_id: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        format: ReadFormat = "json",
    ) -> Pager[Conversation, Paginated[Conversation]]: ...

    def list_arrow(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        conversation_ids: builtins.list[str] | None = None,
        share_id: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
    ) -> ArrowPageIterator: ...

    def iterate(
        self, *, max_items: int | None = None, **kwargs: Any
    ) -> Iterator[Conversation]: ...

    def get(self, conversation_id: str) -> Conversation: ...

    def export_json(
        self, conversation_id: str, **params: Unpack[ConversationExportParams]
    ) -> GenAiSpanList: ...

    def export_stream(
        self,
        conversation_id: str,
        format: ConversationExportFormat,
        **params: Unpack[ConversationExportParams],
    ) -> Iterator[bytes]: ...

    def export_trajectory(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Trajectory: ...

    def export_arrow(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Any: ...

    def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> GenAiSpan | None: ...


@runtime_checkable
class EventsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.events.Events`."""

    def list(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        owner_key: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        automation_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        format: ReadFormat = "json",
    ) -> Pager[Event, Paginated[Event]]: ...

    def get(self, event_id: str) -> Event | UnknownEvent: ...

    def iterate(
        self,
        event_name: str | IntrospectionEventName,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> Iterator[Event]: ...

    def list_arrow(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        owner_key: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        automation_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
    ) -> ArrowPageIterator: ...


@runtime_checkable
class MetricsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.metrics.Metrics`."""

    def query(
        self, request: MetricQueryRequest | dict[str, Any]
    ) -> MetricQueryResponse: ...


@runtime_checkable
class SharesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.shares.Shares`."""

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        resource_type: ShareResourceType | str | None = None,
        resource_id: str | None = None,
        created_by_me: bool = False,
        granted_to_me: bool = False,
    ) -> Pager[ResourceShare, Paginated[ResourceShare]]: ...

    def create(
        self,
        *,
        resource_type: ShareResourceType | str,
        resource_id: str,
        granted_member_id: str | None = None,
    ) -> ResourceShare: ...

    def get(self, share_id: str) -> ResourceShare: ...

    def delete(self, share_id: str) -> None: ...


@runtime_checkable
class AutomationsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.automations.Automations`."""

    def list(
        self,
        *,
        kind: AutomationKind | str | None = None,
        enabled: bool | None = None,
        scheduled: bool | None = None,
        task_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Automation, Paginated[Automation]]: ...

    def get(self, automation_id: UUID | str) -> Automation: ...

    def create(
        self,
        *,
        name: str,
        trigger_type: AutomationTriggerType | str,
        description: str | None = None,
        cron_schedule: str | None = None,
        kind: AutomationKind | str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | None = None,
        task_id: UUID | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Automation: ...

    def update(
        self,
        automation_id: UUID | str,
        *,
        name: str | None = None,
        description: str | None = None,
        cron_schedule: str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | None = None,
        task_id: UUID | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Automation: ...

    def delete(self, automation_id: UUID | str) -> None: ...

    def trigger(
        self, automation_id: UUID | str
    ) -> AutomationTriggerResponse: ...


@runtime_checkable
class IssuesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.issues.Issues`."""

    def list(
        self,
        *,
        status: builtins.list[IssueStatus | str] | None = None,
        owner: builtins.list[IssueOwner | str] | None = None,
        assigned_to_me: bool | None = None,
        has_open_requests: bool | None = None,
        task_status: builtins.list[TaskStatus | str] | None = None,
        exclude_task_status: builtins.list[TaskStatus | str] | None = None,
        display_index: int | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
        search: str | None = None,
        include_total: bool = False,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Issue, Paginated[Issue]]: ...

    def create(
        self,
        *,
        title: str,
        description: str,
        task_id: UUID | str,
        priority: IssuePriority | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue: ...

    def get(self, issue_id: UUID | str) -> Issue: ...

    def update(
        self,
        issue_id: UUID | str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: IssuePriority | str | None = None,
        status: IssueStatus | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue: ...

    def delete(
        self, issue_id: UUID | str, *, idempotency_key: str | None = None
    ) -> None: ...


@runtime_checkable
class AsyncTaskRunsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.tasks.AsyncTaskRuns`."""

    async def create(
        self,
        task_id: str,
        *,
        prompt: TaskPrompt | dict[str, Any] | None = None,
        kind: TaskRunKind | str | None = None,
        metadata: dict[str, Any] | None = None,
        files: list[TaskFileRef | dict[str, Any]] | None = None,
    ) -> AsyncRunHandle: ...

    async def resume(
        self, task_id: str, *, resume: list[ResumeEntry | dict[str, Any]]
    ) -> AsyncRunHandle: ...

    async def get(self, task_id: str, run_id: str) -> TaskRun: ...

    async def cancel(
        self,
        task_id: str,
        run_id: str,
        options: TaskCancelRequest | dict[str, Any] | None = None,
    ) -> TaskCancelResponse: ...

    def stream(
        self,
        task_id: str,
        run_id: str,
        *,
        max_reconnects: int = 5,
        backoff: float = 0.5,
        timeout: float = 300.0,
    ) -> AsyncIterator[AGUIEvent]: ...


@runtime_checkable
class AsyncTasksResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.tasks.AsyncTasks`."""

    @property
    def runs(self) -> AsyncTaskRunsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        statuses: builtins.list[str] | None = None,
        require_automation_id: bool | None = None,
        tag: str | None = None,
    ) -> AsyncPager[Task, Paginated[Task]]: ...

    async def create(
        self,
        *,
        title: str | None = None,
        prompt: str | None = None,
        agent_name: str | None = None,
        repositories: builtins.list[TaskRepoRequest | dict[str, Any]]
        | None = None,
        metadata: dict[str, Any] | None = None,
        conversation_metadata: dict[str, str] | None = None,
        idle_timeout_seconds: int | None = None,
        fork_share_id: str | None = None,
        files: builtins.list[TaskFileRef | dict[str, Any]] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> TaskCreateResponse: ...

    async def get(self, task_id: str) -> Task: ...

    async def update(
        self,
        task_id: str,
        *,
        title: str | None = None,
        is_archived: bool | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> Task: ...

    async def delete(self, task_id: str) -> None: ...

    async def archive(self, task_id: str) -> None: ...

    async def unarchive(self, task_id: str) -> None: ...

    async def start(self, *, prompt: str, **kwargs: Any) -> AsyncRunHandle: ...


@runtime_checkable
class AsyncFileVersionsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.files.AsyncFileVersions`."""

    def list(
        self,
        file_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
    ) -> AsyncPager[File, Paginated[File]]: ...

    async def get(self, file_id: str, version_id: str) -> File: ...

    async def create(
        self,
        file_id: str,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
    ) -> File: ...


@runtime_checkable
class AsyncFilesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.files.AsyncFiles`."""

    @property
    def versions(self) -> AsyncFileVersionsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        include_total: bool = False,
        name: str | None = None,
        file_type: FileType | str | None = None,
        storage_path: str | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> AsyncPager[File, Paginated[File]]: ...

    async def upload(
        self,
        *,
        file: FileLike,
        name: str | None = None,
        file_type: FileType | str = FileType.OTHER,
        content_type: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    async def create_text(
        self,
        *,
        name: str,
        content: str,
        mime_type: str = "text/markdown",
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    async def get(self, file_id: str) -> File: ...

    async def update(
        self,
        file_id: str,
        *,
        name: str | None = None,
        metadata: dict[str, Any] | None = None,
        tags: builtins.list[str] | None = None,
    ) -> File: ...

    async def delete(self, file_id: str) -> None: ...

    async def download(self, file_id: str) -> bytes: ...

    def download_stream(self, file_id: str) -> AsyncIterator[bytes]: ...


@runtime_checkable
class AsyncConversationItemsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.conversations.AsyncConversationItems`."""

    def list(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        next: str | None = None,
        include: builtins.list[ConversationItemInclude] | None = None,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        lookback_days: int | None = None,
        share_id: str | None = None,
    ) -> AsyncPager[GenAiSpan, GenAiSpanList]: ...

    async def get(
        self,
        conversation_id: str,
        item_id: str,
        *,
        include: builtins.list[ConversationItemInclude] | None = None,
    ) -> GenAiSpan: ...


@runtime_checkable
class AsyncConversationsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.conversations.AsyncConversations`."""

    @property
    def items(self) -> AsyncConversationItemsResource: ...

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        conversation_ids: builtins.list[str] | None = None,
        share_id: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[Conversation, Paginated[Conversation]]: ...

    def list_arrow(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        conversation_id: str | None = None,
        sort: ConversationSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        model: str | None = None,
        agent_name: str | None = None,
        status: SpanStatus | None = None,
        service_name: str | None = None,
        service_names: builtins.list[str] | None = None,
        environment: str | None = None,
        runtime_id: UUID | None = None,
        runtime_group_id: UUID | None = None,
        experiment_id: UUID | None = None,
        recipe_git_commit_sha: str | None = None,
        conversation_ids: builtins.list[str] | None = None,
        share_id: builtins.list[str] | None = None,
        resolution: ConversationResolution | None = None,
        sentiment: ConversationSentiment | None = None,
        owner_key: str | None = None,
        metadata: dict[str, str] | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
    ) -> AsyncArrowPageIterator: ...

    def iterate(
        self, *, max_items: int | None = None, **kwargs: Any
    ) -> AsyncIterator[Conversation]: ...

    async def get(self, conversation_id: str) -> Conversation: ...

    async def export_json(
        self, conversation_id: str, **params: Unpack[ConversationExportParams]
    ) -> GenAiSpanList: ...

    def export_stream(
        self,
        conversation_id: str,
        format: ConversationExportFormat,
        **params: Unpack[ConversationExportParams],
    ) -> AsyncIterator[bytes]: ...

    async def export_trajectory(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Trajectory: ...

    async def export_arrow(
        self,
        conversation_id: str,
        *,
        agent: str | None = None,
        service_name: str | None = None,
        operation_name: str | None = None,
        lookback_days: int | None = None,
        share_id: str | UUID | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
    ) -> Any: ...

    async def retrieve(
        self, conversation_id: str, item_id: str | None = None
    ) -> GenAiSpan | None: ...


@runtime_checkable
class AsyncEventsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.events.AsyncEvents`."""

    def list(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        owner_key: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        automation_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
        format: ReadFormat = "json",
    ) -> AsyncPager[Event, Paginated[Event]]: ...

    async def get(self, event_id: str) -> Event | UnknownEvent: ...

    def iterate(
        self,
        event_name: str | IntrospectionEventName,
        *,
        max_items: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[Event]: ...

    def list_arrow(
        self,
        event_name: str | IntrospectionEventName,
        *,
        limit: int = 100,
        next: str | None = None,
        sort: EventSortField | None = None,
        direction: Literal["asc", "desc"] | None = None,
        order: Literal["asc", "desc"] | None = None,
        start: str | datetime | None = None,
        end: str | datetime | None = None,
        lookback: str | None = None,
        start_date: str | datetime | None = None,
        end_date: str | datetime | None = None,
        conversation_id: str | None = None,
        service_name: str | None = None,
        environment: str | None = None,
        runtime_group_id: UUID | None = None,
        trace_id: str | None = None,
        span_id: str | None = None,
        owner_key: str | None = None,
        event_id: builtins.list[str] | None = None,
        conversation_ids: builtins.list[str] | None = None,
        lens: str | None = None,
        pattern_id: str | UUID | None = None,
        include_superseded: bool | None = None,
        severities: builtins.list[str] | None = None,
        runtime_group_unattributed: bool | None = None,
        status: str | None = None,
        automation_id: UUID | str | None = None,
        task_id: UUID | str | None = None,
    ) -> AsyncArrowPageIterator: ...


@runtime_checkable
class AsyncMetricsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.metrics.AsyncMetrics`."""

    async def query(
        self, request: MetricQueryRequest | dict[str, Any]
    ) -> MetricQueryResponse: ...


@runtime_checkable
class AsyncSharesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.shares.AsyncShares`."""

    def list(
        self,
        *,
        limit: int = 100,
        next: str | None = None,
        resource_type: ShareResourceType | str | None = None,
        resource_id: str | None = None,
        created_by_me: bool = False,
        granted_to_me: bool = False,
    ) -> AsyncPager[ResourceShare, Paginated[ResourceShare]]: ...

    async def create(
        self,
        *,
        resource_type: ShareResourceType | str,
        resource_id: str,
        granted_member_id: str | None = None,
    ) -> ResourceShare: ...

    async def get(self, share_id: str) -> ResourceShare: ...

    async def delete(self, share_id: str) -> None: ...


@runtime_checkable
class AsyncAutomationsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.automations.AsyncAutomations`."""

    def list(
        self,
        *,
        kind: AutomationKind | str | None = None,
        enabled: bool | None = None,
        scheduled: bool | None = None,
        task_id: UUID | str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Automation, Paginated[Automation]]: ...

    async def get(self, automation_id: UUID | str) -> Automation: ...

    async def create(
        self,
        *,
        name: str,
        trigger_type: AutomationTriggerType | str,
        description: str | None = None,
        cron_schedule: str | None = None,
        kind: AutomationKind | str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | None = None,
        task_id: UUID | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Automation: ...

    async def update(
        self,
        automation_id: UUID | str,
        *,
        name: str | None = None,
        description: str | None = None,
        cron_schedule: str | None = None,
        prompt: str | None = None,
        runtime_group_id: UUID | None = None,
        task_id: UUID | None = None,
        next_trigger_at: datetime | None = None,
        metadata: MetadataInput | None = None,
        enabled: bool | None = None,
    ) -> Automation: ...

    async def delete(self, automation_id: UUID | str) -> None: ...

    async def trigger(
        self, automation_id: UUID | str
    ) -> AutomationTriggerResponse: ...


@runtime_checkable
class AsyncIssuesResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.issues.AsyncIssues`."""

    def list(
        self,
        *,
        status: builtins.list[IssueStatus | str] | None = None,
        owner: builtins.list[IssueOwner | str] | None = None,
        assigned_to_me: bool | None = None,
        has_open_requests: bool | None = None,
        task_status: builtins.list[TaskStatus | str] | None = None,
        exclude_task_status: builtins.list[TaskStatus | str] | None = None,
        display_index: int | None = None,
        tag: str | None = None,
        metadata: dict[str, str] | None = None,
        search: str | None = None,
        include_total: bool = False,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Issue, Paginated[Issue]]: ...

    async def create(
        self,
        *,
        title: str,
        description: str,
        task_id: UUID | str,
        priority: IssuePriority | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue: ...

    async def get(self, issue_id: UUID | str) -> Issue: ...

    async def update(
        self,
        issue_id: UUID | str,
        *,
        expected_revision: int,
        title: str | None = None,
        description: str | None = None,
        priority: IssuePriority | str | None = None,
        status: IssueStatus | str | None = None,
        tags: builtins.list[str] | None = None,
        metadata: dict[str, IssueMetadataValue] | None = None,
        files: builtins.list[IssueFile] | None = None,
        links: builtins.list[IssueLink] | None = None,
        events: builtins.list[IssueEventReference] | None = None,
        spans: builtins.list[IssueSpanReference] | None = None,
        idempotency_key: str | None = None,
    ) -> Issue: ...

    async def delete(
        self, issue_id: UUID | str, *, idempotency_key: str | None = None
    ) -> None: ...


@runtime_checkable
class ConnectionsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.connections.AppConnections`."""

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        app: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> Pager[Connection, Paginated[Connection]]: ...

    def create(self, *, app: str, runtime: str | UUID) -> ConnectPage: ...

    def get(self, connection_id: UUID | str) -> Connection: ...

    def delete(self, connection_id: UUID | str) -> None: ...


@runtime_checkable
class DataPlaneResources(Protocol):
    """The data-plane namespaces :class:`~introspection_sdk.IntrospectionClient`
    and :class:`~introspection_sdk.runner.Runner` both expose."""

    @property
    def tasks(self) -> TasksResource: ...

    @property
    def files(self) -> FilesResource: ...

    @property
    def conversations(self) -> ConversationsResource: ...

    @property
    def events(self) -> EventsResource: ...

    @property
    def metrics(self) -> MetricsResource: ...

    @property
    def shares(self) -> SharesResource: ...

    @property
    def automations(self) -> AutomationsResource: ...

    @property
    def issues(self) -> IssuesResource: ...

    @property
    def connections(self) -> ConnectionsResource: ...


@runtime_checkable
class AsyncConnectionsResource(Protocol):
    """Protocol of :class:`~introspection_sdk.runner_resources.connections.AsyncAppConnections`."""

    def list(
        self,
        *,
        member_id: UUID | str | None = None,
        app: str | None = None,
        limit: int | None = None,
        next: str | None = None,
    ) -> AsyncPager[Connection, Paginated[Connection]]: ...

    async def create(
        self, *, app: str, runtime: str | UUID
    ) -> ConnectPage: ...

    async def get(self, connection_id: UUID | str) -> Connection: ...

    async def delete(self, connection_id: UUID | str) -> None: ...


@runtime_checkable
class AsyncDataPlaneResources(Protocol):
    """The data-plane namespaces :class:`~introspection_sdk.AsyncIntrospectionClient`
    and :class:`~introspection_sdk.runner.AsyncRunner` both expose."""

    @property
    def tasks(self) -> AsyncTasksResource: ...

    @property
    def files(self) -> AsyncFilesResource: ...

    @property
    def conversations(self) -> AsyncConversationsResource: ...

    @property
    def events(self) -> AsyncEventsResource: ...

    @property
    def metrics(self) -> AsyncMetricsResource: ...

    @property
    def shares(self) -> AsyncSharesResource: ...

    @property
    def automations(self) -> AsyncAutomationsResource: ...

    @property
    def issues(self) -> AsyncIssuesResource: ...

    @property
    def connections(self) -> AsyncConnectionsResource: ...
