# Changelog

## [0.16.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.15.1...v0.16.0) (2026-08-13)


### Features

* **connectors:** add connectors, connections, and the install link ([#129](https://github.com/introspection-org/introspection-python-sdk/issues/129)) ([dd62d31](https://github.com/introspection-org/introspection-python-sdk/commit/dd62d31bcdb0b4746021bd61da6aac2026f9bf22))


### Bug Fixes

* drop the client-side ten-repository cap; correct the `ref` field doc ([#131](https://github.com/introspection-org/introspection-python-sdk/issues/131)) ([d54f5dc](https://github.com/introspection-org/introspection-python-sdk/commit/d54f5dc97196ce2ea1c87e60f97c4fe4594438a6))
* stop start() drifting from create(), expose file tags, and drop identity_key ([#133](https://github.com/introspection-org/introspection-python-sdk/issues/133)) ([c6840ca](https://github.com/introspection-org/introspection-python-sdk/commit/c6840cadb717ee0ce745e686391789ab9458c7c2))

## [0.15.1](https://github.com/introspection-org/introspection-python-sdk/compare/v0.15.0...v0.15.1) (2026-08-10)


### Bug Fixes

* **ci:** remove competing release tagger ([#127](https://github.com/introspection-org/introspection-python-sdk/issues/127)) ([18aa376](https://github.com/introspection-org/introspection-python-sdk/commit/18aa376666102f3c52c1b527a769ac7e8bc06b4d))

## [0.15.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.14.0...v0.15.0) (2026-08-10)


### ⚠ BREAKING CHANGES

* AnthropicInstrumentor, GeminiInstrumentor, IntrospectionTracingProcessor, IntrospectionCallbackHandler, IntrospectionConversationsSession, traced_embeddings_create, async_traced_embeddings_create, REDACTED_THINKING_CONTENT, and the convert_responses_* converters are removed, along with the per-framework install extras for those SDKs.
* experiments.create/update/delete and recipes.create/update/delete are removed. Use the CLI to author definitions.

### Features

* add complete conversation export parity ([#121](https://github.com/introspection-org/introspection-python-sdk/issues/121)) ([990760b](https://github.com/introspection-org/introspection-python-sdk/commit/990760be3db9a112856ba8316ad64dc6a9494f62))
* align the SDK with the current API and the runner-plane boundary ([#116](https://github.com/introspection-org/introspection-python-sdk/issues/116)) ([490c92d](https://github.com/introspection-org/introspection-python-sdk/commit/490c92d99a4fc4bb6b48c06af1af41645ebb132c))


### Bug Fixes

* stop resolve() depending on a filter the API never had ([#119](https://github.com/introspection-org/introspection-python-sdk/issues/119)) ([8c3e900](https://github.com/introspection-org/introspection-python-sdk/commit/8c3e90078e86f29782894af333d3a0103c8d1dd2))


### Code Refactoring

* minimal REST + OTel surface, and the defect pass over it ([#120](https://github.com/introspection-org/introspection-python-sdk/issues/120)) ([4569eb1](https://github.com/introspection-org/introspection-python-sdk/commit/4569eb1b28113132157a6523310aeccb2ccdeb88))

## [0.14.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.13.0...v0.14.0) (2026-08-08)


### Features

* **conversations:** add summary resources and agent selection ([#113](https://github.com/introspection-org/introspection-python-sdk/issues/113)) ([053a6a8](https://github.com/introspection-org/introspection-python-sdk/commit/053a6a8a17fc3612c0a572a526defffb836c76eb))

## [0.13.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.12.0...v0.13.0) (2026-08-06)


### Features

* **tasks:** add `files` to task and task-run create ([#111](https://github.com/introspection-org/introspection-python-sdk/issues/111)) ([5aa45e1](https://github.com/introspection-org/introspection-python-sdk/commit/5aa45e15a279fb92231d28f580c127dc14d1b3dc))

## [0.12.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.11.0...v0.12.0) (2026-08-05)


### ⚠ BREAKING CHANGES

* **conversations:** `ConversationItem`, `ConversationItemList`, `ConversationSummary`, `ConversationResponse`, `IntrospectionMetadata` and `SpanEvent` are removed. Both conversation reads now return `GenAiSpan`.

### Features

* **conversations:** replace the flat conversation models with GenAiSpan ([#108](https://github.com/introspection-org/introspection-python-sdk/issues/108)) ([38877ae](https://github.com/introspection-org/introspection-python-sdk/commit/38877aeaf1975221f9d517375d46489e1f988bb7))

## [0.11.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.10.0...v0.11.0) (2026-07-29)


### Features

* **otel:** trace embedding usage metadata ([#96](https://github.com/introspection-org/introspection-python-sdk/issues/96)) ([925ca8a](https://github.com/introspection-org/introspection-python-sdk/commit/925ca8a70be4d53066ee098835d5bf4d123d2121))
* paginate conversation items with opaque cursors ([#100](https://github.com/introspection-org/introspection-python-sdk/issues/100)) ([d6624c2](https://github.com/introspection-org/introspection-python-sdk/commit/d6624c23680dbca52fe9c02ba4bb722bd9424420))

## [0.10.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.9.0...v0.10.0) (2026-07-29)


### Features

* route tasks to a named dev server via INTROSPECTION_DEV_TARGET ([#98](https://github.com/introspection-org/introspection-python-sdk/issues/98)) ([3497ef9](https://github.com/introspection-org/introspection-python-sdk/commit/3497ef9a55c69214ffc3ef1149bc1c9f5beab190))


### Bug Fixes

* drop CLEAR from TaskRunKind ([#92](https://github.com/introspection-org/introspection-python-sdk/issues/92)) ([4d132ca](https://github.com/introspection-org/introspection-python-sdk/commit/4d132ca5a9b8f4f7067b9d141faeb74dd7cffb03))

## [0.9.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.8.0...v0.9.0) (2026-07-24)


### ⚠ BREAKING CHANGES

* **experiments:** ExperimentCreate requires runtime_group_id, arms, and goal_json; ExperimentHandle.end()/AsyncExperimentHandle.end() no longer accept winning_arm_label/notes.
* RuntimeResolutionMode is removed from introspection_sdk.schemas.

### Features

* add environment_ref to Runtime; drop RuntimeResolutionMode ([#88](https://github.com/introspection-org/introspection-python-sdk/issues/88)) ([b3e8d06](https://github.com/introspection-org/introspection-python-sdk/commit/b3e8d061795268cc0155b36dd553ad623b5eb89b))


### Bug Fixes

* **experiments:** align the experiments contract with the CP API ([#87](https://github.com/introspection-org/introspection-python-sdk/issues/87)) ([d476b36](https://github.com/introspection-org/introspection-python-sdk/commit/d476b360c93243902e7914f3b8d89da2dbd226f5))

## [0.8.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.7.1...v0.8.0) (2026-07-18)


### ⚠ BREAKING CHANGES

* runner.events.list()/iterate() now take a required event_name (exactly one of the six IntrospectionEventName families) and return the discriminated Event union (common envelope + nested typed payload). RawEvent, LensObservation, PatternGrainEvent, EventRecord, EventGrain, and EventInclude are deleted, along with the grain, include, event_name_prefix, q, and q_regex params. Family-scoped filters (observation: conversation_ids/lens/pattern_id/include_superseded/ severities/runtime_group_unattributed; pattern: lens/status) pass through and are server-validated. Rows with an event_name outside the known family set are skipped client-side (counted + debug-logged), never raised. Arrow decode handles the new envelope-columns + payload-struct wire shape, and a new columnar accessor (runner.events.arrow() / runner.conversations.arrow()) yields one pyarrow.Table per page with a read_all() concatenation convenience ([arrow] extra, lazy import).

### Features

* runner events/metrics reads — typed six-family events, Arrow decode + columnar arrow() ([#80](https://github.com/introspection-org/introspection-python-sdk/issues/80)) ([69a5313](https://github.com/introspection-org/introspection-python-sdk/commit/69a53139721509609e909b19fd9ce9b178523b8a))


### Bug Fixes

* align SDK execution contracts ([#85](https://github.com/introspection-org/introspection-python-sdk/issues/85)) ([4e22329](https://github.com/introspection-org/introspection-python-sdk/commit/4e2232905fc8ae33706760947813b78750526f0e))
* keep runtime SDK surface read and run only ([#86](https://github.com/introspection-org/introspection-python-sdk/issues/86)) ([4758764](https://github.com/introspection-org/introspection-python-sdk/commit/4758764755ea34690b8ea95369718a28f2f6afdb))

## [0.7.1](https://github.com/introspection-org/introspection-python-sdk/compare/v0.7.0...v0.7.1) (2026-07-15)


### Bug Fixes

* align conversations API with server contract ([#78](https://github.com/introspection-org/introspection-python-sdk/issues/78)) ([6dbba77](https://github.com/introspection-org/introspection-python-sdk/commit/6dbba77a8a846942c73619ceac80b38fd31a26b2))

## [0.7.0](https://github.com/introspection-org/introspection-python-sdk/compare/v0.6.5...v0.7.0) (2026-07-05)


### Features

* **ci:** adopt release-please for versioning; rename VERSION to version.txt ([#74](https://github.com/introspection-org/introspection-python-sdk/issues/74)) ([b478fba](https://github.com/introspection-org/introspection-python-sdk/commit/b478fbacbb1e7f0d86f7b268375f64fe3a5917a4))
* **ci:** release-please cuts the tag on release-PR merge ([#76](https://github.com/introspection-org/introspection-python-sdk/issues/76)) ([f0e95bf](https://github.com/introspection-org/introspection-python-sdk/commit/f0e95bf67c3f5fa3a225302a1490161420ec303e))
