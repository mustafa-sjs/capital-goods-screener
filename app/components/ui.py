"""Shared design system for the app — mirrors the original dashboard's
palette (teal identity, accessible pos/neg, ink hierarchy).

style_table() pre-formats every cell to a display string (st.dataframe's
Styler bridge skips format callables on None cells, so formatting must
happen before styling) and colors cells from the ORIGINAL numeric values.
No raw float and no literal "None" can reach the screen.
"""
import altair as alt
import pandas as pd
import streamlit as st

TEAL9, TEAL7, TEAL1 = '#0d3b3f', '#175d63', '#e3efef'
POS, NEG, WARN, INK2 = '#0a7d38', '#c0392b', '#b07100', '#4e5a5b'
SERIES = ['#2a78d6', '#1baf7a', '#eda100', '#4a3aa7', '#e34948']
# colour semantics (product spec): green/red are reserved for realised
# performance and improving/deteriorating fundamentals; valuation uses
# blue (cheaper) <-> orange (more expensive) so "cheap" never reads as
# an automatic buy signal.
VAL_CHEAP, VAL_EXP = '#2a78d6', '#e07b00'

CLASS_COLORS = {
    # valuation states — blue = cheaper, orange = more expensive (a discount
    # is a fact about price, not automatically good news)
    'deep discount': VAL_CHEAP, 'discount': '#4a90cf', 'fair': INK2,
    'premium': '#d98a2b', 'extreme premium': VAL_EXP,
    # fundamental states — green/red = improving/deteriorating
    'improving': POS, 'stable': INK2, 'deteriorating': NEG,
    # legacy five-state momentum labels (kept for the legacy dashboard)
    'emerging positive inflection': POS, 'established uptrend': '#1baf7a',
    'fading uptrend': WARN, 'emerging breakdown': NEG,
    'established downtrend': NEG, 'indeterminate': INK2,
    'insufficient data': INK2,
    # unified trend fields (src/features/momentum.simple_momentum_fields)
    'Uptrend': POS, 'Downtrend': NEG, 'No clear trend': INK2,
    'Strengthening': POS, 'Stable': INK2, 'Weakening': WARN,
    'New positive crossover': POS, 'New negative crossover': NEG,
    'No recent crossover': INK2,
    # momentum screener composite classes
    'strong': POS, 'neutral': INK2, 'weak': NEG,
    # data freshness
    'Current': INK2, 'Stale': WARN, 'Not available': INK2,
}


def page_header(title, description=None):
    """Restrained page title (~32px) + one-line purpose sentence."""
    st.markdown(f'<h1 style="font-size:32px;margin:0 0 2px">{title}</h1>',
                unsafe_allow_html=True)
    if description:
        st.markdown(f'<div style="color:{INK2};font-size:14px;'
                    f'margin-bottom:10px">{description}</div>',
                    unsafe_allow_html=True)


def section(title, help_text=None):
    """Lightweight section header — quieter than group_header, for use
    inside tabs where every block must not shout equally loudly."""
    h = (f'<span title="{help_text}" style="cursor:help;opacity:.6"> ⓘ</span>'
         if help_text else '')
    st.markdown(f'<div style="font-weight:650;font-size:15px;color:{TEAL9};'
                f'margin:12px 0 2px">{title}{h}</div>',
                unsafe_allow_html=True)


def group_header(display, subgroup=None):
    sub = (f'<span style="opacity:.75;font-weight:400;font-size:12px"> · {subgroup}</span>'
           if subgroup else '')
    st.markdown(
        f'<div style="background:{TEAL9};color:#fff;padding:6px 12px;'
        f'border-radius:6px;font-weight:650;margin:14px 0 4px">{display}{sub}</div>',
        unsafe_allow_html=True)


def basket_caption(s):
    arrow = ('<span style="color:#b07100;font-weight:600"> · ⚠ one peer moved '
             'far more than the rest</span>' if s.get('outlier') else '')
    ba = (f' · beta-adjusted {s["beta_adj"]:+.2f}%'
          if s.get('beta_adj') is not None else '')
    cw = (f' · correlation-weighted {s["cw"]:+.2f}%'
          if s.get('cw') is not None else '')
    st.markdown(
        f'<div style="color:{INK2};font-size:12.5px;font-style:italic;margin:2px 0 10px">'
        f'└ peer basket 1-day move: average <b>{s["eq"]:+.2f}%</b> · '
        f'median {s["median"]:+.2f}%{cw}{ba} · '
        f'{s["pos"]} up / {s["neg"]} down · best {s["best"][0]} {s["best"][1]:+.2f}% · '
        f'worst {s["worst"][0]} {s["worst"][1]:+.2f}% · average 30-day '
        f'correlation {s["avg_corr30"]}'
        f'{arrow}</div>', unsafe_allow_html=True)


def _isnull(v):
    return v is None or (isinstance(v, float) and pd.isna(v))


def _f(v, spec, null='–'):
    if _isnull(v):
        return null
    try:
        v = float(v)
    except (TypeError, ValueError):
        return str(v)
    if abs(v) < 5e-3 and spec.startswith('+'):
        v = 0.0
    return format(v, spec)


