# Product Requirements Specification
## Project: Distraction-Free Instagram Client

**Document type:** Product Requirements / Client Brief  
**Version:** 1.0  
**Status:** Ready for architecture review  
**Target platform:** Self-hosted web application  
**Initial deployment:** Raspberry Pi 5, home network  
**Primary user:** Single personal user  
**Future extensibility:** MCP-enabled AI agent integration

---

# 1. Product Vision

## 1.1 Problem statement

Instagram's current experience is designed to maximize engagement and time spent in the application rather than help users efficiently consume content from accounts they have chosen to follow.

The experience contains several unwanted characteristics:

- Algorithmically recommended content.
- Sponsored posts and advertisements.
- Infinite scrolling.
- Repeated content.
- Distractions unrelated to followed accounts.
- No meaningful indication that the user has consumed everything new.
- Story navigation that is unnecessarily confusing when navigating between different accounts and individual Story segments.

The result is that users cannot easily accomplish a simple task: see what the people they follow have published and then stop browsing.

## 1.2 Product objective

Build an alternative Instagram web client that provides access to content from followed Instagram accounts, organized into a controlled, finite browsing experience.

The application must:

1. Show content from followed accounts.
2. Exclude unwanted interruptions and recommendations.
3. Organize posts chronologically.
4. Provide a first-class Stories experience.
5. Track viewing progress persistently.
6. Provide a clear indication when all available content has been consumed.
7. Never encourage endless browsing.
8. Operate independently of Instagram's frontend.

## 1.3 Product philosophy

The application must follow these principles:

- **User-controlled:** The user decides what to see.
- **Finite:** Every browsing session must have an identifiable end.
- **Predictable:** Content ordering must be understandable and consistent.
- **Non-intrusive:** No notifications, recommendations or engagement-driven interruptions.
- **Persistent:** Viewing progress survives browser restarts and device changes.
- **Independent:** The application owns its presentation and browsing experience.
- **Extensible:** External agents can interact with the application through MCP.

The product is not intended to recreate every Instagram feature.

It is intended to provide a better way to consume the content users already want to see.

---

# 2. Target User and Usage Scenarios

## 2.1 Initial target user

The initial release is a single-user, personal application.

The user has an existing Instagram account and follows a collection of accounts.

The application is accessible through a browser on devices connected to the user's home network.

Expected devices:
- iPhone.
- MacBook.
- Other desktop or mobile browsers.

The experience should be responsive and optimized for mobile browsing.

## 2.2 Primary usage scenario

A typical session:

1. The user opens the application.
2. The application displays the number of unseen posts and Stories.
3. The user chooses whether to browse posts or Stories.
4. The user consumes available content.
5. Viewing progress is automatically recorded.
6. The application indicates when the selected content is exhausted.
7. The user leaves the application.

The user should not have to remember which posts or Stories they previously saw.

## 2.3 Secondary scenarios

- The user wants to revisit a previously viewed post.
- The user wants to see content from a particular account.
- The user wants to temporarily mute an account.
- The user wants to browse Stories without browsing posts.
- The user wants to check whether new content has arrived.
- The user wants to resume an unfinished browsing session.
- An external AI agent wants to retrieve feed information or viewing progress through MCP.

---

# 3. Functional Requirements

# 3.1 Application Dashboard

The application should provide a central dashboard.

It should give the user an immediate understanding of what is available.

### Required information

- Number of unseen posts.
- Number of unseen Stories.
- Number of followed accounts with new content.
- Last successful synchronization.
- Overall viewing progress.

### Proposed layout

**Posts**
- 12 unseen posts.
- 8 already viewed in the current session.

**Stories**
- 5 accounts with unseen Stories.
- 14 unseen Story segments.

The dashboard should provide direct access to:
- Following feed.
- Stories.
- Account list.
- Previously viewed content.
- Synchronization status.
- Settings.

### Acceptance criteria

