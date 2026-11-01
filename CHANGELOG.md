## Unreleased

### Fixed
- Prevent occasional hangs during startup by enabling page events before navigation [[#482](https://github.com/plotly/kaleido/pull/482)], with thanks to @dennisjlee for the contribution!

## v1.5.0 -- 2026-10-06

### Changed
- Update Choreographer to v1.4.0 and use its large figure chunking, remove the Kaleido chunking code [[#478](https://github.com/plotly/Kaleido/pull/478)]

### Removed
- Drop support for Python 3.8 [[#478](https://github.com/plotly/Kaleido/pull/478)]
- Remove the `orjson` dependency [[#478](https://github.com/plotly/Kaleido/pull/478)]

### Fixed
- Add the browser path to message in `ChromeNotFoundError` when it was set with `path=` or `BROWSER_PATH` and points to nothing [[#476](https://github.com/plotly/Kaleido/pull/476)], with thanks to @Blizzeq for the contribution!
- Restore serialization of figure specs through the `plotly` JSON encoder [[#478](https://github.com/plotly/Kaleido/pull/478)]

## v1.4.0 -- 2026-08-31

### Fixed
- Fix `TypeError: Type is not JSON serializable: Timestamp` when a figure contains datetime-like values such as a `pandas` `Timestamp`; these now serialize to ISO strings [[#461](https://github.com/plotly/Kaleido/pull/461)], with thanks to @binggao1230 for the contribution!
- Fix `orjson` serialization of `Decimal` values [[issue #453](https://github.com/plotly/Kaleido/issues/453)]

### Changed
- Switch default MathJax version from v2 to v3 [[#469](https://github.com/plotly/Kaleido/pull/469)]

## v1.3.0

### Added
- Allow for request headers to be added to Choreographer calls [[#446](https://github.com/plotly/Kaleido/pull/446)]

### Changed
- Significant refactor, better organization
- `write_fig` and `_from_object` now take an additional argument:
  `cancel_on_error: bool, default False`. See docs.
- Update Choreographer to v1.3.0 [[#449](https://github.com/plotly/Kaleido/pull/449)]

### Deprecated
- Unused `path` argument for `calc_fig` was deprecated.

### Fixed
- Fixed race condition where two render tasks would choose the same filename
- Fix issue where exporting large figures could cause hang [[#442](https://github.com/plotly/Kaleido/pull/442)], with thanks to @EliasTalcott for the contribution!

## v1.3.0rc0
- Significant refactor, better organization
- `write_fig` and `_from_object` now take an additional argument:
  `cancel_on_error: bool, default False`. See docs.
- Unused `path` argument for `calc_fig` was deprecated.
- Fixed race condition where two render tasks would choose the same filename

## v1.2.0
- Try to use plotly JSON encoder instead of default

## v1.1.0
- Add testing
- Fix a variety of type bugs
- Change order of browser closer to fix hang
- Explicitly handle certain argument options better
- Move temp file creation to .open() out of __init__()
- Reduce mathjax version to plotly.py
- Fix hang and add automatic close with stop_sync_server
- Add option to silence warnings in start/stop_sync_server
- Fix bug where attribute was inconsistently named

## v1.1.0rc0
- Improve verbosity of errors when starting kaleido improperly
- Add new api functions start/stop_sync_server

## v1.0.0
- Add warning if using incompatible Plotly version

## v1.0.0rc15
- BUG: Add regex sanitization for auto-filename generation
- Further santiize title to filename conversion

## v1.0.0rc14
- Pass `plotlyjs` option through from Kaleido() to PageGenerator()

## v1.0.0rc13
- Pass mathjax option through when using default plotly.js template

## v1.0.0rc12
- Add `kopts` args to top-level shortcuts to pass args to `Kaleido(**kopts)`

## v1.0.0rc11
- Write mocker tool to parameterize opts in tests
- Crop page to pdf size
- Add type checks to user input for improved error messages
- Fix latex strings in PDF bolding
- Add some choreographer errors to kaleido.errors

## v1.0.0rc10
- Allow user to pass Figure-like dicts
- Fix bug by which calc fig rejected plotly figures
- Improve testing

## v1.0.0rc9
- Fix v1.0.0rc7 for logic reversal (was conditional error)

## v1.0.0rc8
- Add kaleido.calc_fig to return bytes, not write file automatically
- Add calc_fig[_sync], write_fig_sync, and write_fig_from_object_sync to kaleido API

## v1.0.0rc7
- Use new choreo is_isolated() to improve platform support (snap /tmp sandboxing)

## v1.0.0rc6
- Allow PageGenerator(force_cdn=True) to not use plotly.py's installed js

## v1.0.0rc5
- Fix bug by which plotly.py's internal js was always ignored
- Adds testing for PageGenerator