def _grad(v, vmin=-60, vmax=60, lo_rgb=(76, 175, 80), hi_rgb=(214, 92, 92)):
    """Two-ended gradient background: lo colour <- white -> hi colour."""
    if _isnull(v):
        return ''
    t = max(-1.0, min(1.0, 2 * (float(v) - vmin) / (vmax - vmin) - 1))
    if t <= 0:
        r, g, b = (int(255 + t * (255 - c)) for c in lo_rgb)
    else:
        r, g, b = (int(255 - t * (255 - c)) for c in hi_rgb)
    return f'background-color:rgb({r},{g},{b})'


def _grad_val(v, vmin=-60, vmax=60):
    """Valuation scale: blue (cheaper) <- white -> orange (more expensive)."""
    return _grad(v, vmin, vmax, lo_rgb=(90, 148, 214), hi_rgb=(224, 152, 74))


def style_table(df, pct_cols=(), num_cols=(), mult_cols=(), price_cols=(),
                signed_pct=(), pct_plain_cols=(), int_cols=(),
                class_cols=(), class_col=None, bold_rows=None,
                scale_col=None, val_scale_col=None):
    """Format + colour a display table.

    Colour semantics: green/red text = signed performance/fundamental change;
    class columns use CLASS_COLORS; scale_col = green/red background
    (performance rank); val_scale_col = blue/orange background (valuation:
    blue cheaper, orange more expensive). 'Not available' shown for missing
    text states; numeric gaps show '–' / 'NM'.
    """
    df = df.reset_index(drop=True)
    orig = df.copy()
    disp = df.copy()
    for c in pct_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, '+.1f') + '%')
    for c in signed_pct:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, '+.2f') + '%')
    for c in pct_plain_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, '.1f') + '%')
    for c in mult_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: 'NM' if _isnull(v) else _f(v, '.1f') + '×')
    for c in price_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, ',.2f'))
    for c in num_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, ',.2f'))
    for c in int_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, ',.0f'))
    disp = disp.astype(object).where(pd.notnull(disp), '–')

    colored = [c for c in list(pct_cols) + list(signed_pct) if c in disp]
    classy = [c for c in (list(class_cols) + ([class_col] if class_col else []))
              if c and c in disp]

    def _style(_):
        css = pd.DataFrame('', index=disp.index, columns=disp.columns)
        for c in colored:
            css[c] = orig[c].map(lambda v: '' if _isnull(v) or abs(float(v)) < 0.05 else
                                 (f'color:{POS}' if float(v) > 0 else f'color:{NEG}'))
        for c in classy:
            css[c] = orig[c].map(
                lambda v: f'color:{CLASS_COLORS.get(v, INK2)};font-weight:600')
        if scale_col and scale_col in disp:
            css[scale_col] = orig[scale_col].map(
                lambda v: ('color:#101314;' + _grad(v)) if not _isnull(v) else '')
        if val_scale_col and val_scale_col in disp:
            css[val_scale_col] = orig[val_scale_col].map(
                lambda v: ('color:#101314;' + _grad_val(v)) if not _isnull(v) else '')
        if bold_rows:
            for i in bold_rows:
                css.loc[i] = css.loc[i] + ';font-weight:700;background-color:rgba(23,93,99,.10)'
                css.loc[i] = css.loc[i].str.strip(';')
        return css

    return disp.style.apply(_style, axis=None)


def df_show(sty_or_df, height=None, help_map=None, pinned=('Company',)):
    """Render a (styled) frame. help_map {column: tooltip} adds an ⓘ tooltip
    per column header; pinned columns stay visible while scrolling."""
    kw = {'height': height} if height else {}
    cols = (sty_or_df.data.columns if hasattr(sty_or_df, 'data')
            else sty_or_df.columns)
    config = {}
    for c in cols:
        opts = {}
        if help_map and help_map.get(c):
            opts['help'] = help_map[c]
        if pinned and c in pinned:
            opts['pinned'] = True
        if opts:
            config[c] = st.column_config.Column(c, **opts)
    if config:
        kw['column_config'] = config
    st.dataframe(sty_or_df, hide_index=True, use_container_width=True, **kw)


def alt_theme():
    return {'config': {
        'axis': {'labelColor': INK2, 'titleColor': INK2, 'gridColor': '#e8ecec',
                 'labelFontSize': 11, 'titleFontSize': 12},
        'title': {'color': '#101314', 'fontSize': 14, 'anchor': 'start',
                  'fontWeight': 600},
        'view': {'stroke': None}, 'range': {'category': SERIES}}}


alt.themes.register('cg', alt_theme)
alt.themes.enable('cg')


def status_badge(text, kind='ok'):
    color = {'ok': POS, 'warn': WARN, 'bad': NEG}[kind]
    st.markdown(f'<span style="background:{color};color:#fff;padding:3px 10px;'
                f'border-radius:12px;font-size:12.5px;font-weight:600">{text}</span>',
                unsafe_allow_html=True)