- The dashboard loads without requiring a synchronization.
- Previously retrieved content remains available when synchronization is unavailable.
- Counts reflect persisted viewing state.
- Posts and Stories have independent progress indicators.

---

# 3.2 Following Feed

This is the primary functionality of the application.

## Content requirements

The feed must contain content originating from accounts the user follows.

Supported content types should include:
- Single-image posts.
- Video posts.
- Carousel posts.
- Reels, subject to the final content-selection decision.

The feed must exclude:
- Suggested posts.
- Recommended accounts.
- Sponsored content and advertisements.
- Content from accounts the user does not follow.

The application must not introduce its own engagement-based ranking algorithm.

## Ordering

Posts should be presented chronologically.

Recommended default: newest first.

The user should be able to navigate through posts in a predictable order.

## Finite feed behavior

This is a core product requirement.

The application must not implement an infinite feed.

A browsing session should operate against a finite snapshot of available content.

Proposed behavior:

1. When a browsing session starts, the application determines which posts are eligible.
2. The application creates a finite collection of posts.
3. Newly discovered posts during that session are reserved for the next session.
4. The user browses the existing collection.
5. Once the final post has been consumed, the application displays an end-of-feed state.

Example:

At session start:
- 12 unseen posts.

During browsing:
- 3 additional posts are discovered.

The current session still contains 12 posts.

The additional 3 posts become available in the next session.

This prevents the feed from continually extending while the user is browsing.

## Post presentation

Each post should display, where available:

- Author/profile picture.
- Username.
- Publication timestamp.
- Image or video.
- Caption.
- Carousel navigation.
- Original Instagram permalink.
- Available engagement metadata.

The interface should prioritize the media.

Captions should be readable without requiring excessive interaction.

## Feed navigation

Required interactions:

- Move to the next post.
- Move to the previous post.
- Open an individual post.
- Navigate carousel images.
- Open the author's account.
- Mark a post as seen.
- Revisit previously seen posts.

The application should support keyboard navigation on desktop where appropriate.

## Seen/unseen behavior

Viewing state must be independent of content synchronization.

A post must not automatically become seen merely because it has been retrieved or displayed in a background list.

Recommended behavior:
- Mark as seen when the post enters the active viewing experience and meets the application's viewing threshold.
- Persist viewing state immediately.
- Provide a way to mark content as unseen again.
- Preserve history across sessions.

The exact viewing threshold should be configurable or determined during UX design.

## End-of-feed state

When all eligible posts have been consumed, display an explicit completion state.

Suggested message:

**You're all caught up.**

You've seen everything available from the accounts you follow.

The application must not automatically load recommended content or extend the session.

The user may explicitly request a refresh or start another session.

---

# 3.3 Stories

Stories are a first-class part of the product, not an extension of the feed.

The Stories experience must be independent of the Posts experience.

## Stories overview

The application should display accounts with available Stories.

Each account entry should provide:

- Profile picture.
- Username.
- Unseen indicator.
- Number of available Story segments, if known.
- Viewing progress.

Accounts with unseen Stories should be visually distinguishable from completed accounts.

The user should be able to identify which accounts still have content to watch.

## Story viewer

The Story viewer should provide an immersive, distraction-free presentation.

Each Story should display:

- Media.
- Account identity.
- Publication time.
- Story progress indicators.
- Navigation controls.

Support both image and video Stories.

For video Stories, playback should follow the natural media duration.

## Story navigation

The existing Instagram navigation model should be improved.

The distinction between navigating Story segments and navigating between accounts must be clear.

Proposed interaction model:

| Interaction | Action |
|---|---|
| Tap right side | Next Story segment |
| Tap left side | Previous Story segment |
| Swipe left | Next account |
| Swipe right | Previous account |
| Keyboard right | Next account |
| Keyboard left | Previous account |
| Keyboard down | Next Story segment |
| Keyboard up | Previous Story segment |
| Space | Pause/resume |
| Escape | Close viewer |

