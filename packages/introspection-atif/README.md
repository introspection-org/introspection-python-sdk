# introspection-atif

GenAI spans to a [Harbor](https://github.com/laude-institute/harbor) ATIF
trajectory, and an ATIF trajectory back to the AG-UI messages that open a
run. It is the projection `introspection-sdk` uses, published on its own so
an eval adapter can read a conversation's spans without installing the SDK.

```bash
pip install introspection-atif
```

```python
from introspection_atif import GenAiSpanList, atif_to_messages, spans_to_atif

spans = GenAiSpanList.model_validate_json(body).items
trajectory = spans_to_atif(spans, session_id="conv-1")
messages = atif_to_messages(trajectory, prompt="Continue the task")
```

## Layout

| Module | Holds |
| --- | --- |
| `introspection_atif.projection` | `spans_to_atif` and `AtifProjection`: a conversation's GenAI spans as one ATIF trajectory. |
| `introspection_atif.messages` | `atif_to_messages` and `AtifConversionError`: a trajectory as the `ag_ui.core` messages a run opens with. |
| `introspection_atif.trajectory` | The ATIF models the projection writes, at `ATIF_SCHEMA_VERSION`. |
| `introspection_atif.genai_span` | `GenAiSpan` and `GenAiSpanList`, the span a conversation read returns. |
| `introspection_atif.genai` | The OTel GenAI message and part models. |
| `introspection_atif.annotations` | `AnnotationState`, the annotation a span read can carry. |

`introspection-sdk` re-exports each of these from its old module
(`introspection_sdk.atif`, `introspection_sdk.atif_messages`,
`introspection_sdk.schemas.atif`, `.genai`, `.genai_span`), so code that
imports them from the SDK keeps working.

## Development

```bash
uv sync --all-extras
uv run ruff format --check . && uv run ruff check .
uv run ty check introspection_atif tests
uv run pytest tests/ --cov=introspection_atif
uv run deptry .
npx --yes jscpd@5.4.1
```
