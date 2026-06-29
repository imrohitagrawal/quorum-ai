# 🎯 UI Fix Implementation Plan
*Created: 2026-06-30*
*Based on UI/UX Audit Report*

## 📋 Overview
This plan organizes all UI fixes into 4 distinct phases, each requiring separate focus and implementation. Fixes are ordered by impact and dependency.

---

## 🚨 Phase 1: Critical Issues - Accessibility & Performance
*Estimated Time: 2-3 hours*
*Goal: Address WCAG violations and core performance issues*

### 1.1 Focus States Fix [app.css:1374-1381]
```diff
- :focus-visible {
-   outline: 3px solid var(--focus-ring);
-   outline-offset: 3px;
-   border-radius: var(--radius-xs);
- }
+ :focus-visible {
+   outline: 3px solid var(--focus-ring);
+   outline-offset: 3px;
+   /* Removed border-radius for consistent focus rings */
+ }
```

### 1.2 Dynamic Type Support [app.css:135]
```diff
+ html {
+   -webkit-text-size-adjust: 100%;
+ }

 body {
   min-height: 100vh;
   background: var(--bg);
   color: var(--ink);
```

### 1.3 Alternative Text [workspace.html:25]
```diff
- <div class="logo" aria-hidden="true">Q</div>
+ <div class="logo" aria-label="Quorum AI logo">Q</div>
```

### 1.4 Button Touch Targets [app.css:830]
```diff
- .button-compact { min-width: 44px; min-height: 36px; padding: 0 var(--space-4); font-size: 0.85rem; }
+ .button-compact { min-width: 44px; min-height: 44px; padding: 0 var(--space-4); font-size: 0.85rem; }
```

### 1.5 Loading States [app.css:793-794]
```diff
- .button:disabled { cursor: not-allowed; opacity: 0.6; }
+ .button:disabled { 
+   cursor: not-allowed; 
+   opacity: 0.5;
+   background: var(--line) !important;
+   border-color: var(--line) !important;
+ }
```

### 1.6 Font Loading [workspace.html:9]
```diff
- <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Manrope:wght@400;500;600;700;800&display=swap">
+ <link href="https://fonts.googleapis.com/css2?family=Instrument+Serif:ital@0;1&family=Manrope:wght@400;500;600;700;800&display=swap">
```
> Note: Add `&display=swap` parameter if not already present

### 1.7 Critical CSS Inlining [workspace.html:11-17]
```diff
- <style>
-   /* Inline accessibility-critical rules so the page remains usable
-      even if the external stylesheet fails to load. */
-   :focus-visible { outline: 3px solid var(--focus-ring, #4a6cf7); outline-offset: 3px; }
-   :focus { outline: 3px solid var(--focus-ring, #4a6cf7); outline-offset: 3px; }
-   .button, button, .toggle, .info-icon { min-width: 44px; min-height: 44px; }
- </style>
+ <style>
+   /* Inline accessibility-critical rules */
+   :focus-visible { outline: 3px solid var(--focus-ring, #4a6cf7); outline-offset: 3px; }
+   :focus { outline: 3px solid var(--focus-ring, #4a6cf7); outline-offset: 3px; }
+   .button, button, .toggle, .info-icon { min-width: 44px; min-height: 44px; }
+   
+   /* Critical above-the-fold styles */
+   body { font-family: var(--font-sans); font-size: 16px; line-height: 1.5; }
+   .panel { background: var(--panel); backdrop-filter: blur(24px); }
+   .topbar { background: var(--panel); backdrop-filter: blur(24px); }
+ </style>
```

**Phase 1 Checklist:**
- [ ] Focus rings fixed
- [ ] iOS text zoom fixed
- [ ] Alt text added
- [ ] All touch targets ≥44px
- [ ] Disabled states improved
- [ ] Fonts load without FOIT
- [ ] Critical CSS inlined

---

## ⚠️ Phase 2: High Priority Issues - Layout & Typography
*Estimated Time: 2-3 hours*
*Goal: Improve mobile responsiveness and visual hierarchy*

### 2.1 Safe Area Handling [app.css:1384-1398]
```diff
@media (max-width: 600px) {
  .shell { width: calc(100vw - var(--space-5)); }
+ 
+   /* Add safe area insets for iOS/Android */
+   @supports (padding: max(0px)) {
+     .shell {
+       padding-top: max(var(--space-6), env(safe-area-inset-top));
+       padding-bottom: max(var(--space-8), env(safe-area-inset-bottom));
+     }
+     .topbar {
+       padding-top: max(var(--space-4), env(safe-area-inset-top));
+     }
+   }
}
```

### 2.2 Horizontal Scrolling Fix [app.css:1384-1398]
```diff
@media (max-width: 600px) {
  .shell { width: calc(100vw - var(--space-5)); }
+   body { overflow-x: hidden; }
+   .model-grid, .meta-grid { overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .brand-copy p { font-size: 0.8rem; -webkit-line-clamp: 4; }
}
```