Navigation must not accidentally skip multiple accounts or Story segments.

The interface should provide clear controls for moving between accounts.

### Account boundaries

When the user reaches the final Story of an account:

- The application should indicate that the account's Stories are complete.
- The user can move to the next account.
- Automatic advancement to the next account should be configurable.

When the user reaches the first Story of an account, previous navigation should move to the previous account only through an explicit account-navigation action.

## Story progress

Viewing progress must be tracked per individual Story segment.

The application must distinguish:

- Discovered Stories.
- Available Stories.
- Viewed Stories.
- Expired Stories.

A Story should not be marked as viewed merely because the account's Story list has been opened.

Progress must persist across browser sessions and devices.

## Story expiration

Instagram Stories normally expire after approximately 24 hours.

The application should:
- Track expiration timestamps where available.
- Remove expired Stories from the active viewing queue.
- Avoid presenting expired media as currently available.
- Preserve historical viewing metadata.
- Handle content that becomes unavailable before its expected expiration.

## Stories completion

Once all available Stories have been viewed, display an explicit completion state.

Example:

**You're all caught up on Stories.**

There should be no automatic transition to unrelated content.

---

# 3.4 Accounts Management

The application should maintain a local representation of followed accounts.

For each account, store available metadata:

- Account identifier.
- Username.
- Display name.
- Profile picture.
- Following status.
- Last synchronization.
- Muted status.

## Account controls

The user should be able to:

- View followed accounts.
- Search accounts.
- Filter content by account.
- Temporarily mute an account.
- Unmute an account.
- View an account's posts.
- View an account's Stories.
- Inspect account synchronization status.

Muting should hide content from the active feed without deleting previously collected content or viewing history.

The initial version does not need to support following or unfollowing accounts through the application.

---

# 3.5 Synchronization

The application needs a background synchronization mechanism.

Its purpose is to discover newly published content and update locally stored metadata.

## Requirements

- Synchronization must run independently of the frontend.
- Synchronization must not interrupt an active browsing session.
- Synchronization must not reset viewing progress.
- Duplicate content must not be created.
- Failed synchronization must not make existing content inaccessible.
- The user must be able to request synchronization manually.
- The application must expose the last successful synchronization time.

Recommended initial interval: every 30 minutes.

This should be configurable.

## Synchronization status

The application should expose:

- Last attempted synchronization.
- Last successful synchronization.
- Synchronization duration.
- Number of new posts discovered.
- Number of new Stories discovered.
- Errors, if any.

The system should handle expired sessions, unavailable content and provider failures gracefully.

## Important content acquisition constraint

Instagram's official API does not provide unrestricted access to the complete home feed or arbitrary Stories from followed accounts.

The architecture must therefore support different content providers without coupling the product to a specific ingestion mechanism.

Any implementation must respect applicable Meta permissions and platform terms.

A successful proof of content acquisition is a prerequisite for claiming full Instagram functionality.

---

# 3.6 Previously Viewed Content

The user must be able to revisit content without changing their browsing progress.

A separate history view should provide:

- Previously viewed posts.
- Previously viewed Stories, where historical access remains possible.
- Account filtering.
- Date filtering.
- Direct access to original content.

Reopening a previously viewed post should not automatically mark it as unseen.

The user may explicitly change its viewing state.

Expired Story media should not be represented as playable when it is no longer available.

---

# 3.7 Filtering and Preferences

The application should support basic deterministic filters.

Initial requirements:

- Hide muted accounts.
- Hide selected content types.
- Filter by account.
- Filter by publication date.
- Switch between unseen and all posts.

No machine-learning ranking or recommendation functionality is required.

Filters must not silently remove content from persistent storage.

---

# 4. User Experience Requirements

## 4.1 General design

The interface should be:

