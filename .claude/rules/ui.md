---
paths:
  - volscope/ui/**
description: Streamlit + Plotly UI conventions. Applies on every edit under volscope/ui/.
---

# Rules for `volscope/ui/`

## `st.metric` is forbidden

Truncates values to "45..." in narrow columns. Always use the custom
KPI helper:

```python
from volscope.ui.components.html_utils import kpi_grid_html, render_html
render_html(st, kpi_grid_html([
    ("LABEL", "$1,234,567", color_optional),
], variant="compact"))
```

## Plotly: `go` only — never `px`

```python
import plotly.graph_objects as go      # OK
import plotly.express as px            # REJECT
```

## Plotly fillcolor

- 8-char hex (`#00d4aa22`) is REJECTED by Plotly. Always use the
  `rgba()` helper at `volscope/ui/styles/theme.py:15`:

```python
from volscope.ui.styles.theme import COLORS, rgba
fillcolor=rgba(COLORS["accent"], 0.13)
```

## Fonts

- Numbers, tabular data, KPI values: `JetBrains Mono`. Always with
  `font-variant-numeric: tabular-nums`.
- UI chrome, labels, prose: `DM Sans`.
- Never use system default (looks unbranded).

## Streamlit forms + buttons

- Wrap inputs in `st.form(...)` when bundling 2+ inputs.
- `use_container_width=True` on action buttons.
- Set `label_visibility="collapsed"` when the label is redundant
  (e.g. ticker selectbox under a render_html label).

## Material Symbols ghost text

The fonts CDN can be slow. Don't reintroduce raw `material-symbols-outlined`
spans without the CSS fallback at `theme.py` (font-size: 0 + ::before).

## Read-only DB pattern (Phase 2.5+)

When the Bot dashboard reads from `bot_*` tables, the underlying
connection should be `read_only=True` to avoid contention with the
scheduler writer. (Not enforced yet; v0.6.0 C7.)

## Page docstrings

Every `volscope/ui/views/*.py` starts with a docstring:

```python
"""
Page X — one-line purpose.

WHY this page exists: <one sentence>.
WHEN to use it: <one sentence>.
WHAT it depends on: <list of DB tables / analytics functions>.
"""
```
