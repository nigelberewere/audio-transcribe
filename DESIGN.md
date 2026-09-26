# Zingsa Files Center — Design System Documentation

> This document outlines the actual, active design system for **Zingsa Files Center**, extracted directly from `app/static/style.css`, `index.html`, `admin.html`, `admin-login.html`, `documents.html`, and their companion scripts. Any agent or engineer implementing new features must adhere to these specifications to preserve visual and structural consistency.

---

## 1. Color Palette

The interface uses a warm, editorial slate-and-terracotta palette over a warm parchment background, accented by agency teal and muted status tints.

### Active Palette Tokens

Because of the CSS cascade in [app/static/style.css](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/static/style.css) (where trailing declarations override earlier lines), the effective runtime variables on `:root` are:

| Token | Hex Value | Name / Description | Primary Usages |
|---|---|---|---|
| `--ink` | `#18242b` | Deep Slate / Dark Charcoal | Primary headings, body copy, active text, primary button background, login dark rail background |
| `--muted` | `#6e7b80` | Neutral Slate Gray | Secondary text, metadata timestamps, form input labels, table column headers (`th`), upload drop zone subtitles |
| `--paper` | `#f4f0e8` | Warm Parchment | Primary application background (`body`) |
| `--card` | `#fffdf8` | Warm Off-White | Panel and card surface background (`.panel`, `.brand-card`, `.job`, `.stat`, `.document-row`) |
| `--line` | `#d8d1c4` | Warm Tan Border Line | Card borders, table cell bottom borders, quiet button borders, dividers |
| `--accent` | `#d4513b` | Terracotta / Rust Orange | Eyebrows (`.eyebrow`), primary button hover state, login accents, failed status text, error text (`.error`) |
| `--teal` | `#26736e` | Deep Agency Teal | Navigation links (`nav a`), download action links, document row name hover, progress bar indicator (`.bar i`), status pill text (`processing`, `done`) |
| `--blue` | `#e4f0fa` | Light Ice Blue | Processing status badge background (`.status.processing`), folder hover/active state (`.folder-link:hover`, `.folder-link.active`), brand mark background |
| `--green` | `#e4f4ec` | Soft Sage / Pale Mint | Completed status badge background (`.status.done`), document tags background (`.tags span`) |
| `--danger` | `#b9424b` | Crimson Red | Error text fallback, validation alerts |
| `--danger-bg` | `#f8e7e8` | Soft Pastel Pink / Red | Failed status badge background (`.status.failed`) |
| `--shadow` | `rgba(16, 40, 63, 0.08)` | Navy Shadow Tint | Subtle floating shadow for cards (`.job`, `.stat`, `.brand-card`, `.document-row`) |

### Additional Hardcoded Colors in Active Use

| Color Value | Context / Usage |
|---|---|
| `radial-gradient(circle at 15% 10%, #fff9ed 0, transparent 35%)` | Ambient subtle light gradient layered on top of `body` (`--paper`) |
| `#e5ddce` | Solid brutalist drop shadow on `.panel` (`box-shadow: 8px 8px 0 #e5ddce`) |
| `#c8bda9` | Dashed border outline on upload drop zones (`.drop { border: 2px dashed #c8bda9; }`) |
| `#e8e1d5` | Progress bar track background (`.bar { background: #e8e1d5; }`) |
| `#aebdc0` | Soft muted cyan-gray text in admin login rail copy |
| `#ffffff` | Pure white background for text inputs and dropdown selects |
| `rgba(16, 40, 63, 0.35)` | Backdrop mask tint for native modal dialogs (`dialog::backdrop`) |
| `rgba(38, 115, 110, 0.16)` | Focus ring glow for inputs (`outline: 3px solid rgba(38, 115, 110, .16)`) |

---

## 2. Typography

The application couples **Century Gothic** for titles/metrics with **Trebuchet MS** for body copy and UI controls.

### Font Families
- **Headings, Display, & Brand**: `'Century Gothic', 'Trebuchet MS', sans-serif`
- **Body & Controls**: `'Trebuchet MS', sans-serif`

### Type Scale

