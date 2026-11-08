"""Hover help for the Living World tabs, in the markup Mantella's own settings use (its style.css draws the "?" icon
and shows the text on hover), so both look the same."""
import html


def tip(text: str, right: bool = False) -> str:
    """A "?" icon that shows text on hover. right=True opens it leftwards, for icons near the right edge: the hidden
    box still takes room, and one past the edge makes the whole page scroll sideways."""
    side = 'left:auto;right:0;' if right else ''
    return ('<div class="tooltip-container" role="tooltip"><span class="tooltip-icon" tabindex="0">?</span>'
            f'<div class="tooltip-content-left" style="{side}max-width:min(420px,80vw);white-space:normal">'
            f'<p>{html.escape(text).replace(chr(10), "<br>")}</p></div></div>')


def label(title: str, text: str, right: bool = False) -> str:
    """A field title with its "?" icon, for a gr.HTML placed above a component shown without its own label."""
    return f'<div style="display:flex;align-items:center;gap:4px;font-weight:600">{html.escape(title)}{tip(text, right)}</div>'


def heading(title: str, text: str, about: str = '') -> str:
    """A section heading with its "?" icon and an optional one-line explanation under it."""
    line = f'<p style="margin:2px 0 8px;opacity:.8">{html.escape(about)}</p>' if about else ''
    return f'<h2 style="display:flex;align-items:center;gap:6px;margin:18px 0 2px">{html.escape(title)}{tip(text)}</h2>{line}'


def intro(text: str, help_text: str) -> str:
    """The one-line description at the top of a page, with the page's "?" icon."""
    return (f'<div style="display:flex;align-items:center;gap:6px;margin:4px 0 10px;opacity:.85">'
            f'{html.escape(text)}{tip(help_text)}</div>')


def danger_css() -> str:
    """Mantella's stylesheet makes 'stop' buttons look like any other; buttons that delete or reset things carry the
    lw-danger class and stay red. Emitted once per page set."""
    return ('<style>button.lw-danger{background:#7f1d1d!important;border-color:#b91c1c!important;color:#fff!important}'
            'button.lw-danger:hover{background:#991b1b!important}'
            # buttons sized to their label (scale=0) keep it on one line instead of wrapping at the 160 px minimum
            'button[style*="flex-grow: 0"]{white-space:nowrap!important;flex-shrink:0!important;max-width:none!important;'
            'padding-left:16px!important;padding-right:16px!important}</style>')