- Minimal.
- Responsive.
- Media-focused.
- Fast.
- Consistent.
- Free of unnecessary animations.
- Easy to navigate using touch or keyboard.

It should not reproduce Instagram's engagement-oriented design patterns.

## 4.2 Mobile experience

Mobile browsing is particularly important.

The application should:
- Work on modern iPhone browsers.
- Support touch navigation.
- Use available screen space efficiently.
- Provide a comfortable Story viewing experience.
- Avoid accidental navigation.
- Preserve progress when the browser is closed.

## 4.3 Desktop experience

Desktop browsing should support:

- Keyboard navigation.
- Efficient feed navigation.
- Larger media presentation.
- Account and filter sidebars.
- Clear progress indicators.

## 4.4 Notifications and interruptions

The application should not implement:

- Push notifications.
- Engagement notifications.
- Suggested content popups.
- Promotional messages.
- Infinite-loading mechanisms.

The user should explicitly choose to refresh or begin another browsing session.

---

# 5. Data and Persistence Requirements

The application must persist:

- Followed account information.
- Retrieved posts.
- Retrieved Stories.
- Content metadata.
- Viewing history.
- Story segment progress.
- Feed session state.
- User preferences.
- Synchronization history.

Important distinctions:

1. Retrieved content is not necessarily viewed.
2. Viewed content is not necessarily expired.
3. Expired content may still have historical metadata.
4. New content must not reset existing progress.
5. Feed sessions must remain consistent after browser restarts.

The application should use stable source identifiers to avoid duplicates.

Media caching is optional and should not be a prerequisite for the initial release.

The product must not require permanent local copies of all Instagram media.

---

# 6. MCP Integration Requirements

## 6.1 Objective

The application should expose an MCP server that allows external AI agents to interact with its functionality.

MCP is an integration interface, not an AI feature inside the application.

No AI models or AI services are required in V1.

The MCP server must use the same application business logic as the web frontend.

## 6.2 Initial MCP tools

### Feed

| Tool | Function |
|---|---|
| `get_feed` | Retrieve posts with filters and pagination |
| `get_feed_status` | Retrieve unseen counts and progress |
| `get_post` | Retrieve an individual post |
| `mark_post_seen` | Mark a post as viewed |
| `get_accounts` | List followed accounts |

### Stories

| Tool | Function |
|---|---|
| `get_stories` | Retrieve available Stories |
| `get_story_queue` | Retrieve the next unseen Story segments |
| `mark_story_seen` | Mark a Story segment as viewed |
| `get_story_progress` | Retrieve Story viewing progress |

### Synchronization

| Tool | Function |
|---|---|
| `get_sync_status` | Retrieve synchronization status |
| `request_sync` | Request a synchronization |
| `get_feed_summary` | Retrieve deterministic content statistics |

## 6.3 MCP behavior

- Tools must return structured data.
- Pagination must be supported.
- Errors must be explicit.
- Write operations must be validated.
- Bulk modifications should return affected identifiers.
- MCP operations must respect the same permissions and rules as the web application.

The MCP server should not expose Instagram credentials or session information.

The MCP interface should be versioned to allow future extensions without breaking existing agents.

## 6.4 Future agent capabilities

Not required in V1, but the interface should permit future capabilities such as:

- Searching posts using natural language.
- Summarizing recent activity.
- Finding specific content.
- Creating collections.
- Answering questions about followed accounts.
- Managing reading preferences.

These capabilities should be implemented by external agents rather than introducing AI dependencies into the core application.

---

# 7. Security and Privacy Requirements

The initial application is personal and accessible only from the home network.

Requirements:

- No public-facing service endpoints.
- No router port forwarding.
- No externally accessible database.
- Authentication for application access.
- Secure storage of any provider credentials.
- No exposure of Instagram session cookies to the frontend.
- No credentials returned through REST or MCP.
- No unnecessary transmission of personal data.
- Restricted access to administrative operations.

The application should continue working with locally stored data when Instagram synchronization is unavailable.