| Element / Class | Font Family | Size | Weight | Line Height / Letter Spacing | Color |
|---|---|---|---|---|---|
| **Login Hero Heading (`h1`)** | Century Gothic | `clamp(34px, 4vw, 58px)` | `700` (Bold) | `line-height: 1.03`, `letter-spacing: -0.04em` | `--ink` or white (rail) |
| **Page Title (`h1`)** | Century Gothic | `clamp(2rem, 5vw, 4.4rem)` (max 700px width) | `700` (Bold) | `line-height: 0.98` | `--ink` (`#18242b`) |
| **Section Title (`h2`)** | Century Gothic | `~24px` (1.5em browser default) | `700` (Bold) | `margin: 0 0 14px` | `--ink` (`#18242b`) |
| **Login Panel Title (`h2`)** | Century Gothic | `clamp(27px, 3vw, 38px)` | `700` (Bold) | `letter-spacing: -0.03em` | `--ink` (`#18242b`) |
| **Item Title (`h3` / `.job h3`)** | Trebuchet MS | `16px` | `700` (Bold) | `margin: 0 0 7px` | `--ink` (`#18242b`) |
| **Stat Metric (`.stat strong`)** | Century Gothic | `30px` | `700` (Bold) | Normal | `--ink` (`#18242b`) |
| **Eyebrow / Overline (`.eyebrow`)** | Trebuchet MS | `11px` | `700` (Bold) | `letter-spacing: 2px`, uppercase | `--accent` (`#d4513b`) |
| **Admin Kicker (`.admin-kicker`)** | Trebuchet MS | `10px` | `700` (Bold) | `letter-spacing: 0.14em`, uppercase | `--teal` (`#26736e`) |
| **Body Copy (`body`, `.login-copy`)** | Trebuchet MS | `15px` | `400` (Regular) | `line-height: 1.6` | `--ink` (`#18242b`) |
| **Table Headings (`th`)** | Trebuchet MS | `11px` | `700` (Bold) | `letter-spacing: 0.08em`, uppercase | `--muted` (`#6e7b80`) |
| **Table Data / Metadata (`td`, `.meta`)**| Trebuchet MS | `13px` | `400` (Regular) | Normal | `--muted` (`#6e7b80`) |
| **Form Labels (`label`)** | Trebuchet MS | `12px` | `700` (Bold) | Normal | `--muted` (`#6e7b80`) |
| **Buttons (`button`)** | Trebuchet MS | `14px` | `700` (Bold) | Normal | White or `--ink` |
| **Nav Links (`nav a`)** | Trebuchet MS | `13px` | `700` (Bold) | Normal | `--teal` (`#26736e`) |
| **Action Links (`.downloads a`)** | Trebuchet MS | `12px` | `700` (Bold) | Normal | `--teal` (`#26736e`) |
| **Badges / Pills (`.status`, `.tags span`)**| Trebuchet MS | `11px` | `700` (Bold) | `letter-spacing: 1px`, uppercase | Status dependent |

---

## 3. Spacing and Layout

### Container & Layout Constraints
- **Main App Shell (`.shell`)**:
  - `max-width: 1120px; margin: auto; padding: 38px 24px 70px;`
  - Responsive breakpoint (`@media (max-width: 760px)`): `padding: 22px 14px;`
- **Admin Shell (`.admin-shell`)**:
  - `max-width: 1180px; min-height: 100vh; padding: 28px;`
- **Shared Page Footer (`.page-footer`)**:
  - `margin-top: 48px; padding: 16px 0 8px; text-align: center; font-size: 12px; color: var(--muted); line-height: 1.5;`
  - A standard part of every authenticated page (`/home`, `/transcription`, `/documents`, `/admin`). Sits naturally after the main page content inside `.shell` (not fixed or sticky).

### Border-Radius Scale in Use
- `3px`: Text inputs (`input`), dropdowns (`select`), and action buttons (`button`).
- `6px`: Panels (`.panel` in active cascade).
- `8px`: Drop zones (`.drop`), document rows (`.document-row`), modal dialogs (`dialog`), login screen box (`.admin-login-screen`).
- `10px`: Progress bar indicator track (`.bar`).
- `12px`: Brand header (`.brand-card`), job cards (`.job`), stat cards (`.stat`), split login screen (`.login-screen`).
- `50%`: Circular logos (`.brand-logo`, `.admin-brand img`, `.secure-mark`).
- `999px`: Pills and badges (`.status`, `.tags span`).

