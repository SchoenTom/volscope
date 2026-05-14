"""
Lightweight keyboard-shortcut injector for VolScope.

Streamlit doesn't natively expose keydown listeners, so we inject a small
JavaScript snippet into the page that intercepts a few global shortcuts and
clicks the corresponding sidebar nav radio. The shortcuts are intentionally
conservative — single-key bindings only outside text inputs:

    g c   → Command Center
    g d   → Discover
    g s   → Scope
    g n   → Scanner
    g h   → Heatmap
    g r   → Rotation
    g f   → Flow
    ?     → display the cheatsheet
    /     → focus first input on page

The 'g' prefix follows GitHub/Vim conventions and prevents collisions with
typing in any text field. The cheatsheet is rendered only when triggered;
the injector is otherwise zero-DOM.
"""
from __future__ import annotations

_SHORTCUTS_JS = r"""
<script>
(function () {
    if (window.__volscopeShortcutsBound) return;
    window.__volscopeShortcutsBound = true;
    let pendingG = false;
    let pendingTimer = null;

    document.addEventListener('keydown', function (e) {
        // Skip when user is typing into an input/textarea/contenteditable
        const t = e.target;
        const tag = (t && t.tagName ? t.tagName.toLowerCase() : '');
        if (tag === 'input' || tag === 'textarea' ||
            (t && t.isContentEditable)) return;

        const k = e.key.toLowerCase();

        if (k === '?') {
            const overlay = document.createElement('div');
            overlay.id = 'vs-cheatsheet';
            overlay.style.cssText = 'position:fixed;top:50%;left:50%;' +
                'transform:translate(-50%,-50%);background:#151620;' +
                'color:#e0e4ef;padding:24px 28px;border-radius:8px;' +
                'border:1px solid #1e2038;font-family:JetBrains Mono,monospace;' +
                'font-size:12px;z-index:9999;box-shadow:0 6px 32px rgba(0,0,0,.6);';
            overlay.innerHTML =
                '<div style="font-weight:700;margin-bottom:10px;color:#00d4aa;">' +
                'Keyboard Shortcuts</div>' +
                '<div>g c — Command Center</div>' +
                '<div>g d — Discover</div>' +
                '<div>g s — Scope</div>' +
                '<div>g n — Scanner</div>' +
                '<div>g h — Heatmap</div>' +
                '<div>g r — Rotation</div>' +
                '<div>g f — Flow</div>' +
                '<div>/   — focus search</div>' +
                '<div>?   — toggle this</div>' +
                '<div style="margin-top:10px;color:#8a8f9e;">' +
                'Click anywhere to dismiss.</div>';
            document.body.appendChild(overlay);
            const dismiss = () => overlay.remove();
            setTimeout(() => document.addEventListener('click', dismiss, {once: true}), 100);
            return;
        }

        if (k === '/') {
            const inp = document.querySelector('input[type=text],input:not([type])');
            if (inp) { inp.focus(); e.preventDefault(); }
            return;
        }

        if (pendingG) {
            const map = {c: 'Command', d: 'Discover', s: 'Scope', n: 'Scanner',
                         h: 'Heatmap', r: 'Rotation', f: 'Flow'};
            const target = map[k];
            pendingG = false;
            if (pendingTimer) { clearTimeout(pendingTimer); pendingTimer = null; }
            if (target) {
                const radios = document.querySelectorAll('[role="radio"]');
                radios.forEach(r => {
                    if (r.textContent && r.textContent.trim() === target) r.click();
                });
            }
            return;
        }
        if (k === 'g') {
            pendingG = true;
            pendingTimer = setTimeout(() => { pendingG = false; }, 1500);
        }
    });
})();
</script>
"""


def inject_keyboard_shortcuts() -> None:
    """Mount the keyboard-shortcut listener into the current Streamlit page.

    Call once per page render (cheap — guarded against double-binding via
    a window-scope flag). The listener handles 'g <letter>' navigation and
    '?' for the cheatsheet overlay.
    """
    import streamlit as st

    st.markdown(_SHORTCUTS_JS, unsafe_allow_html=True)
