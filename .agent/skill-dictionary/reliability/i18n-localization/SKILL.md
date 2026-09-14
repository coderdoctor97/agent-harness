---
name: i18n-localization
description: "Internationalize code with string externalization, ICU MessageFormat, Intl-based formatting, and RTL-safe layout for full locale coverage."
---

# I18n & Localization

## 1. Scope & Objective
- Make the product locale-safe: externalize every user-facing string, use ICU message formatting with correct pluralization, format dates/numbers via `Intl`, and keep the layout direction-agnostic.
- In scope: string catalogs, message format, locale-aware formatting, RTL/logical-property layout, coverage checks.
- Out of scope (delegate): producing translations (vendors/native speakers); content strategy.

## 2. Trigger Conditions
- Commands: "add German/Japanese support", "the dates are wrong", "we need RTL", "strings are hardcoded".
- Intent patterns: new locale; date/number/currency display bugs; RTL requirement; hardcoded-string audit.
- Orchestration tags: `i18n:extract`, `i18n:format`, `gate:i18n`.

## 3. Core Directives & Standards
1. **Zero hardcoded user-facing strings in code:** every visible string comes from a catalog with stable keys (`namespace.path`); extractor linters run in CI.
2. **ICU MessageFormat for messages:** plurals (`plural`/`select`), gender (`select`), and argument interpolation in one message — never word-order composition ("Hello, " + name); translators need full sentences with context comments.
3. **`Intl` for all formatting:** dates, numbers, currency, list formatting via the Intl API — no manual format strings (MM/DD vs DD/MM is not a "small fix").
4. **Direction-agnostic layout:** logical CSS properties (`margin-inline`, `inset-inline-start`) — no physical `left`/`right` assumptions; RTL is a test target, not an afterthought.
5. **Key stability is a contract:** renaming a key breaks translation memory; changes are deliberate, documented, and versioned.

## 4. Execution Workflow
1. **Intake & Analysis:** Inventory strings, locales, plural categories per locale, and RTL requirements; audit current hardcoded strings and manual date/number formatting.
2. **Implementation:** Extract strings to the catalog (extractor tool); convert messages to ICU (with context comments); replace manual formatting with `Intl`; swap physical CSS properties for logical ones; add the pseudo-locale.
3. **Validation:** Extractor reports 0 hardcoded user-facing strings; ICU parse check: 0 syntax errors; every locale has 100% key coverage (no missing-key warnings); pseudo-locale test (elongated strings + forced RTL) shows no layout breakage.

## 5. Antipatterns & Prohibited Behaviors
- String concatenation for i18n (`"You have " + n + " items"` — plural and word order broken).
- Manual date/number formatting ("we'll just swap the format string per locale").
- English fallback visible in production for unhandled locales.
- Using display text as the key (any copy edit wipes out the translations).
- Ignoring plural-category differences (English has two; Japanese has one; Arabic has six).

## 6. Definition of Done & Quality Guardrails
- Extractor: 0 hardcoded user-facing strings (CI-enforced).
- All locales at 100% key coverage (coverage report attached).
- Pseudo-locale test passes: elongated strings and forced RTL cause no overflow or overlap.
- All ICU messages parse (0 syntax errors); all date/number/currency output via `Intl` (audit).
