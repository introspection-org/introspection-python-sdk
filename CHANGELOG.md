# Changelog

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
