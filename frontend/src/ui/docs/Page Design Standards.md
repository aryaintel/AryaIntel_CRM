1) Purpose

A compact set of layout, spacing, and component rules for internal CRM pages so everything feels consistent (Salesforce-style: clean cards, clear hierarchy, and right-aligned primary actions).

2) Page anatomy

Page header (required)

Title: text-2xl font-semibold text-gray-900

Subtitle/help: text-sm text-gray-600

Right side: status, quick indicators, or page-level actions.

Content grid

Default: 2 columns on ≥ lg (left: navigation/list/create, right: detail).

Use grid grid-cols-1 lg:grid-cols-3 gap-4.

Left column spans 1; right column spans 2.

Cards

Card container: bg-white border rounded-2xl shadow-sm

Card header: px-4 py-3 border-b with a font-medium title.

Card body: p-4 (add space-y-4 for stacked groups).

Card footer: actions right-aligned; primary action last.

Entries/list panels below

Large tables/lists should live in a full-width card below the two-column area.

3) Forms

Label: block text-xs text-gray-600 mb-1

Text/number/date inputs: use shared .input class (see UI kit)

Select: use shared .select class

Checkbox/radio label: inline-flex items-center gap-2 text-sm

Group fields using grid grid-cols-1 md:grid-cols-N gap-3.

Place primary form actions in card footers, right-aligned.

4) Tables

Wrapper: overflow-auto

Header row: bg-gray-50 text-left text-xs text-gray-600

Body rows: divide-y

Keep cells padded: px-3 py-2.

Right-align row actions.

5) Buttons

Primary action: Indigo

Secondary action: Neutral bordered

Destructive: Rose outline or filled (rare)

Icon only: compact size="sm"

Use the shared <Button /> (UI kit). Never hand-write button classes.

6) Status & metadata

Use Badges (chips) for state like Active, Default.

Active: emerald tone

Default: indigo tone

Put badges in card headers when they describe the whole record; otherwise near the field they describe.

7) Spacing rhythm

Vertical rhythm by section: 16px (space-y-4)

Inside cards: 12–16px (we use p-4)

Dense tables: py-2 rows

8) Copy tone

Buttons: short verbs (“Save”, “Add price”, “Delete”).

Banners: brief, actionable (“Can’t save. Check required fields.”).

Place unintrusive help text in muted text-gray-600 small text.

9) Accessibility

Always associate <label> with form controls.

Don’t rely on color only; include text/aria labels.

Ensure focus styles remain visible (we keep default focus rings).