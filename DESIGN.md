# Design System Strategy: Editorial Energy
 
## 1. Overview & Creative North Star
### Creative North Star: "The Radiant Editorial"
This design system moves beyond the utility of a standard energy provider into a high-end editorial experience. We are not just building a dashboard; we are curating a digital environment that feels as warm as a sunrise and as precise as a modern architectural blueprint. 
 
To break the "template" look, this system utilizes **intentional asymmetry**—offsetting imagery and typography to create dynamic movement. We avoid the rigid, boxy constraints of traditional grids by allowing elements to overlap and breathe. High-contrast typography scales and "tonal layering" replace the outdated use of borders and lines, ensuring the interface feels fluid, premium, and human-centric.
 
---
 
## 2. Colors: Tonal Depth & Radiant Warmth
Our palette is rooted in a vibrant orange and a sophisticated neutral foundation. The goal is to use color not just for branding, but to guide the user's eye through a logical hierarchy of "radiance."
 
### The Palette
- **Primary (Radiant Orange):** `#ac3500` (Core Action), `#ff6024` (Container/Impact). Use this for energy and focus.
- **Secondary (Warm Amber):** `#825500` (Subtle Action), `#ffb233` (Warning/Highlight). Use this to soften the primary heat.
- **Surface Neutrals:** From `surface-container-lowest` (`#ffffff`) to `surface-dim` (`#dadada`). These are the "sheets of paper" that form our UI.
 
### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders to separate sections or cards. Hierarchy is created through background color shifts. A `surface-container-low` component should sit on a `surface` background to define its boundaries. The absence of lines creates a sophisticated, "limitless" feel.
 
### Surface Hierarchy & Nesting
Treat the UI as a series of physical layers.
- **Layer 0 (Background):** `surface` (`#f9f9f9`)
- **Layer 1 (Main Content Area):** `surface-container-low` (`#f3f3f3`)
- **Layer 2 (Interactive Cards):** `surface-container-lowest` (`#ffffff`)
 
### The "Glass & Gradient" Rule
To add "soul" to the digital experience:
- **Glassmorphism:** For floating navigation or modal overlays, use semi-transparent surface colors with a `backdrop-filter: blur(20px)`.
- **Signature Textures:** Use subtle linear gradients (e.g., `#ac3500` to `#ff6024`) on primary CTAs and hero sections to avoid the flat, "default" look of hex-only fills.
 
---
 
## 3. Typography: Authoritative Clarity
The typography pairing balances the geometric precision of **Plus Jakarta Sans** for high-impact display with the approachable legibility of **Be Vietnam Pro** for long-form content.
 
- **Display (Plus Jakarta Sans):** Oversized and confident. Use `display-lg` (3.5rem) with tight letter-spacing for hero headlines to establish editorial authority.
- **Headlines (Plus Jakarta Sans):** Set at `headline-lg` (2rem), these should be bold and dark (`on-surface`), providing clear entry points into content.
- **Body (Be Vietnam Pro):** Reserved for information. `body-lg` (1rem) provides a generous reading experience.
- **Labels (Plus Jakarta Sans):** Small caps or bold weights at `label-md` (0.75rem) should be used for metadata to distinguish it from body text.
 
---
 
## 4. Elevation & Depth
We reject traditional "drop shadows" in favor of **Ambient Tonal Layering**. Depth should feel like natural light hitting fine paper.
 
- **The Layering Principle:** Soft, natural lift is achieved by placing a lighter surface (e.g., `surface-container-lowest`) onto a slightly darker one (e.g., `surface-container`).
- **Ambient Shadows:** If an element must float, use a multi-layered shadow:
  - `box-shadow: 0 10px 40px rgba(26, 28, 28, 0.06);`
  - The shadow color should never be pure black; use a tint of your `on-surface` color.
- **The "Ghost Border" Fallback:** If accessibility requires a container boundary, use `outline-variant` at 15% opacity. High-contrast, 100% opaque borders are forbidden.
 
---
 
## 5. Components: The Primitive Set
 
### Buttons
- **Primary:** Gradient fill (`#ac3500` to `#ff6024`), white text, `9999px` (full) roundedness. Padding: `1rem 2rem`.
- **Secondary:** Surface-container-highest fill with `on-surface` text. No border.
- **Tertiary:** Text-only with an underline that appears on hover, utilizing the `primary` color.
 
### Cards & Lists
- **Rule:** Forbid divider lines.
- **Implementation:** Use a `1.5rem` (`md`) rounded corner. Separate list items using `surface-container-low` backgrounds and vertical white space (32px minimum).
- **Hover State:** Lift the card slightly by shifting the background from `surface-container-lowest` to `white` and applying an ambient shadow.
 
### Input Fields
- **Styling:** Use a "soft-fill" approach. No bottom line or full border. Use `surface-container-high` as the background.
- **Active State:** A subtle `outline-variant` at 20% opacity and a `primary` color label.
 
### Chips
- **Selection Chips:** Use `secondary-fixed` (`#ffddb3`) for selected states to provide a warm, friendly glow that is distinct from the high-alert `primary` orange.
 
---
 
## 6. Do's and Don'ts
 
### Do
- **Do** use generous white space. If you think there is enough space, add 16px more.
- **Do** overlap elements. Let an image slightly bleed over the edge of a container to break the "grid feel."
- **Do** use the typography scale aggressively. The jump between `display-lg` and `body-md` should feel intentional and dramatic.
 
### Don't
- **Don't** use 1px solid black or grey borders.
- **Don't** use standard "Material Design" shadows. They are too heavy for this professional, modern aesthetic.
- **Don't** crowd the "Radiant Orange." It is a high-energy color; it needs neutral "breathing room" to maintain its premium status.
- **Don't** use sharp 0px corners. This system relies on the `1rem` (default) to `2rem` (lg) roundedness scale to feel "friendly and approachable."