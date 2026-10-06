# cockpit (`chrysa.cockpit`)

Source of truth for the herdr setup (see `work/specs/2026-10-06-cockpit-design.md`).

- `palette.toml`: every color and project slot, used by all surfaces.
- `templates/`: files rendered from the palette with `{{section.key}}` placeholders.
- `render.py <template>`: prints a rendered template.

Today `templates/config.toml` renders the current herdr config byte for byte
(`tests/test_cockpit_render.py`). `setup` (write + reload) and `status` (drift
report) are the next steps of the plan.
