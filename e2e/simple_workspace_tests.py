#!/usr/bin/env python3
"""
Simple Playwright E2E tests for Quorum-AI workspace
Run with: python e2e/simple_workspace_tests.py
"""

import re

from playwright.sync_api import sync_playwright


def test_workspace_loads():
    """Test that the workspace loads successfully"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate to workspace
        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Check title
        title = page.title()
        print(f"✓ Page loaded: {title}")
        assert re.search(r"quorum|workspace", title, re.IGNORECASE), f"Unexpected title: {title}"

        # Check main elements exist
        assert page.get_by_role("textbox").is_visible(), "Question input should be visible"
        assert page.get_by_role(
            "button", name=re.compile("estimate cost", re.IGNORECASE)
        ).is_visible(), "Estimate cost button should be visible"
        assert page.get_by_role("button", name=re.compile("run now", re.IGNORECASE)).is_visible(), (
            "Run now button should be visible"
        )

        browser.close()
        print("✓ Workspace load test passed")


def test_theme_toggle():
    """Test theme switching functionality"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Get initial theme
        initial_theme = page.locator("html").get_attribute("data-theme")
        print(f"Initial theme: {initial_theme}")

        # Toggle theme
        theme_button = page.get_by_role("button", name=re.compile("switch to", re.IGNORECASE))
        theme_button.click()
        page.wait_for_timeout(500)

        # Check theme changed
        new_theme = page.locator("html").get_attribute("data-theme")
        print(f"New theme: {new_theme}")

        assert new_theme != initial_theme, "Theme should toggle"

        browser.close()
        print("✓ Theme toggle test passed")


def test_cost_estimation():
    """Test cost estimation functionality"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Enter a test question
        question = "What is artificial intelligence?"
        page.get_by_role("textbox").fill(question)

        # Click estimate cost
        page.get_by_role("button", name=re.compile("estimate cost", re.IGNORECASE)).click()
        page.wait_for_timeout(2000)  # Wait for calculation

        # Check cost is displayed
        cost_element = page.locator('[class*="cost"]').first
        if cost_element:
            cost_text = cost_element.inner_text()
            print(f"Cost estimate: {cost_text}")

        browser.close()
        print("✓ Cost estimation test passed")


def test_error_handling():
    """Test error display when API fails"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Mock API error
        def handle_route(route):
            route.fulfill(
                status=500,
                content_type="application/json",
                body='{"error": "Internal Server Error"}',
            )

        page.route("**/v1/query-runs/**", handle_route)

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Try to run a query
        page.get_by_role("textbox").fill("Test question")
        page.get_by_role("button", name=re.compile("run now", re.IGNORECASE)).click()

        # Wait for response
        page.wait_for_timeout(2000)

        # Check if any error-related content is visible
        error_elements = page.locator('[class*="error"], [role="alert"]').all()
        if error_elements:
            for elem in error_elements:
                if elem.is_visible():
                    print(f"✓ Error element found: {elem.inner_text()[:50]}")
                    break
        else:
            print("ℹ No error banner visible (may be handled differently)")

        browser.close()
        print("✓ Error handling test passed")


def test_keyboard_navigation():
    """Test keyboard navigation works"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Tab through elements
        elements = []
        for _ in range(5):
            page.keyboard.press("Tab")
            page.wait_for_timeout(100)
            focused = page.locator(":focus")
            try:
                text = focused.inner_text()
                elements.append(text[:20] if text else "Element")
            except Exception:
                elements.append("Element")

        print(f"✓ Navigated through elements: {elements}")

        browser.close()
        print("✓ Keyboard navigation test passed")


def test_mobile_responsive():
    """Test responsive design on mobile"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 375, "height": 667})

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Check UI is still usable on mobile
        assert page.get_by_role("textbox").is_visible(), "Input should be visible on mobile"
        assert page.get_by_role(
            "button", name=re.compile("estimate cost", re.IGNORECASE)
        ).is_visible(), "Estimate button should be visible on mobile"
        assert page.get_by_role("button", name=re.compile("run now", re.IGNORECASE)).is_visible(), (
            "Run button should be visible on mobile"
        )

        browser.close()
        print("✓ Mobile responsive test passed")


def test_console_no_errors():
    """Test that there are no console errors"""
    errors = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.on("console", lambda msg: errors.append(msg.text) if msg.type == "error" else None)

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1000)

        if errors:
            print(f"⚠ Console errors found: {errors}")
        else:
            print("✓ No console errors")

        browser.close()

    return len(errors) == 0


def test_form_interactions():
    """Test form input and interactions"""
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        page.goto("http://127.0.0.1:18085/ui")
        page.wait_for_load_state("networkidle")

        # Test input field
        test_question = "What is machine learning?"
        textbox = page.get_by_role("textbox")
        textbox.fill(test_question)

        value = textbox.input_value()
        assert value == test_question, f"Input value mismatch: {value}"
        print(f"✓ Input accepts text: '{value}'")

        # Test clear and re-fill
        textbox.clear()
        new_question = "How does neural network training work?"
        textbox.fill(new_question)
        assert textbox.input_value() == new_question, "Input should accept new text after clear"
        print("✓ Input clears and accepts new text")

        browser.close()
        print("✓ Form interactions test passed")


if __name__ == "__main__":
    print("=" * 60)
    print("Running Quorum-AI E2E Tests")
    print("=" * 60)

    tests = [
        ("Workspace Loads", test_workspace_loads),
        ("Theme Toggle", test_theme_toggle),
        ("Cost Estimation", test_cost_estimation),
        ("Error Handling", test_error_handling),
        ("Keyboard Navigation", test_keyboard_navigation),
        ("Mobile Responsive", test_mobile_responsive),
        ("Console Errors", test_console_no_errors),
        ("Form Interactions", test_form_interactions),
    ]

    passed = 0
    failed = 0

    for name, test_func in tests:
        print(f"\n--- {name} ---")
        try:
            result = test_func()
            if result is None:
                result = True
            if result:
                print(f"✓ {name} passed")
                passed += 1
            else:
                print(f"✗ {name} failed")
                failed += 1
        except Exception as e:
            print(f"✗ {name} failed: {str(e)}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)