### Standard Card / Container Styles
1. **Header Card (`.brand-card`)**:
   - `padding: 16px 18px;`
   - `background: var(--card); border: 1px solid var(--line); border-radius: 12px;`
   - `box-shadow: 0 8px 24px var(--shadow);`
2. **Main Panel (`.panel`)**:
   - `padding: 24px;`
   - `background: var(--card); border: 1px solid var(--line); border-radius: 6px;`
   - `box-shadow: 8px 8px 0 #e5ddce;`
3. **List Card (`.job`, `.document-row`)**:
   - `padding: 18px` (or `16px 18px`);
   - `background: var(--card); border: 1px solid var(--line);`
   - `border-radius: 12px` (jobs) / `8px` (documents);
   - `box-shadow: 0 6px 18px var(--shadow);`
4. **Metric Stat Card (`.stat`)**:
   - `padding: 20px;`
   - `background: var(--card); border: 1px solid var(--line); border-radius: 12px;`
   - `box-shadow: 0 6px 18px var(--shadow);`

---

## 4. Reusable Components

### 1. Header / Branding Bar
Displays branding and top navigation links. Used across authenticated views.

```html
<header class="brand-card">
  <div class="brand-lockup">
    <img class="brand-logo" src="/static/assets/logo.jpg" alt="ZINGSA logo">
    <div>
      <div class="brand-name">Zingsa Files Center</div>
      <div class="brand-subtitle">Meeting transcription</div>
    </div>
  </div>
  <nav>
    <a href="/home">Home</a>
    <a href="/transcription" class="nav-active">Transcription</a>
    <a href="/documents">Documents</a>
    <span id="userName" class="user-name">Firstname Surname</span>
    <button id="logout" class="quiet">Sign out</button>
  </nav>
</header>
```

#### User Badge (`.user-name`)
Renders the currently logged-in user's name on the top navigation bar as a clean, text-only pill badge. **Never includes a status dot, circle indicator, or icon before the name.** Automatically hides when empty (`.user-name:empty { display: none; }`).
```html
<span id="userName" class="user-name">Nigel Berewere</span>
```
*(Style: `display: inline-flex; align-items: center; padding: 5px 12px; background: var(--paper); border: 1px solid var(--line); border-radius: 999px; font-size: 13px; font-weight: 700; color: var(--ink);`)*

#### Module Cards Grid (`.modules-grid`, `.module-card`)
Used on the Home dashboard (`/home`) to present available application tools:
```html
<section class="modules-grid">
  <a href="/transcription" class="module-card">
    <div class="module-card-head">
      <div class="module-card-icon">
        <!-- SVG icon -->
      </div>
      <span class="module-card-badge">Audio &amp; Video</span>
    </div>
    <h3>Transcription</h3>
    <p>Transcribe meeting recordings</p>
    <div class="module-card-foot">
      <span>Open module</span>
      <span aria-hidden="true">&rarr;</span>
    </div>
  </a>
</section>
```
*(Card Style: `padding: 30px 28px; background: var(--card); border: 1px solid var(--line); border-radius: 12px; box-shadow: 0 6px 18px var(--shadow); transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;`)*
*(Hover: `transform: translateY(-4px); box-shadow: 0 14px 30px var(--shadow); border-color: var(--teal);`)*

### 2. Standard Card Container (`.panel`)
```html
<section class="panel">
  <!-- Content here -->
</section>
```

### 3. Metric Stat Card (`.stat`)
```html
<section id="stats" class="stats">
  <article class="stat">
    <strong>14</strong>
    <span>Active jobs</span>
  </article>
</section>
```

### 4. Primary & Secondary ("Quiet") Buttons
- **Primary Button**: Solid dark slate button turning terracotta on hover.
  ```html
  <button id="submitBtn">Add to queue</button>
  ```
  *(Style: `background: var(--ink); color: white; border: 0; border-radius: 3px; padding: 12px 16px; font: 700 14px 'Trebuchet MS'; cursor: pointer;`)*
  *(Hover: `background: var(--accent);`)*

