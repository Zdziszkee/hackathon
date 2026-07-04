"""Lucide-style stroke icons (inline SVG, currentColor).

Lucide icons use a 24x24 viewBox, no fill, stroke=currentColor, stroke-width=2,
round caps/joins. Each helper returns an inline-SVG string sized via ``size``
(px). Color inherits from the surrounding element via ``color``.
"""

from __future__ import annotations

__all__ = [
    "Icon",
    "ic_activity",
    "ic_alert",
    "ic_bar_chart",
    "ic_boxes",
    "ic_building",
    "ic_check",
    "ic_chevron_down",
    "ic_dashed",
    "ic_error",
    "ic_factory",
    "ic_file_text",
    "ic_gauge",
    "ic_globe",
    "ic_info",
    "ic_map_pin",
    "ic_minus",
    "ic_newspaper",
    "ic_scale",
    "ic_search",
    "ic_shield",
    "ic_trending",
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


def ic_building(size: int = 16) -> str:
    return Icon(
        size,
        '<rect width="16" height="20" x="4" y="2" rx="2"/>'
        '<path d="M9 22v-4h6v4"/><path d="M8 6h.01"/><path d="M16 6h.01"/>'
        '<path d="M12 6h.01"/><path d="M12 10h.01"/><path d="M12 14h.01"/>'
        '<path d="M16 10h.01"/><path d="M16 14h.01"/><path d="M8 10h.01"/>'
        '<path d="M8 14h.01"/>',
    )


def ic_shield(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
    )


def ic_trending(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M22 7 8.5 20.5 5 17"/>'
        '<path d="m21 5-9 9-2-2"/>'
        '<path d="M3 21h18"/><path d="M3 3v18"/>',
    )


def ic_newspaper(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M15 18h1a1 1 0 0 0 1-1v-3h1a2 2 0 0 0 0-4h-1v-3a1 1 0 0 0-1-1h-7l-4 4v9a1 1 0 0 0 1 1"/>'
        '<path d="M3 27h2"/>',
    )


def ic_scale(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="m16 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="m2 16 3-8 3 8c-.87.65-1.92 1-3 1s-2.13-.35-3-1Z"/>'
        '<path d="M7 21h10"/><path d="m12 3 3 3h-3"/><path d="M12 21V6"/>',
    )


def ic_boxes(size: int = 16) -> str:
    return Icon(
        size,
        '<path d="M2.97 12.92A2 2 0 0 0 2 14.63a32 32 0 0 0 4 13.18 2 2 0 0 0 1.76 1.06c3.84 0 7.4-.67 10.49-1.46a2 2 0 0 0 1.43-1.4c.34-1.18.59-2.42.59-3.64a32 32 0 0 0-4-13.18 2 2 0 0 0-2.32-1.41"/><rect width="20" height="12" x="2" y="6" rx="2"/>',
    )


def ic_bar_chart(size: int = 16) -> str:
    return Icon(
        size,
        '<line x1="12" x2="12" y1="20" y2="10"/>'
        '<line x1="18" x2="18" y1="20" y2="4"/>'
        '<line x1="6" x2="6" y1="20" y2="16"/>',
    )


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
    return Icon(
        size,
        '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
    )


def ic_globe(size: int = 16) -> str:
    return Icon(
        size,
        '<circle cx="12" cy="12" r="10"/>'
        '<path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/>'
        '<path d="M2 12h20"/>',
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
