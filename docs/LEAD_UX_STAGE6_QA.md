# Partners lead UX: stage 6 QA, 2026-11-18

## Scope

This is a **local synthetic-browser audit**, not a physical Telegram acceptance test.
No CRM, PostgreSQL, banking state or backend runtime was modified.

- Local worktree: `D:\GPT\.partners-green-theme-20261114`
- Lead UX stages 3–6 are held locally until the combined release.
- Tested 320, 375, 390, 430, 768, 1024 and 1440 CSS px across the browser suites.
- Telegram simulation covers reported safe/content insets, changing inset events,
  modal top-layer behavior, short viewport/keyboard proxy, navigation and browser back.
- Registration/pending, empty/retry/error, assigned offers, filters, details and CRM/admin
  regression scenarios are exercised using synthetic API responses.

## Review and fixes

- Inspected generated synthetic screenshots of home, offers, details and profile
  at 320, 390 and 1440 CSS px.
- On narrow screens the offer-detail close button wrapped. Replaced its mobile
  text with an accessible, 44×44 px close symbol and kept the modal header sticky.
- Confirmed the dialog stays inside the viewport when height shrinks, and its
  close control remains reachable after scrolling.
- Tested Telegram bottom safe-area updates and reduced-motion accessibility.

## Automated verification

```powershell
node --check web/app.js
node --check web/admin/admin.js
node --check web/telegram-layout.js
git diff --check
python -m unittest tests.test_lead_final_ux_qa tests.test_participant_redesign_browser tests.test_responsive_interaction_qa tests.test_mvp_browser tests.test_header_logo_browser tests.test_visual_foundation tests.test_core_components_browser tests.test_admin_redesign_browser tests.test_deploy_safety_static -q
```

Result: **48 tests passed** on 2026-11-18.

Review screenshots and full logs are intentionally kept outside Git, under
`D:\GPT\_ta-partners-releases\ux-stage6-screenshots` and
`D:\GPT\_ta-partners-releases\ux-stage6-full-regression.log`.

## Final on-device acceptance still required

- Open the published Mini App from the actual Telegram bot on an iPhone and an
  Android phone; verify native close/menu controls, safe areas and gesture back.
- Focus a real text input with the software keyboard open, especially in admin dialogs.
- Check long instructions and external HTTPS offer links; confirm scroll and close.
- Verify account approval and assigned offers with an authorized test user only.
- Check network interruption, background/resume and refreshed Telegram authentication.

The synthetic test results must **not** be represented as physical-device acceptance.