- **Secondary ("Quiet") Button**: Ghost button with subtle border.
  ```html
  <button id="refreshBtn" class="quiet">Refresh</button>
  ```
  *(Style: `background: transparent; color: var(--ink); border: 1px solid var(--line); border-radius: 3px; padding: 12px 16px; font: 700 14px 'Trebuchet MS';`)*

### 5. Form Input, Select, and Labels
Forms use stacked labels with uppercase-feel bold micro-copy:
```html
<label>
  Model
  <select id="model">
    <option value="auto">Auto (queue policy)</option>
    <option value="large-v3">Force large-v3</option>
  </select>
</label>

<label>
  Initial prompt
  <input id="prompt" placeholder="Names, terminology, case numbers">
</label>
```
*(Label Style: `display: grid; gap: 7px; font-size: 12px; color: var(--muted); font-weight: bold;`)*
*(Input/Select Style: `border: 1px solid var(--line); background: #fff; padding: 12px; border-radius: 3px; font: inherit; color: inherit; width: 100%;`)*

### 6. Status Pills & Badges
Badges are rounded pills used to reflect job, document, and user states:
```html
<span class="status waiting">waiting</span>
<span class="status processing">processing</span>
<span class="status done">done</span>
<span class="status failed">failed</span>
```

#### Status Color Map:
| Status Class | Background Token | Text Color Token | Visual Appearance |
|---|---|---|---|
| `.status` (Default: `waiting`, `deleted`) | `--line` (`#d8d1c4`) | `--ink` (`#18242b`) | Neutral beige pill with dark slate text |
| `.status.processing` | `--blue` (`#e4f0fa`) | `--teal` (`#26736e`) | Pale ice-blue pill with deep teal text |
| `.status.done` | `--green` (`#e4f4ec`) | `--teal` (`#26736e`) | Pale mint pill with deep teal text |
| `.status.failed` | `--danger-bg` (`#f8e7e8`) | `--accent` (`#d4513b`) | Soft pink pill with terracotta text |

*(Tag Badges in DMS use: `.tags span { padding: 3px 7px; border-radius: 999px; background: var(--green); color: var(--teal); font-size: 11px; }`)*

### 7. Table Styling (Admin & Directory)
Tables must be wrapped in `.table-wrap` for responsive horizontal scrolling:
```html
<div class="table-wrap">
  <table>
    <thead>
      <tr>
        <th>Username</th>
        <th>Role</th>
        <th>Status</th>
        <th>Created</th>
        <th>Actions</th>
      </tr>
    </thead>
    <tbody id="rows">
      <tr>
        <td>john.doe</td>
        <td>
          <select><option value="user">User</option></select>
        </td>
        <td>
          <label class="switch"><input type="checkbox" checked><span>Active</span></label>
        </td>
        <td>Sep 24, 2026</td>
        <td><button class="quiet">Reset password</button></td>
      </tr>
    </tbody>
  </table>
</div>
```
*(Table Style: `width: 100%; border-collapse: collapse; font-size: 13px;`)*
*(Cell Style: `padding: 12px 10px; border-bottom: 1px solid var(--line); text-align: left; white-space: nowrap;`)*
*(Header Style: `color: var(--muted); font-size: 11px; letter-spacing: .08em; text-transform: uppercase;`)*

### 8. Drag-and-Drop Upload Zone
```html
<!-- Audio/Video Transcription Upload Zone -->
<div class="drop" id="drop">
  <strong>Drop files here to upload</strong>
  <span>MP3, WAV, M4A, MP4, MKV, OGG, FLAC, WEBM</span>
  <input id="file" type="file" accept="...">
</div>

<!-- Documents Repository Upload Zone (50MB Limit) -->
<section id="drop" class="panel drop document-drop">
  <strong>Drop files here to upload</strong>
  <span>PDF, Word, Excel, PowerPoint, text, and image files, up to 50MB</span>
  <input id="file" type="file" accept=".pdf,.doc,.docx,.xls,.xlsx,.ppt,.pptx,.txt,.csv,.rtf,.odt,.ods,.odp,.jpg,.jpeg,.png">
</section>
```
*(Style: `border: 2px dashed #c8bda9; border-radius: 8px; padding: 34px; text-align: center; display: grid; gap: 8px; color: var(--muted);`)*
- **Allowed Document Extensions**: `pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, rtf, odt, ods, odp, jpg, jpeg, png`
- **File Size Limit**: `50MB` (52,428,800 bytes), enforced on both client and server.

