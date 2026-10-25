/* Home-only QR disclosure: mouse, keyboard and touch use the same button. */
document.querySelectorAll('[data-platform-qr]').forEach((wrapper) => {
    const button = wrapper.querySelector('button');
    const popup = wrapper.querySelector('.platform-qr-popup');
    let pinned = false;
    let dismissed = false;

    const show = () => {
        popup.hidden = false;
        button.setAttribute('aria-expanded', 'true');
    };
    const hide = () => {
        popup.hidden = true;
        button.setAttribute('aria-expanded', 'false');
    };

    wrapper.addEventListener('mouseenter', () => {
        if (!dismissed && window.matchMedia('(hover: hover)').matches) show();
    });
    wrapper.addEventListener('mouseleave', () => {
        dismissed = false;
        if (!pinned && !wrapper.contains(document.activeElement)) hide();
    });
    button.addEventListener('focus', () => {
        dismissed = false;
        show();
    });
    wrapper.addEventListener('focusout', (event) => {
        if (!wrapper.contains(event.relatedTarget)) {
            pinned = false;
            hide();
        }
    });
    button.addEventListener('click', () => {
        pinned = !pinned;
        if (pinned) {
            dismissed = false;
            show();
        } else {
            dismissed = true;
            hide();
        }
    });
    document.addEventListener('pointerdown', (event) => {
        if (!wrapper.contains(event.target)) {
            pinned = false;
            hide();
        }
    });
    document.addEventListener('keydown', (event) => {
        if (event.key === 'Escape' && !popup.hidden) {
            const focusWasInside = popup.contains(document.activeElement);
            pinned = false;
            if (focusWasInside) button.focus();
            dismissed = true;
            hide();
        }
    });
});