### 2.3 Line Length Constraints [app.css:168-173]
```diff
.shell {
-  width: min(1280px, calc(100vw - var(--space-7)));
+  width: min(1280px, 80ch, calc(100vw - var(--space-7)));
  margin: var(--space-6) auto var(--space-8);
  display: flex;
  flex-direction: column;
  gap: var(--space-5);
}
```

### 2.4 Font Weight Hierarchy
```diff
.brand-copy h1 {
  margin: 0;
-  font-family: var(--font-serif);
-  font-size: clamp(1.9rem, 3.5vw, 2.6rem);
-  font-weight: 500;
+  font-family: var(--font-serif);
+  font-size: clamp(1.9rem, 3.5vw, 2.6rem);
+  font-weight: 700; /* Increased from 500 */
  line-height: 1;
  letter-spacing: -0.01em;
}
```

### 2.5 Heading Standardization
```diff
/* Update all headings */
h1, h2, h3 { font-weight: 700 !important; }
h4, h5, h6 { font-weight: 600 !important; }
.panel h2 {
-  font-weight: 500;
+  font-weight: 700;
  font-size: 1.7rem;
}
```

**Phase 2 Checklist:**
- [ ] Safe areas implemented
- [ ] No horizontal scroll
- [ ] Line length optimized
- [ ] Font weights standardized
- [ ] Visual hierarchy improved

---

## 🔧 Phase 3: Medium Priority Issues - Color & Forms
*Estimated Time: 2 hours*
*Goal: Enhance color accessibility and form UX*

### 3.1 Color Contrast Audit
```css
/* Add to design tokens for better contrast */
:root {
  /* Ensure dark mode contrasts */
  --ink-light: #f4eee7;
  --panel-darker: rgba(25, 29, 35, 0.95);
}
```

### 3.2 Semantic Tokens Implementation
```diff
.replace-raw-hex {
-  background: #fffaf5;
+  background: var(--bg-light);
-  color: #10161f;
+  color: var(--ink-dark);
}
```

### 3.3 Real-time Form Validation [workspace.html:84]
```diff
<textarea
  id="query-text"
  placeholder="Ask a source-backed business, technical, or policy question. Press Ctrl+Enter (Cmd+Enter on Mac) to run."
  aria-describedby="query-validation-hint"
  maxlength="20000"
+ oninput="updateCharCount()"
></textarea>

+ <script>
+ function updateCharCount() {
+   const textarea = document.getElementById('query-text');
+   const counter = document.getElementById('query-char-count');
+   const remaining = 20000 - textarea.value.length;
+   counter.textContent = `${textarea.value.length} chars`;
+   counter.style.color = remaining < 1000 ? 'var(--warning)' : '';
+ }
+ </script>
```

### 3.4 Error State Improvements
```diff
.field label {
  font-weight: 600;
  font-size: 0.95rem;
+ transition: color var(--duration-fast) var(--bezier);
}

.field[data-error="true"] label {
+ color: var(--danger);
}
```

**Phase 3 Checklist:**
- [ ] Color contrast verified
- [ ] Semantic tokens implemented
- [ ] Real-time validation added
- [ ] Error states improved

---

## 📝 Phase 4: Low Priority Issues - Polish & Structure
*Estimated Time: 1-2 hours*
*Goal: Final polish and code organization*

### 4.1 Progress Indicator
```html
<!-- Add before main content -->
<div class="progress-indicator" style="display: none;">
  <span>Question</span>
  <span>Models</span>
  <span>Cost</span>
  <span>Results</span>
</div>
```

### 4.2 Error Placement [workspace.html:80]
```diff
              <textarea
                id="query-text"
                name="query_text"
                placeholder="Ask a source-backed..."
                aria-describedby="query-validation-hint"
                maxlength="20000"
              ></textarea>
+             <div id="query-error" class="field-error" style="display: none;"></div>
```

### 4.3 CSS Component Architecture
```css
/* Extract reusable components */
.component-button {
  /* Shared button styles */
}

.component-card {
  /* Shared card styles */
}
```

**Phase 4 Checklist:**
- [ ] Progress indicator added
- [ ] Errors inline with fields
- [ ] CSS components extracted
- [ ] Code improved

---

## 📈 Success Metrics

### Before vs After
| Metric | Before | After |
|--------|--------|-------|
| WCAG AA Compliance | 80% | 100% |
| Mobile Score | 75% | 95% |
| Performance (LCP) | 2.5s | <1.5s |
| CSS Validity | 95% | 100% |

### Testing Strategy
1. **Automated**: Lighthouse, axe-core
2. **Manual**: Keyboard navigation, mobile testing
3. **Accessibility**: Screen reader tests, color contrast

---

## 🔄 Next Steps

1. **Start with Phase 1** - Critical accessibility fixes
2. **Test thoroughly** after each phase
3. **Document changes** in commit messages
4. **Update audit report** with fixes applied

*End of Implementation Plan*