The architecture should permit future secure remote access, but remote access is explicitly outside V1 scope.

---

# 8. Deployment and Operational Requirements

## 8.1 Target environment

Initial deployment:

- Raspberry Pi 5.
- Existing Docker environment.
- Home network only.
- Persistent local storage.
- Existing Home Assistant installation must remain unaffected.

## 8.2 Deployment requirements

The application should be deployable using Docker Compose.

The deployment must include independently manageable components for:

- Web frontend / reverse proxy.
- Go API.
- Synchronization worker.
- MCP server.
- PostgreSQL.

The exact service boundaries and whether API and MCP run in one process or separate processes are architectural decisions.

The application should not require:
- Cloud hosting.
- Cloud databases.
- External AI services.
- GPU acceleration.
- Kubernetes.
- Redis for initial functionality.

## 8.3 Resource requirements

The application should operate comfortably on a Raspberry Pi 5.

It should:
- Use limited CPU and memory during idle periods.
- Avoid permanently running unnecessary browser processes.
- Keep synchronization resource usage controlled.
- Avoid unbounded media caching.
- Recover automatically after container restarts.

## 8.4 Backups

Requirements:

- Automated daily database backup.
- Retention of at least seven daily backups.
- Documented restore procedure.
- Persistent storage independent of container lifecycle.

---

# 9. Explicit Non-Goals for V1

The following are not part of the initial release:

- AI-powered functionality.
- AI summarization.
- Semantic search.
- AI categorization.
- Recommendation algorithms.
- Likes and comments through Instagram.
- Following and unfollowing accounts.
- Direct messages.
- Uploading posts.
- Publishing Stories.
- Creating Reels.
- Multiple user accounts.
- Public multi-user SaaS functionality.
- Cloud hosting.
- Social engagement analytics.
- Push notifications.

These features should not influence the initial implementation unless they introduce necessary architectural considerations.

---

# 10. Acceptance Criteria

The initial release should be considered functionally complete when the following conditions are met.

## Feed

- [ ] The application can display posts from the user's followed accounts through a permitted content source.
- [ ] Posts are ordered chronologically.
- [ ] Suggested and sponsored content is excluded.
- [ ] The user can navigate forward and backward.
- [ ] Viewing progress is persisted.
- [ ] Previously viewed posts can be revisited.
- [ ] A finite feed session reaches an explicit end.
- [ ] Newly discovered posts do not extend an active session.

## Stories

- [ ] Available Stories are grouped by account.
- [ ] Individual Story segments are tracked independently.
- [ ] The user can navigate between segments.
- [ ] The user can navigate between accounts.
- [ ] Backward and forward navigation behave predictably.
- [ ] Story progress is persisted.
- [ ] Expired Stories are removed from the active queue.
- [ ] Completing all available Stories displays an explicit end state.

## Synchronization

- [ ] Synchronization runs independently of the frontend.
- [ ] Duplicate content is prevented.
- [ ] Failed synchronization does not affect existing content.
- [ ] Manual synchronization is available.
- [ ] Synchronization status is visible.

## MCP

- [ ] The MCP server can be accessed by an authorized local agent.
- [ ] Feed retrieval works through MCP.
- [ ] Stories retrieval works through MCP.
- [ ] Viewing state can be queried.
- [ ] Viewing state can be updated.
- [ ] Synchronization can be requested.
- [ ] MCP and REST return consistent application state.

## Deployment

- [ ] The application runs on Raspberry Pi 5.
- [ ] The application is accessible from the home network.
- [ ] Existing Home Assistant services remain unaffected.
- [ ] PostgreSQL is not exposed to the LAN.
- [ ] Data survives container restarts.
- [ ] Backup and restore procedures are tested.

---

# 11. Recommended Development Priorities

Development should be organized around delivering useful functionality early.

### Phase 0 — Feasibility validation

Before building the complete application:

