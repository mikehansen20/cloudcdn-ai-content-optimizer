# Headless HTML Renderer (`services/renderer`)

Cloud Run service running Playwright and headless Chromium to render client-side JavaScript Single Page Applications (SPAs).

## Architecture & Lifecycle

- **Escalation Fallback Only**: Invoked exclusively by `services/worker` during offline crawl processing when static HTML fetch returns a JavaScript shell without substantial content.
- **Strict Process Isolation**: Isolated in a dedicated stateless container so heavy browser rendering workloads never impact worker crawl stability.
- **Offline Plane Exclusivity**: Operates entirely offline during scheduled builds. It is **never** on the real-time request serving path for end users or AI crawlers.