### 9. Empty State Pattern
Used when folders or lists have no records:
```html
<p class="meta">No documents in this folder.</p>
```
*(Style: `.meta { color: var(--muted); font-size: 13px; }`)*

### 10. Modal Dialogs (`<dialog>`)
Used for popups (e.g. create user, reset password, document version history):
```html
<dialog id="exampleDialog">
  <form id="exampleForm" method="dialog">
    <p class="eyebrow">CONTEXT</p>
    <h2>Dialog Title</h2>
    <!-- Fields -->
    <p class="error" id="formError"></p>
    <div class="dialog-actions">
      <button type="button" class="quiet" id="cancelBtn">Cancel</button>
      <button type="submit">Confirm</button>
    </div>
  </form>
</dialog>
```
*(Dialog Style: `width: min(620px, calc(100% - 28px)); padding: 24px; border: 1px solid var(--line); border-radius: 8px; color: var(--ink);`)*
*(Backdrop: `dialog::backdrop { background: rgba(16, 40, 63, .35); }`)*

### 11. Module Grid & Module Cards
Used on the Home dashboard (`/home`) to present available workspace modules:
```html
<section id="modulesGrid" class="modules-grid">
  <a href="/transcription" class="module-card">
    <div class="module-card-head">
      <div class="module-card-icon">
        <svg viewBox="0 0 24 24" width="24" height="24" stroke="currentColor" stroke-width="2" fill="none">...</svg>
      </div>
      <span class="module-card-badge">Audio & Video</span>
    </div>
    <h3>Transcription</h3>
    <p>Transcribe meeting recordings</p>
    <div class="module-card-foot">
      <span>Open module</span>
      <span aria-hidden="true">&rarr;</span>
    </div>
  </a>
</section>
```
*(Grid Style: `display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 18px;`)*
*(Card Style: `background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 22px; text-decoration: none; display: flex; flex-direction: column; transition: transform 0.16s ease, border-color 0.16s ease, box-shadow 0.16s ease;`)*
*(Card Hover: `border-color: var(--teal); transform: translateY(-2px); box-shadow: 0 10px 24px rgba(16, 40, 63, 0.1);`)*

### 10. Shared Minimal Footer (`.page-footer`)
Every authenticated view includes a single muted line at the bottom of `.shell`:
```html
<footer class="page-footer">
  Zingsa Files Center &middot; Internal use only
</footer>
```
*(Style: `margin-top: 48px; padding: 16px 0 8px; text-align: center; font-size: 12px; color: var(--muted); line-height: 1.5;`)*

### 11. Empty State (`.empty-state`)
Used in file lists and job queues when no items are present. Replaces raw single-line strings with an icon, heading, and guidance message:
```html
<div class="empty-state">
  <div class="empty-state-icon">
    <!-- SVG icon (folder or mic/waveform) -->
  </div>
  <p class="empty-state-title">No documents in this folder.</p>
  <p class="empty-state-guide">Drop a file above to get started</p>
</div>
```
*(Container: `display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 36px 20px; background: var(--card); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 4px 12px var(--shadow);`)*
*(Icon: `display: grid; place-items: center; width: 44px; height: 44px; border-radius: 10px; background: var(--blue); color: var(--teal); margin-bottom: 12px;`)*
*(Title: `font-size: 15px; font-weight: 700; color: var(--ink); margin: 0 0 4px;`)*
*(Guide: `font-size: 13px; color: var(--muted); margin: 0;`)*


---

## 5. Page Structure Convention

Every view in the system follows a predictable 3-tier hierarchy:
1. **Header Card**: Standardized lockup with brand name, section subtitle, and global navigation.
2. **Section Head**: Eyebrow badge over a large page heading, plus optional action buttons/breadcrumbs.
3. **Content Cards/Panels**: Grouped into `.panel`, multi-column layouts (`.document-layout`, `.admin-grid`), or card lists (`.jobs`, `.document-list`).

### Standard Page Skeleton