1. Investigate permitted Instagram content access.
2. Establish whether followed-account posts can be retrieved.
3. Establish whether followed-account Stories can be retrieved.
4. Identify available metadata and media limitations.
5. Document authentication and synchronization limitations.
6. Define a provider interface.

**Deliverable:** A documented feasibility assessment and working proof of content ingestion, or a clear identification of the access limitation.

### Phase 1 — Application foundation

- Project setup.
- Docker deployment.
- PostgreSQL.
- Go application core.
- REST API.
- React frontend.
- Mock content provider.

**Deliverable:** A working application with sample content.

### Phase 2 — Feed experience

- Account management.
- Chronological feed.
- Feed sessions.
- Viewing progress.
- End-of-feed behavior.
- History.

**Deliverable:** Complete feed experience using mock data.

### Phase 3 — Stories experience

- Stories overview.
- Story viewer.
- Segment navigation.
- Account navigation.
- Viewing progress.
- Expiration handling.
- End-of-Stories behavior.

**Deliverable:** Complete Stories experience using mock data.

### Phase 4 — Content integration

- Implement the validated provider.
- Synchronization worker.
- Duplicate detection.
- Content metadata persistence.
- Error handling.
- Real-content validation.

**Deliverable:** Application operating with real, permitted content sources.

### Phase 5 — MCP

- MCP server.
- Initial toolset.
- Authentication.
- Structured responses.
- Integration testing.

**Deliverable:** External agents can interact with the application.

### Phase 6 — Hardening

- Security.
- Backups.
- Recovery.
- Performance.
- Mobile UX.
- Operational monitoring.

**Deliverable:** Stable personal deployment.

---

# 12. Open Product Decisions

The following decisions should be confirmed before implementation. Recommended defaults are included, but these are not yet binding requirements.

| Decision | Recommended default |
|---|---|
| Feed ordering | Newest first |
| Feed session | Snapshot at session start |
| Content types | Photos, carousels and videos; decide whether to include Reels |
| Story account advancement | Manual, with optional auto-advance |
| Story playback | Automatic video playback, timed image progression |
| Viewing threshold | Mark seen when actively viewed, with a configurable threshold |
| Synchronization | Every 30 minutes |
| Media storage | Metadata locally; media loaded from permitted source URLs |
| Feed refresh | Explicit user action plus background sync |
| Previous content | Available through history |
| Account muting | Hide from active feed without deleting history |
| Authentication | Single-user local authentication |

The architect should identify any additional decisions that must be resolved before engineering begins.

---

# 13. Definition of Success

The product succeeds if the user can:

1. Open the application.
2. See all newly available content from followed accounts.
3. Browse posts and Stories without interruptions.
4. Understand how much content remains.
5. Navigate naturally between Stories and accounts.
6. Finish browsing and reach a clear end.
7. Close the application knowing that progress has been saved.
8. Return later and see only content that is genuinely new or explicitly revisited.

The application must not reproduce Instagram's infinite engagement loop.

**The ultimate measure of success is not time spent in the application. It is how reliably the application helps the user finish consuming the content they actually care about.**

---

# 14. Instructions to the Architecture Team

Please use this specification to produce:

1. System architecture and component boundaries.
2. Domain model and database schema.
3. REST API specification.
4. MCP tool schemas and transport design.
5. Content provider abstraction.
6. Synchronization and session lifecycle design.
7. Story navigation and viewing-state model.
8. Docker deployment architecture for Raspberry Pi 5.
9. Security and data-retention design.
10. Engineering epics, implementation milestones and dependencies.

Please explicitly identify technical risks, unresolved assumptions and any requirements that cannot be fulfilled using permitted Instagram access mechanisms.

Do not silently remove or weaken the finite-feed requirement, independent Story progress, or explicit end-of-feed behavior.

**Product principle to preserve throughout implementation: Instagram should show the user what they came to see, not decide how long they stay.**