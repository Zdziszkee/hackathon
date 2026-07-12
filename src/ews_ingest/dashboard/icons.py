"""Carbon Design System icons (inline SVG, currentColor).

Carbon icons use a 32x32 viewBox, fill=currentColor.
Each helper returns an inline-SVG string sized via ``size`` (px).
Color inherits from the surrounding element via ``color``.
"""

from __future__ import annotations

__all__ = [
    "Icon",
    "ic_activity",
    "ic_alert",
    "ic_bar_chart",
    "ic_boxes",
    "ic_building",
    "ic_chart_up",
    "ic_check",
    "ic_chevron_down",
    "ic_dashed",
    "ic_dollar",
    "ic_error",
    "ic_factory",
    "ic_file_text",
    "ic_gauge",
    "ic_gavel",
    "ic_globe",
    "ic_info",
    "ic_landmark",
    "ic_line_chart",
    "ic_map_pin",
    "ic_message",
    "ic_minus",
    "ic_newspaper",
    "ic_percent",
    "ic_plus",
    "ic_scale",
    "ic_search",
    "ic_shield",
    "ic_trending",
    "ic_truck",
    "ic_user_minus",
    "ic_users",
    "ic_zap",
]

_VIEWBOX = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
_VIEWBOX += 'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'


def Icon(size: int, paths: str) -> str:
    """Wrap raw SVG path markup in a sized inline SVG."""
    return f'<svg {_VIEWBOX} width="{size}" height="{size}" style="flex-shrink:0">{paths}</svg>'


def ic_chevron_down(size: int = 16) -> str:
    return Icon(size, '<path d="m6 9 6 6 6-6"/>')


def ic_check(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M21.801 10A10 10 0 1 1 17 3.335"/><path d="m9 11 3 3L22 4"/>',
    )


def ic_alert(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16'
        'a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
    )


def ic_error(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
    )


def ic_info(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/>',
    )


def ic_dashed(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M10.1 2.18a9.93 9.93 0 0 0 0 19.64"/>'
        '<path d="M13.9 2.18a9.93 9.93 0 0 1 0 19.64"/>'
        '<path d="m4.93 4.93 14.14 14.14"/>',
    )


def ic_minus(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/>',
    )


def ic_plus(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="12" cy="12" r="10"/><path d="M8 12h8"/><path d="M12 8v8"/>',
    )