```html
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <link rel="icon" type="image/jpeg" href="/static/assets/logo.jpg">
  <title>Feature Title | Zingsa Files Center</title>
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
<main class="shell">

  <!-- 1. Header / Brand Bar -->
  <header class="brand-card">
    <div class="brand-lockup">
      <img class="brand-logo" src="/static/assets/logo.jpg" alt="ZINGSA logo">
      <div>
        <div class="brand-name">Zingsa Files Center</div>
        <div class="brand-subtitle">Feature Subtitle</div>
      </div>
    </div>
    <nav>
      <a href="/home">Home</a>
      <a href="/transcription">Transcription</a>
      <a href="/documents">Documents</a>
      <span id="userName" class="user-name">Firstname Surname</span>
      <button id="logout" class="quiet">Sign out</button>
    </nav>
  </header>

  <!-- 2. Section Heading -->
  <section class="section-head">
    <div>
      <p class="eyebrow">MODULE CONTEXT</p>
      <h1>Feature Title</h1>
      <p class="meta">Optional contextual description or breadcrumb</p>
    </div>
    <div class="header-actions">
      <button id="refreshBtn" class="quiet">Refresh</button>
      <button id="primaryActionBtn">New Action</button>
    </div>
  </section>

  <!-- 3. Main Content Panel(s) -->
  <section class="panel">
    <!-- Panel content -->
  </section>

  <!-- 4. Shared Minimal Footer -->
  <footer class="page-footer">
    Zingsa Files Center &middot; Internal use only
  </footer>

</main>

<!-- 5. Modals / Dialogs (Optional) -->
<dialog id="actionModal">
  <!-- Dialog content -->
</dialog>

<!-- 6. Client Script -->
<script src="/static/feature.js"></script>
</body>
</html>
```

---

## 6. Naming and File Conventions

- **Centralized CSS**: All styling is stored in a single file: [app/static/style.css](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/static/style.css). Do not create separate `.css` files for new pages; extend `style.css` so tokens and themes remain shared.
- **Dedicated Page Scripts**: Each HTML page has a 1-to-1 companion vanilla JavaScript file in [app/static/](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/static):
  - `index.html` $\rightarrow$ `app.js` (Sign in page & redirection)
  - `home.html` $\rightarrow$ `home.js` (Dashboard hub with module cards)
  - `transcription.html` $\rightarrow$ `transcription.js` (Transcription queue & uploads)
  - `documents.html` $\rightarrow$ `documents.js` (File repository & versioning)
  - `admin.html` $\rightarrow$ `admin.js` (Directory & administration)
  - `admin-login.html` $\rightarrow$ shares `admin.js` (Admin portal sign in)
- **Route & Template Wiring**:
  - FastAPI serves the page in [app/main.py](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/main.py) via a `FileResponse` or redirect:
    ```python
    @app.get("/home", response_class=HTMLResponse)
    def home_page(session: str | None = Cookie(default=None)) -> Response:
        if not _is_authenticated(session):
            return RedirectResponse("/", status_code=303)
        return FileResponse(Path(__file__).parent / "static" / "home.html")
    ```
- **Static Assets**: Logos and graphic assets live in `app/static/assets/`.
- **Pure Vanilla JS Standard**: Keep scripts free of heavy build tools or frameworks. Reuse existing micro-utilities:
  ```javascript
  const $ = (id) => document.getElementById(id);
  async function request(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
    return response.json();
  }
  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  }
  ```

---

## 7. Rules for New Features

