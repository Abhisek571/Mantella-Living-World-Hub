"""Hover help for the Living World tabs, in the markup Mantella's own settings use (its style.css draws the "?" icon
and shows the text on hover), so both look the same."""
import html
import logging


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


BELIEF_WARNING = ('<b>! This changes what they believe, not the game.</b> Writing "married to the player" here will not '
                  'marry them. To really change marriage, home or follower status, do it in the game or with an Absolute '
                  'Command (G).')


def warning(text_html: str = BELIEF_WARNING) -> str:
    """The red warning box (text_html is already markup)."""
    return f'<div class="lw-warn">{text_html}</div>'


def red_lines(lines) -> str:
    """Plain lines shown in red, one per row; '' when there are none."""
    return ''.join(f'<div class="lw-red">! {html.escape(str(l))}</div>' for l in lines or [] if str(l).strip())


def about(text: str, help_text: str) -> str:
    """The one-line description at the top of a section (its title is the section's own header), with its "?" icon."""
    return f'<div class="lw-about">{html.escape(text)}{tip(help_text)}</div>'


def danger_css() -> str:
    """The Hub's own small stylesheet, scoped to .lw-hub (the Living World tab's pages) so Mantella's other tabs are
    untouched. Mantella's stylesheet makes 'stop' buttons look like any other; buttons that delete or reset things
    carry the lw-danger class: outlined in red and pushed to the end of their row, apart from the ordinary ones.
    Emitted once per page set."""
    red, red_dark = '#b91c1c', '#f87171'
    return ('<style>'
            # field titles: plain bold text instead of Mantella's green boxes, so the page reads calmly
            '.lw-hub{--block-title-background-fill:transparent;--block-title-text-color:var(--body-text-color);'
            '--block-title-padding:0 0 2px 0;--block-title-border-width:0}'
            # one button size everywhere (small and large buttons mixed in one row look broken)
            '.lw-hub button.sm{padding:var(--button-large-padding);font-size:var(--button-large-text-size);'
            'font-weight:var(--button-large-text-weight)}'
            # buttons beside a field sit on the field's line instead of stretching to the row's height
            '.lw-hub .stretch>button{align-self:flex-end}'
            # buttons sized to their label (scale=0) keep it on one line instead of wrapping at the 160 px minimum
            '.lw-hub button[style*="flex-grow: 0"]{white-space:nowrap!important;flex:0 0 auto!important;max-width:none!important}'
            f'.lw-hub button.lw-danger{{background:transparent!important;border:1px solid {red}!important;color:{red}!important}}'
            '.lw-hub button.lw-danger:hover{background:rgba(185,28,28,.1)!important}'
            f'.dark .lw-hub button.lw-danger{{border-color:{red_dark}!important;color:{red_dark}!important}}'
            '.lw-hub div:is(.stretch,.unequal-height)>button.lw-danger{margin-left:auto}'
            # parts redrawn every few seconds (Status) carry a permanent green "updating" line and an empty block's
            # minimum height: both look like a broken box
            '.lw-hub .wrap.generating{border:none!important}.lw-hub .prose.min{min-height:0}'
            # tables keep readable columns on a narrow window and scroll sideways inside their box
            '.lw-hub .table-wrap table{min-width:640px}'
            # a table written as markdown (Status: the token tables) fills its panel instead of shrinking to its text
            '.lw-hub .prose table{width:100%}'
            # the one-line description under a section header
            '.lw-hub .lw-about{display:flex;align-items:center;gap:6px;margin:0 0 6px;opacity:.85}'
            # the warning, mismatch lines and status boxes: one calm style, the words carry the meaning too
            f'.lw-hub .lw-warn{{border:1px solid rgba(185,28,28,.3);border-left:3px solid {red};background:rgba(185,28,28,.06);'
            'border-radius:6px;padding:6px 10px;margin:2px 0 8px;font-size:.92em}'
            f'.lw-hub .lw-warn b,.lw-hub .lw-red{{color:{red}}}'
            f'.dark .lw-hub .lw-warn b,.dark .lw-hub .lw-red{{color:{red_dark}}}'
            '.lw-hub .lw-red{margin:2px 0;font-size:.92em}'
            '.lw-hub .lw-state{display:inline-block;border:1px solid;border-left-width:3px;border-radius:6px;padding:4px 10px;'
            'margin:2px 0 6px;font-weight:600;color:var(--body-text-color)}'
            '.lw-hub .lw-state-active{border-color:#16a34a;background:rgba(22,163,74,.08)}'
            '.lw-hub .lw-state-pending{border-color:#ca8a04;background:rgba(202,138,4,.08)}'
            '.lw-hub .lw-state-none{border-color:rgba(128,128,128,.5);background:rgba(128,128,128,.06)}'
            # the NPC page's one-line summary of who is picked
            '.lw-hub .lw-summary{border:1px solid rgba(128,128,128,.35);border-radius:6px;padding:6px 10px;margin:4px 0}'
            '.lw-hub .lw-summary b{margin-right:6px}.lw-hub .lw-summary span{opacity:.85}'
            '</style>')


def safe(fn, fallback=''):
    """fn for a value drawn when a page loads (Gradio also calls it once while the page is built): an error shows the
    fallback and is logged, so one unreadable file can never stop a page from loading."""
    def call(*args):
        try:
            return fn(*args)
        except Exception as e:
            logging.getLogger('Mantella').warning(f"Living World: a page value could not be drawn ({e})")
            return fallback
    return call
