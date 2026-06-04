# Homepage Redesign Design

**Goal:** Rebuild the public homepage as a clean, ordinary-user-facing introduction page for I搭不搭.

**Audience:** Normal users who want to find someone for a specific activity. The page should make the product understandable before introducing any technical mechanism.

**Chosen Direction:** Warm non-human object illustration. Use the generated activity-card hero image selected by the user. Do not use real people, faces, hands, or stock-photo-like human scenes.

**Message Hierarchy:**
- Hero: "想做的事，终于有人一起。"
- Support copy: Tell the AI what you want to do; it helps find activity companions whose time, location, and interests fit.
- Flow: Say the activity, AI screens candidates, matched users enter a chat.
- Trust: Explain A2A as "双方 AI 先聊一轮" instead of showing technical architecture.
- Activities: Show common activity categories like 看展、咖啡、羽毛球、徒步、电影、桌游.
- Footer: Keep API docs and admin links as low-profile utility links only.

**Out of Scope:**
- No technical stack section.
- No A2A architecture diagram on the homepage.
- No new backend API.
- No signup form unless the user later provides a target destination.

**Implementation Notes:**
- Replace `app/static/index.html` with a static responsive page.
- Add the selected generated hero as a project asset under `app/static/assets/`.
- Keep the page clean, bright, and readable on mobile and desktop.
