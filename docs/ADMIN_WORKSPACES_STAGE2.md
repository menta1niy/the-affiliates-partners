# The Affiliates Partners — Stage 2: Admin workspaces

Implementation based on the approved v3.2 plan. Scope: local frontend navigation
and layout only. Backend, PostgreSQL, privileges, payouts, registration and
Telegram secrets remain unchanged.

## Navigation

| Workspace | Contents |
| --- | --- |
| Overview | Existing KPI metrics, registration shortcut, assignment shortcut |
| Offers | Inline catalog summary; existing create/edit dialog from the page or a card |
| Assignments | Searchable, paginated lead list; existing participant dialog for manual assignments |
| People | Pending registrations and Users/Team subtabs; existing roles and decisions |
| More | Invitations and Audit subtabs |

The mobile navigation is an icon-only floating dock with five 48 x 46px buttons,
22px blur and 25px radius. On desktop the labeled side navigation remains.
Screen numbers are 01/05 through 05/05. Hero and metrics live on Overview
only; operational screens have their own headings and content.

### Permissions and functionality

- Owner and admin have access to Offers and Assignments. Staff retains the
  existing authorized user moderation/management functions, but does not get
  catalog or assignment screens.
- Existing individual assignment and status APIs are untouched. The new
  assignment screen routes a selected lead to their existing editable profile.
- Catalog owner edit privileges remain unchanged. An offer card opens its
  populated editor directly for an owner. Administrators can inspect only.
- Invitations, revocation and audit continue to use their existing endpoints.
- The router preserves Back/Forward history and accepts older tab state.
- No automatic assignment or bulk assignment is added here. Manual bulk
  selection and the Select All operation are planned for a later stage.
- The profile, offers and registration flows of leads are not changed.

### UX checks

- Dock measured 264px wide with no document overflow at mobile widths.
- At 320px, the new People screen heading remains a single line.
- The catalog action has readable dark text on amber.
- Status badges do not shrink to vertical lettering; long offer titles
  clamp to two lines in the overview (full title remains editable).
- Existing modal dialogs retain their top-layer behavior and safe-area rules.

## Release boundary

Commit and document the changes locally. Do not push or publish to Aeza
until every implementation stage has been completed, reviewed and accepted.
