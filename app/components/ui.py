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

CLASS_COLORS = {
    'Cheap, improving fundamentals': POS,
    'Cheap but operationally weak': WARN,
    'Expensive, weakening momentum': NEG,
    'Expensive, fundamentals improving': TEAL7,
    'Fairly valued': INK2,
}


def group_header(display, subgroup=None):
    sub = (f'<span style="opacity:.75;font-weight:400;font-size:12px"> · {subgroup}</span>'
           if subgroup else '')
    st.markdown(
        f'<div style="background:{TEAL9};color:#fff;padding:6px 12px;'
        f'border-radius:6px;font-weight:650;margin:14px 0 4px">{display}{sub}</div>',
        unsafe_allow_html=True)


def basket_caption(s):
    arrow = ('<span style="color:#b07100;font-weight:600"> · ⚠ outlier move in basket</span>'
             if s.get('outlier') else '')
    st.markdown(
        f'<div style="color:{INK2};font-size:12.5px;font-style:italic;margin:2px 0 10px">'
        f'└ basket: eq <b>{s["eq"]:+.2f}%</b> · median {s["median"]:+.2f}% · '
        f'corr-wtd {s["cw"]:+.2f}% · β-adj {s["beta_adj"]:+.2f}% · '
        f'▲{s["pos"]} ▼{s["neg"]} · best {s["best"][0]} {s["best"][1]:+.2f}% · '
        f'worst {s["worst"][0]} {s["worst"][1]:+.2f}% · avg ρ30 {s["avg_corr30"]}'
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


def _grad(v, vmin=-60, vmax=60):
    """Green (discount) -> white -> red (premium) background."""
    if _isnull(v):
        return ''
    t = max(-1.0, min(1.0, 2 * (float(v) - vmin) / (vmax - vmin) - 1))
    if t <= 0:   # toward green
        r, g, b = int(255 + t * (255 - 76)), int(255 + t * (255 - 175)), int(255 + t * (255 - 80))
    else:        # toward red
        r, g, b = int(255 - t * (255 - 214)), int(255 - t * (255 - 92)), int(255 - t * (255 - 92))
    return f'background-color:rgb({r},{g},{b})'


def style_table(df, pct_cols=(), num_cols=(), mult_cols=(), price_cols=(),
                signed_pct=(), class_col=None, bold_rows=None, scale_col=None):
    df = df.reset_index(drop=True)
    orig = df.copy()
    disp = df.copy()
    for c in pct_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, '+.1f') + '%')
    for c in signed_pct:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, '+.2f') + '%')
    for c in mult_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: 'NM' if _isnull(v) else _f(v, '.1f') + '×')
    for c in price_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, ',.2f'))
    for c in num_cols:
        if c in disp: disp[c] = disp[c].map(lambda v: '–' if _isnull(v) else _f(v, ',.2f'))
    disp = disp.astype(object).where(pd.notnull(disp), '–')

    colored = [c for c in list(pct_cols) + list(signed_pct) if c in disp]

    def _style(_):
        css = pd.DataFrame('', index=disp.index, columns=disp.columns)
        for c in colored:
            css[c] = orig[c].map(lambda v: '' if _isnull(v) or abs(float(v)) < 0.05 else
                                 (f'color:{POS}' if float(v) > 0 else f'color:{NEG}'))
        if class_col and class_col in disp:
            css[class_col] = orig[class_col].map(
                lambda v: f'color:{CLASS_COLORS.get(v, INK2)};font-weight:600')
        if scale_col and scale_col in disp:
            css[scale_col] = orig[scale_col].map(
                lambda v: ('color:#101314;' + _grad(v)) if not _isnull(v) else '')
        if bold_rows:
            for i in bold_rows:
                css.loc[i] = css.loc[i] + ';font-weight:700;background-color:rgba(23,93,99,.10)'
                css.loc[i] = css.loc[i].str.strip(';')
        return css

    return disp.style.apply(_style, axis=None)


def df_show(sty_or_df, height=None):
    kw = {'height': height} if height else {}
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
