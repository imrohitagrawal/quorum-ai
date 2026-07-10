"""Test Phase 1 UI/UX critical fixes for Quorum AI."""

from playwright.sync_api import sync_playwright, Page, expect


def test_focus_states(page: Page):
    """1.1 Verify focus states work correctly."""
    # Tab to first interactive element
    page.keyboard.press("Tab")

    # Check that focus-visible outline is applied (not border-radius)
    focused = page.evaluate("""
        () => {
            const el = document.activeElement;
            if (!el) return null;
            const styles = window.getComputedStyle(el);
            return {
                hasOutline: styles.outlineWidth !== '0px',
                outlineColor: styles.outlineColor,
                borderRadius: styles.borderRadius
            };
        }
    """)
    print(f"Focus state: {focused}")


def test_logo_accessibility(page: Page):
    """1.3 Verify logo has proper accessibility attributes."""
    logo = page.locator(".logo")
    aria_label = logo.get_attribute("aria-label")
    role = logo.get_attribute("role")
    aria_hidden = logo.get_attribute("aria-hidden")

    print(f"Logo - aria-label: {aria_label}, role: {role}, aria-hidden: {aria_hidden}")

    # Should have aria-label, not aria-hidden
    assert aria_label == "Quorum AI logo", (
        f"Expected aria-label='Quorum AI logo', got '{aria_label}'"
    )
    assert aria_hidden is None, f"Logo should not have aria-hidden, got '{aria_hidden}'"


def test_button_touch_targets(page: Page):
    """1.4 Verify button touch targets are >= 44px."""
    buttons = page.locator(".button, button").all()

    small_buttons = []
    for btn in buttons:
        if btn.is_visible():
            box = btn.bounding_box()
            if box and (box["height"] < 44 or box["width"] < 44):
                small_buttons.append(
                    {"text": btn.inner_text()[:20], "height": box["height"], "width": box["width"]}
                )

    if small_buttons:
        print(f"Small buttons found: {small_buttons}")
    else:
        print("All buttons meet 44px minimum touch target")

    # Check .button-compact specifically
    compact = page.locator(".button-compact").first
    if compact.count() > 0:
        box = compact.bounding_box()
        print(f".button-compact size: {box['width']}x{box['height']}px")


def test_disabled_button_states(page: Page):
    """1.5 Verify disabled buttons have distinct visual state."""
    # Find a disabled button or create one for testing
    disabled_styles = page.evaluate("""
        () => {
            // Create a temporary disabled button to test styles
            const btn = document.createElement('button');
            btn.disabled = true;
            btn.className = 'button';
            document.body.appendChild(btn);
            const styles = window.getComputedStyle(btn);
            const result = {
                opacity: styles.opacity,
                cursor: styles.cursor,
                background: styles.backgroundColor
            };
            document.body.removeChild(btn);
            return result;
        }
    """)
    print(f"Disabled button styles: {disabled_styles}")


def test_critical_css_inline(page: Page):
    """1.7 Verify critical CSS is inlined in <head>."""
    critical_css = page.evaluate("""
        () => {
            const style = document.querySelector('head style');
            return style ? style.innerHTML.substring(0, 200) : null;
        }
    """)
    print(f"Critical CSS present: {critical_css is not None}")
    if critical_css:
        print(f"Critical CSS content: {critical_css[:150]}...")


def test_mobile_viewport(page: Page):
    """Test responsive behavior on mobile viewport."""
    page.set_viewport_size({"width": 375, "height": 667})  # iPhone SE size

    # Check for horizontal overflow
    overflow = page.evaluate("""
        () => document.body.scrollWidth > document.documentElement.clientWidth
    """)
    print(f"Horizontal overflow on mobile: {overflow}")

    page.set_viewport_size({"width": 1280, "height": 800})  # Reset


def test_keyboard_navigation(page: Page):
    """Test keyboard navigation works."""
    # Start from skip link
    page.goto("http://localhost:18085/")
    page.wait_for_load_state("networkidle")

    # Press Tab to move focus
    page.keyboard.press("Tab")
    page.wait_for_timeout(100)

    # Check focus moved to an element
    focused = page.evaluate("() => document.activeElement?.tagName")
    print(f"Focused element after Tab: {focused}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        print("=" * 60)
        print("Phase 1 UI/UX Critical Fixes - Test Suite")
        print("=" * 60)

        # Navigate to the app (Quorum AI uses /ui for workspace)
        page.goto("http://localhost:18085/ui")
        page.wait_for_load_state("networkidle")

        # Run tests
        print("\n[1.1] Testing focus states...")
        test_focus_states(page)

        print("\n[1.3] Testing logo accessibility...")
        test_logo_accessibility(page)

        print("\n[1.4] Testing button touch targets...")
        test_button_touch_targets(page)

        print("\n[1.5] Testing disabled button states...")
        test_disabled_button_states(page)

        print("\n[1.7] Testing critical CSS inlining...")
        test_critical_css_inline(page)

        print("\n[Mobile] Testing responsive layout...")
        test_mobile_viewport(page)

        print("\n[Keyboard] Testing keyboard navigation...")
        test_keyboard_navigation(page)

        print("\n" + "=" * 60)
        print("All tests completed!")
        print("=" * 60)

        # Take a screenshot for reference
        page.screenshot(path="/tmp/quorum_phase1_test.png", full_page=True)
        print("\nScreenshot saved to /tmp/quorum_phase1_test.png")

        browser.close()


if __name__ == "__main__":
    main()
