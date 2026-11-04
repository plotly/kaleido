
<div align="center">
  <a href="https://dash.plotly.com/project-maintenance">
    <img src="https://dash.plotly.com/assets/images/maintained-by-plotly.png"
    width="400px" alt="Maintained by Plotly">
  </a>
</div>

# Overview
Kaleido is a cross-platform Python library for generating static images
(e.g. png, svg, pdf, etc.) for Plotly.js, to be used by Plotly.py.

## Installation

Kaleido can be installed from [PyPI](https://pypi.org/project/kaleido) using `pip`:

```bash
$ pip install kaleido --upgrade
```

As of version 1.0.0, Kaleido requires Chrome to be installed. If you already have
Chrome on your system, Kaleido should find it; otherwise, you can install
a compatible Chrome version using the `kaleido_get_chrome` command:

```bash
$ kaleido_get_chrome
```

or function in Python:

```python
import kaleido
kaleido.get_chrome_sync()
```

## Migrating from v0 to v1

Kaleido v1 introduces a new API. If you're currently using v0, you'll need
to make changes to your code and environment where you are running Kaleido.

- If using Kaleido v1 with Plotly.py, you will need to install
Plotly.py v6.1.1 or later.
- Chrome is no longer included with Kaleido. Kaleido will look for an existing Chrome
installation, but also provides commands for installing Chrome.
If you don't have Chrome, you'll need to install it.
See the installation section above for instructions.
- If your code uses Kaleido directly: `kaleido.scopes.plotly` has been
removed in v1.
Kaleido v1 provides `write_fig` and `write_fig_sync` for exporting Plotly figures.

```python
import kaleido
import plotly.graph_objects as go

fig = go.Figure(data=[go.Scatter(y=[1, 3, 2])])
kaleido.write_fig_sync(fig, path="figure.png")
```

## Development guide

Below are examples of how to use Kaleido directly in your Python program.

If you want to export images of Plotly charts, it's not necessary to call
Kaleido directly; you can use functions in the Plotly library.
[See the Plotly documentation for instructions.](https://plotly.com/python/static-image-export/)

### Usage examples

```python
import asyncio
import kaleido
import plotly.express as px

async def main():
    # n is number of processes
    async with kaleido.Kaleido(n=4, timeout=90) as k:
        # fig is a plotly figure object
        fig = px.scatter(x=[1, 2, 3, 4], y=[2, 1, 4, 3])
        await k.write_fig(fig, path="./", opts={"format": "jpg"})

        # You can also use Kaleido.write_fig_from_object, where fig_objects is
        # an iterable of dicts each expanded to the write_fig arguments (fig,
        # path, opts, topojson):
        fig_objects = [
            {
                "fig": px.scatter(x=[1, 2, 3, 4], y=[2+i, 1+i, 4+i, 3+i]),
                "path": f"fig_{i}.jpg",
                "opts": {"format": "jpg"},
            } for i in range(10)
        ]
        await k.write_fig_from_object(fig_objects)

asyncio.run(main())

# other `kaleido.Kaleido` arguments:
# page_generator:  Change library version (see PageGenerators below)

# `Kaleido.write_fig()` arguments:
# - fig:              (required) A single plotly figure or an iterable.
# - path:             (optional) A directory (names auto-generated based on title)
#                     or a single file.
# - opts:             (optional) A dictionary with image options:
#                     `{"scale":..., "format":..., "width":..., "height":...,
#                       "fonts": [...]}`
#                     `fonts` is a list of paths to font files (.ttf/.otf/.woff).
#                     They are embedded into vector output (svg/pdf/eps) so
#                     charts render with the right font without installing it
#                     system-wide.
# - cancel_on_error:  (optional) If False (default), errors during rendering are collected
#                     and returned as a tuple after all figures are attempted.
#                     If True, the first error is raised immediately and any
#                     remaining renders are cancelled.
```

There are shortcut functions which can be used to generate images without
creating a `Kaleido()` object:

```python
import asyncio
import kaleido

# Pass `Kaleido()` constructor arguments (e.g. `n`, `timeout`) via `kopts`.
asyncio.run(
    kaleido.write_fig(
        fig,
        path="./",
        kopts={"n": 4},
    )
)
```

### Generate multiple images faster by reusing the same Chrome instance

By default, each call to `kaleido.write_fig_sync`, `kaleido.calc_fig_sync`,
or Plotly's `fig.write_image()` launches a fresh Chrome instance, renders
the figure, and shuts Chrome down again. If you're exporting many figures
in one script, the per-call Chrome startup and shutdown delay will
dominate runtime.

Call `kaleido.start_sync_server()` once at the top of your script to start
a single Chrome instance and reuse it across all subsequent sync
calls, including `fig.write_image()`:

```python
import kaleido
import plotly.graph_objects as go

kaleido.start_sync_server()   # one-time; Chrome stays warm

for i, fig in enumerate(figures):
    fig.write_image(f"fig_{i}.png")
```

Chrome is closed automatically when Python exits. To release it sooner
(for example, in a long-running service or Jupyter kernel), call
`kaleido.stop_sync_server()` explicitly.

### PageGenerators

The `page_generator` argument takes a `kaleido.PageGenerator()` to customize which versions
of plotly.js, MathJax, and other scripts are used when generating an image.
If plotly is installed, kaleido defaults to the version of plotly.js contained in that package. You can pass
`kaleido.PageGenerator(force_cdn=True)` to force use of a CDN version of plotly (which is
the default behavior if plotly is not installed).

```python
my_page = kaleido.PageGenerator(
    plotly="https://cdn.plot.ly/plotly-3.7.0.js",  # a fully qualified https:// or file:// link
    mathjax=False,  # False to disable, or a fully qualified link
    others=["a list of other script links to include"],
)
```