1. **Reuse Existing CSS Classes**: Always use existing classes (`.panel`, `.brand-card`, `.section-head`, `.eyebrow`, `.quiet`, `.drop`, `.status`, `.table-wrap`, `.meta`, `.error`, `.stat`, `.tags`). Never create duplicate utility classes for existing concepts.
2. **Never Deviate from the Palette**: Do not introduce arbitrary new hex values or browser defaults (e.g. generic `#007bff` blue or `#28a745` green). Always reference the documented CSS variables (`var(--teal)`, `var(--accent)`, `var(--ink)`, `var(--paper)`, `var(--card)`, `var(--line)`).
3. **No Foreign Component Styles**: Do not introduce rounded pill buttons or custom neumorphic shadows. All cards must be `.panel`, `.brand-card`, `.stat`, or `.job`/`.document-row` clones; buttons must be standard `<button>` or `<button class="quiet">`.
4. **Preserve the Global Header & Navigation**: Every top-level page must include the `<header class="brand-card">` with the Zingsa logo, lockup, and navigation links (`Transcription`, `Documents`, `Sign out`).
5. **No External CSS Frameworks**: Do not introduce Tailwind, Bootstrap, or component libraries. Maintain the lightweight, zero-dependency vanilla architecture.
6. **User Badge Never Includes Status Dot**: The user-pill component in the top header (`.user-name`) must strictly render the user's name as plain text without any status dot, indicator icon, or leading pseudo-element (`::before`/`::after`). Never add a status dot to `.user-name`.
7. **Document Upload Limits and Constraints**: Documents repository uploads are restricted to the defined file types (`pdf, doc, docx, xls, xlsx, ppt, pptx, txt, csv, rtf, odt, ods, odp, jpg, jpeg, png`) with a strict `50MB` size limit. This constraint must always be enforced both client-side (with immediate UI feedback) and server-side (returning a clear 400 error and preventing any unallowed files or database rows from being created).
8. **PDF Tools & Document Lineage**: Any document generated through repository utilities (merging, splitting, watermarking, converting) must create a brand-new document record without modifying or overwriting source documents, must record source document IDs in `source_document_ids` for lineage tracking, and must log an audit entry (`document_merged`, `document_split`, `document_watermarked`, `document_converted`).
9. **Shared Page Footer**: Every top-level page (`Home`, `Transcription`, `Documents`, `Admin`) must include the `.page-footer` element at the bottom of the `.shell` container, styled with `var(--muted)` small text and sitting naturally after the content without sticky/fixed positioning.
10. **Rich Empty States**: Empty collection states in queues and file lists must render an `.empty-state` container comprising a small themed icon, a bold primary headline, and a secondary action guidance line (e.g. "Drop a file/recording above to get started").

---

## 8. Known Inconsistencies to Clean Up

When maintaining or refactoring the stylesheet, be aware of the following legacy inconsistencies currently present in [app/static/style.css](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/static/style.css):

1. **Dual `:root` Declarations and Trailing Minified Block (Line 196)**:
   - Line 49 defines a cool palette (`--ink: #10283f`, `--accent: #e4ad32` gold, `--teal: #147f83`).
   - Line 196 defines a minified block with a warm palette (`--ink: #18242b`, `--accent: #d4513b` terracotta, `--teal: #26736e`).
   - Due to the CSS cascade, line 196 wins for common variables, leaving unused declarations higher in the file.
2. **Inconsistent Border Radius**:
   - Lines 86–87 specify `border-radius: 6px` for inputs and buttons, but line 196 overrides them to `border-radius: 3px`.
   - `.panel` uses `border-radius: 12px` on line 82, but is overridden to `border-radius: 6px` on line 196. Document rows use `8px`, and jobs use `12px`.
3. **Card Shadow Styles**:
   - `.brand-card`, `.job`, `.stat`, and `.document-row` use soft blurred shadows (`box-shadow: 0 6px 18px var(--shadow)`).
   - `.panel` on line 196 was overridden to a solid brutalist shadow (`box-shadow: 8px 8px 0 #e5ddce`).
4. **Button Hover Color**:
   - Line 88 sets `button:hover { background: var(--teal); }`, whereas line 196 sets `button:hover { background: var(--accent); }`. The active behavior is terracotta hover (`var(--accent)`).
5. **Hardcoded Hex Values in Admin Login (Lines 1–48)**:
   - The `.admin-login-*` selectors manually hardcode `#18242b`, `#fffdf8`, `#d4513b`, `#26736e`, `#d8d1c4`, and `#6e7b80` instead of using the custom CSS properties (`var(--ink)`, `var(--card)`, etc.).
6. **Incomplete Status Pill Definition for `failed`**:
   - Line 107 set `.status.failed { background: var(--danger-bg); color: var(--danger); }`. Line 196 overrides `.status.failed { color: var(--accent); }` without declaring a background, resulting in `--accent` text over `--danger-bg`.
7. **Missing Navigation Links in Admin Header**:
   - In [app/static/admin.html](file:///c:/Users/Nigel/Documents/projects/audio%20transcribe/app/static/admin.html), the `<header class="brand-card">` lacks the `<nav>` links to return to Transcription or Documents that exist on `index.html` and `documents.html`.