def ic_building(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M28,2H16a2.002,2.002,0,0,0-2,2V14H4a2.002,2.002,0,0,0-2,2V30H30V4A2.0023,2.0023,0,0,0,28,2ZM9,28V21h4v7Zm19,0H15V20a1,1,0,0,0-1-1H8a1,1,0,0,0-1,1v8H4V16H16V4H28Z"/><path d="M18 8H20V10H18z"/><path d="M24 8H26V10H24z"/><path d="M18 14H20V16H18z"/><path d="M24 14H26V16H24z"/><path d="M18 20H20V22H18z"/><path d="M24 20H26V22H24z"/></svg>'


def ic_shield(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M14 16.59 11.41 14 10 15.41 14 19.41 22 11.41 20.59 10 14 16.59z"/><path d="M16,30,9.8242,26.7071A10.9818,10.9818,0,0,1,4,17V4A2.0021,2.0021,0,0,1,6,2H26a2.0021,2.0021,0,0,1,2,2V17a10.9818,10.9818,0,0,1-5.8242,9.7071ZM6,4V17a8.9852,8.9852,0,0,0,4.7656,7.9423L16,27.7333l5.2344-2.791A8.9852,8.9852,0,0,0,26,17V4Z"/></svg>'


def ic_trending(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M4.67,28l6.39-12,7.3,6.49a2,2,0,0,0,1.7.47,2,2,0,0,0,1.42-1.07L27,10.9,25.18,10,19.69,21l-7.3-6.49A2,2,0,0,0,10.71,14a2,2,0,0,0-1.42,1L4,25V2H2V28a2,2,0,0,0,2,2H30V28Z"/></svg>'


def ic_newspaper(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M25.7,9.3l-7-7C18.5,2.1,18.3,2,18,2H8C6.9,2,6,2.9,6,4v24c0,1.1,0.9,2,2,2h16c1.1,0,2-0.9,2-2V10C26,9.7,25.9,9.5,25.7,9.3	z M18,4.4l5.6,5.6H18V4.4z M24,28H8V4h8v6c0,1.1,0.9,2,2,2h6V28z"/><path d="M10 22H22V24H10z"/><path d="M10 16H22V18H10z"/></svg>'


def ic_scale(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M13,17H7a2,2,0,0,0-2,2v6a2,2,0,0,0,2,2h6a2,2,0,0,0,2-2V19A2,2,0,0,0,13,17ZM7,25V19h6v6Z"/><path d="M19,21v2h6a2,2,0,0,0,2-2V7a2,2,0,0,0-2-2H11A2,2,0,0,0,9,7v6h2V7H25V21"/></svg>'


def ic_boxes(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M26,30H6a2,2,0,0,1-2-2V16a2,2,0,0,1,2-2H9v2H6V28H26V16H23V14h3a2,2,0,0,1,2,2V28A2,2,0,0,1,26,30Z"/><path d="M13 20H19V22H13z"/><path d="M20.59 8.59 17 12.17 17 2 15 2 15 12.17 11.41 8.59 10 10 16 16 22 10 20.59 8.59z"/></svg>'


def ic_bar_chart(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M4,2H2V28a2,2,0,0,0,2,2H30V28H4V25H26V17H4V13H18V5H4ZM24,19v4H4V19ZM16,7v4H4V7Z"/></svg>'


def ic_activity(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M22 12h-2.48a2 2 0 0 0-1.93 1.46l-2.35 8.36a.5.5 0 0 1-.96 0L9.68 3.18a.5.5 0 0 0-.96 0l-2.35 8.36A2 2 0 0 1 4.45 13H2"/>',
    )


def ic_map_pin(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M20 10c0 4.993-5.539 10.193-7.399 11.799a1 1 0 0 1-1.202 0C9.539 20.193 4 14.993 4 10a8 8 0 0 1 16 0"/>'
        '<circle cx="12" cy="10" r="3"/>',
    )


def ic_factory(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M2 20a3 3 0 0 0 3-3V4a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v13a3 3 0 0 0 3 3h-2a3 3 0 0 0-3-3V8a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v9a3 3 0 0 0 3 3h2a3 3 0 0 0 3-3V8a1 1 0 0 1 1-1h2a1 1 0 0 1 1 1v9a3 3 0 0 0 3 3"/>',
    )


def ic_file_text(size: int = 14) -> str:
    return Icon(
        size,
        '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/>'
        '<path d="M14 2v4a2 2 0 0 0 2 2h4"/>'
        '<path d="M16 13H8"/><path d="M16 17H8"/><path d="M10 9H8"/>',
    )


def ic_search(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
    )


def ic_gauge(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M24 21H26V26H24z"/><path d="M20 16H22V26H20z"/><path d="M11,26a5.0059,5.0059,0,0,1-5-5H8a3,3,0,1,0,3-3V16a5,5,0,0,1,0,10Z"/><path d="M28,2H4A2.002,2.002,0,0,0,2,4V28a2.0023,2.0023,0,0,0,2,2H28a2.0027,2.0027,0,0,0,2-2V4A2.0023,2.0023,0,0,0,28,2Zm0,9H14V4H28ZM12,4v7H4V4ZM4,28V13H28.0007l.0013,15Z"/></svg>'


def ic_globe(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M14,4a7,7,0,1,1-7,7,7,7,0,0,1,7-7m0-2a9,9,0,1,0,9,9A9,9,0,0,0,14,2Z"/><path d="M28,11a13.9563,13.9563,0,0,0-4.1051-9.8949L22.4813,2.5187A11.9944,11.9944,0,0,1,5.5568,19.5194l-.0381-.0381L4.1051,20.8949A13.9563,13.9563,0,0,0,14,25v3H10v2H20V28H16V24.84A14.0094,14.0094,0,0,0,28,11Z"/></svg>'


def ic_dollar(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M21,12V10H17V7H15v3H13a2.002,2.002,0,0,0-2,2v3a2.002,2.002,0,0,0,2,2h6v3H11v2h4v3h2V22h2a2.0023,2.0023,0,0,0,2-2V17a2.002,2.002,0,0,0-2-2H13V12Z"/><path d="M16,4A12,12,0,1,1,4,16,12.0353,12.0353,0,0,1,16,4m0-2A14,14,0,1,0,30,16,14.0412,14.0412,0,0,0,16,2Z"/></svg>'


def ic_gavel(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="m14.5 12.5-8 8a2.119 2.119 0 1 1-3-3l8-8"/>'
        '<path d="m16 16 6-6"/><path d="m8 8 6-6"/>'
        '<path d="m9 7 8 8"/><path d="m21 11-8-8"/>'
        '<path d="M3 21h18"/>',
    )


def ic_landmark(size: int = 16) -> str:
    return Icon(
        size,
        '<line x1="3" x2="21" y1="22" y2="22"/>'
        '<line x1="6" x2="6" y1="18" y2="11"/>'
        '<line x1="10" x2="10" y1="18" y2="11"/>'
        '<line x1="14" x2="14" y1="18" y2="11"/>'
        '<line x1="18" x2="18" y1="18" y2="11"/>'
        '<polygon points="12 2 20 7 4 7"/>',
    )


def ic_line_chart(size: int = 16) -> str:
    return f'<svg viewBox="0 0 32 32" fill="currentColor" width="{size}" height="{size}" style="flex-shrink:0"><path d="M4.67,28l6.39-12,7.3,6.49a2,2,0,0,0,1.7.47,2,2,0,0,0,1.42-1.07L27,10.9,25.18,10,19.69,21l-7.3-6.49A2,2,0,0,0,10.71,14a2,2,0,0,0-1.42,1L4,25V2H2V28a2,2,0,0,0,2,2H30V28Z"/></svg>'


def ic_message(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>'
        '<path d="M8 12h.01"/><path d="M12 12h.01"/><path d="M16 12h.01"/>',
    )


def ic_truck(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M5 18H3c-.6 0-1-.4-1-1V7c0-.6.4-1 1-1h10c.6 0 1 .4 1 1v11"/>'
        '<path d="M14 9h4l4 4v4c0 .6-.4 1-1 1h-2"/>'
        '<circle cx="7" cy="18" r="2"/>'
        '<circle cx="17" cy="18" r="2"/>'
        '<path d="M9 18h5"/>',
    )


def ic_zap(size: int = 16) -> str:
    return Icon(
        size,
        '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    )


def ic_users(size: int = 16) -> str:
    """Two-person silhouette — insider / WARN layoffs / workforce signals."""
    return Icon(
        size,
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<path d="M22 21v-2a4 4 0 0 0-3-3.87"/>'
        '<path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    )


def ic_percent(size: int = 16) -> str:
    """Percent sign — credit spreads, rates, ratios."""
    return Icon(
        size,
        '<line x1="19" x2="5" y1="5" y2="19"/>'
        '<circle cx="6.5" cy="6.5" r="2.5"/>'
        '<circle cx="17.5" cy="17.5" r="2.5"/>',
    )


def ic_user_minus(size: int = 16) -> str:
    """Person with minus — layoffs, workforce reduction."""
    return Icon(
        size,
        '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/>'
        '<circle cx="9" cy="7" r="4"/>'
        '<line x1="22" x2="16" y1="11" y2="11"/>',
    )


def ic_chart_up(size: int = 16) -> str:
    """Upward-trending bar chart — earnings beat / positive surprise."""
    return Icon(
        size,
        '<line x1="3" x2="21" y1="21" y2="21"/>'
        '<polyline points="6 17 11 11 14 14 19 7"/>'
        '<polyline points="19 7 19 12 14 12"/>',
    )


# Status -> (icon_fn, accent_css_var_value)
STATUS_ICON = {
    "good": ic_check,
    "warning": ic_alert,
    "bad": ic_error,
    "demo": ic_dashed,
    "unavailable": ic_minus,
    "info": ic_info,
}
