"""Stage 6: UI-only responsive, accessibility and Telegram WebView simulation."""

import threading
import unittest
from http.server import ThreadingHTTPServer

from playwright.sync_api import sync_playwright

from tests.test_admin_participant_browser import BrowserHandler
from tests.test_admin_redesign_browser import BOOTSTRAP
from tests.test_participant_redesign_browser import FIXTURE


TELEGRAM_MOCK = r"""(() => {
  const events = {};
  window.__tgEvents = events;
  window.Telegram = {WebApp: {
    initData: 'ui-fixture',
    safeAreaInset:{top:48,left:9,right:9,bottom:26},
    contentSafeAreaInset:{top:56,left:13,right:13,bottom:34},
    isFullscreen:true,
    ready(){},expand(){},disableVerticalSwipes(){},
    setHeaderColor(){},setBackgroundColor(){},setBottomBarColor(){},
    onEvent(event,fn){events[event]=fn;},
    requestFullscreen(){},
  }};
})()"""


class ResponsiveInteractionQA(unittest.TestCase):
    def setUp(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), BrowserHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def open_page(self, browser, admin=False, width=390, viewport_height=844, reduced_motion=False):
        page = browser.new_page(
            viewport={"width": width, "height": viewport_height},
            reduced_motion="reduce" if reduced_motion else "no-preference",
        )
        # The real Telegram SDK overwrites window.Telegram; replace only its
        # external script in this isolated local simulation.
        page.route(
            "https://telegram.org/js/telegram-web-app.js",
            lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
        )
        page.add_init_script(TELEGRAM_MOCK)
        page.add_init_script(BOOTSTRAP if admin else FIXTURE)
        route = "/partners/admin/" if admin else "/partners/"
        page.goto(self.base + route + "#tgWebAppData=ui-fixture&state=active&role=owner")
        page.locator("#admin-app" if admin else "#account").wait_for(state="visible")
        return page

    def test_safe_area_and_content_layout_across_sizes(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    for width in (320, 375, 390, 430, 768, 1024, 1440):
                        with self.subTest(admin=admin, width=width):
                            page = self.open_page(browser, admin, width)
                            values = page.evaluate("""() => {
                              const shell = document.querySelector('.shell');
                              const style = getComputedStyle(shell);
                              return {
                                scroll: document.documentElement.scrollWidth,
                                available: document.documentElement.clientWidth,
                                top: parseFloat(style.paddingTop),
                                left: parseFloat(style.paddingLeft),
                                right: parseFloat(style.paddingRight),
                                bottom: parseFloat(style.paddingBottom),
                              };
                            }""")
                            self.assertLessEqual(values["scroll"], values["available"] + 1, values)
                            self.assertGreaterEqual(values["top"], 56, values)
                            self.assertGreaterEqual(values["left"], 13, values)
                            self.assertGreaterEqual(values["right"], 13, values)
                            self.assertGreaterEqual(values["bottom"], 34, values)
                            page.close()
            finally:
                browser.close()

    def test_display_font_loaded_and_mobile_headings_readable(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    for width in (320, 390, 430, 1440):
                        with self.subTest(admin=admin, width=width):
                            page = self.open_page(browser, admin=admin, width=width)
                            page.evaluate("document.fonts.load('700 24px Unbounded')")
                            heading = page.locator(".admin-hero h1" if admin else "#welcome")
                            heading.wait_for(state="visible")
                            typography = heading.evaluate("""element => {
                              const style=getComputedStyle(element),rect=element.getBoundingClientRect();
                              return {font:style.fontFamily,spacing:style.letterSpacing,
                                overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth,
                                left:rect.left,right:rect.right,loaded:document.fonts.check('700 24px Unbounded')};
                            }""")
                            self.assertTrue(typography["loaded"], typography)
                            self.assertIn("Unbounded", typography["font"])
                            self.assertLessEqual(typography["overflow"], 1, typography)
                            self.assertGreaterEqual(typography["left"], 0, typography)
                            self.assertLessEqual(typography["right"], width + 1, typography)
                            page.close()
            finally:
                browser.close()

    def test_rounded_float_panels_and_offers_heading_plaque(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 390, 430, 1440):
                    with self.subTest(width=width):
                        page = self.open_page(browser, width=width)
                        page.locator('#participant-nav [data-view="offers"]').click()
                        plaque = page.locator(".participant-screen-offers")
                        self.assertTrue(plaque.is_visible())
                        self.assertIn("Мои", plaque.inner_text())
                        self.assertIn("офферы", plaque.inner_text())
                        self.assertFalse(page.locator("#participant-home").is_visible())
                        metrics = page.evaluate("""() => {
                          const get=selector=>{
                            const node=document.querySelector(selector);
                            const rect=node.getBoundingClientRect();
                            return {radius:parseFloat(getComputedStyle(node).borderTopLeftRadius),
                              width:rect.width,left:rect.left,right:rect.right};
                          };
                          return {plaque:get('.participant-screen-offers'),
                            offers:get('#offers-section'),
                            overflow:document.documentElement.scrollWidth-document.documentElement.clientWidth};
                        }""")
                        for key in ("plaque", "offers"):
                            self.assertGreaterEqual(metrics[key]["radius"], 25, metrics)
                            self.assertGreaterEqual(metrics[key]["left"], 0, metrics)
                            self.assertLessEqual(metrics[key]["right"], width+1, metrics)
                        self.assertLessEqual(metrics["overflow"], 1, metrics)
                        offer_layout=page.locator(".participant-screen-offers").evaluate("""e=>({
                          height:e.getBoundingClientRect().height,
                          radius:getComputedStyle(e).borderTopLeftRadius,
                          padding:getComputedStyle(e).padding,
                          background:getComputedStyle(e).backgroundImage,
                          title:(() => {
                            const h=e.querySelector('h1'),r=h.getBoundingClientRect(),s=getComputedStyle(h);
                            return {font:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight,
                              height:r.height,width:r.width,scrollWidth:h.scrollWidth,nowrap:s.whiteSpace};
                          })()
                        })""")
                        page.locator('#participant-nav [data-view="profile"]').click()
                        profile=page.locator(".participant-screen-profile")
                        self.assertTrue(profile.is_visible())
                        profile_layout=profile.evaluate("""e=>({
                          height:e.getBoundingClientRect().height,
                          radius:getComputedStyle(e).borderTopLeftRadius,
                          padding:getComputedStyle(e).padding,
                          background:getComputedStyle(e).backgroundImage,
                          title:(() => {
                            const h=e.querySelector('h1'),r=h.getBoundingClientRect(),s=getComputedStyle(h);
                            return {font:s.fontSize,weight:s.fontWeight,lineHeight:s.lineHeight,
                              height:r.height,width:r.width,scrollWidth:h.scrollWidth,nowrap:s.whiteSpace};
                          })()
                        })""")
                        layout={"offers":offer_layout,"profile":profile_layout}
                        self.assertAlmostEqual(offer_layout["height"],profile_layout["height"],delta=1,msg=str(layout))
                        self.assertEqual(offer_layout["radius"],profile_layout["radius"])
                        self.assertEqual(offer_layout["padding"],profile_layout["padding"])
                        self.assertEqual(offer_layout["background"],profile_layout["background"])
                        self.assertEqual(offer_layout["title"]["font"],profile_layout["title"]["font"])
                        self.assertEqual(offer_layout["title"]["weight"],profile_layout["title"]["weight"])
                        self.assertEqual(offer_layout["title"]["nowrap"],"nowrap")
                        self.assertEqual(profile_layout["title"]["nowrap"],"nowrap")
                        for current in (offer_layout,profile_layout):
                            self.assertLessEqual(current["title"]["height"],float(current["title"]["lineHeight"].replace("px",""))+1)
                            self.assertLessEqual(current["title"]["scrollWidth"],current["title"]["width"]+1)
                        page.close()
                for width in (320, 390, 1440):
                    with self.subTest(admin=True, width=width):
                        page = self.open_page(browser, admin=True, width=width)
                        page.locator('[data-tab="users"]').click()
                        radius=page.locator(".admin-work-panel:not([hidden])").first.evaluate(
                            "el=>parseFloat(getComputedStyle(el).borderTopLeftRadius)")
                        self.assertGreaterEqual(radius, 25)
                        page.close()
            finally:
                browser.close()

    def test_mobile_sidebars_fixed_below_modal_layer(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    for width in (320, 390, 430):
                        with self.subTest(admin=admin, width=width):
                            page = self.open_page(browser, admin=admin, width=width)
                            selector = ".admin-sidebar" if admin else ".participant-nav"
                            nav = page.locator(selector)
                            nav.wait_for(state="visible")
                            geometry = nav.evaluate("""node => {
                              const rect=node.getBoundingClientRect();
                              return {position:getComputedStyle(node).position,
                                left:rect.left,right:rect.right,bottom:rect.bottom,
                                width:innerWidth,height:innerHeight};
                            }""")
                            self.assertEqual(geometry["position"], "fixed", geometry)
                            self.assertGreaterEqual(geometry["left"], 0, geometry)
                            self.assertLessEqual(geometry["right"], geometry["width"], geometry)
                            self.assertLess(geometry["bottom"], geometry["height"], geometry)
                            page.evaluate("scrollTo(0, document.body.scrollHeight)")
                            after_scroll = nav.evaluate("node => node.getBoundingClientRect().bottom")
                            self.assertAlmostEqual(after_scroll, geometry["bottom"], delta=1)
                            if admin:
                                page.evaluate("""() => {
                                  const dialog=document.createElement('dialog');
                                  dialog.id='navigation-layer-test';
                                  dialog.textContent='Modal content';
                                  dialog.style.cssText='width:100vw;height:100vh;max-width:none;max-height:none;margin:0;';
                                  document.body.append(dialog);dialog.showModal();
                                }""")
                                self.assertTrue(page.locator("#navigation-layer-test").evaluate(
                                    "node => node.matches(':modal')"
                                ))
                            page.close()
            finally:
                browser.close()

    def test_compact_glass_icon_docks(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    for width in (320, 375, 390, 430):
                        with self.subTest(admin=admin, width=width):
                            page = self.open_page(browser, admin=admin, width=width)
                            selector = ".admin-sidebar" if admin else "#participant-nav"
                            dock = page.locator(selector)
                            info = dock.evaluate("""node => {
                              const css=getComputedStyle(node), rect=node.getBoundingClientRect();
                              return {width:rect.width,height:rect.height,radius:parseFloat(css.borderRadius),
                                blur:css.backdropFilter,background:css.backgroundColor,
                                left:rect.left,right:rect.right};
                            }""")
                            self.assertLess(info["width"],width-20,info)
                            self.assertLess(info["height"],70,info)
                            self.assertGreaterEqual(info["radius"],24,info)
                            self.assertIn("blur(",info["blur"],info)
                            self.assertGreaterEqual(info["left"],0,info)
                            self.assertLessEqual(info["right"],width,info)
                            buttons = dock.locator(".admin-tabs button:not([hidden])" if admin else "a[data-view]")
                            self.assertGreaterEqual(buttons.count(),3)
                            for i in range(buttons.count()):
                                item=buttons.nth(i)
                                self.assertEqual(item.locator(".nav-icon").count(),1)
                                self.assertFalse(item.locator(".nav-label").is_visible())
                                self.assertTrue(item.get_attribute("aria-label"))
                                rect=item.bounding_box()
                                self.assertGreaterEqual(rect["width"],44,rect)
                                self.assertGreaterEqual(rect["height"],44,rect)
                            selected = dock.locator('[aria-selected="true"]' if admin else '[aria-current="page"]')
                            self.assertEqual(selected.count(),1)
                            self.assertIn("drop-shadow(",selected.locator(".nav-icon").evaluate(
                                "node => getComputedStyle(node).filter"))
                            page.close()
            finally:
                browser.close()

    def test_participant_three_views_and_back_navigation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for width in (320, 390, 430, 1440):
                    with self.subTest(width=width):
                        page = self.open_page(browser, admin=False, width=width)
                        nav = page.locator("#participant-nav")
                        self.assertTrue(nav.is_visible())
                        self.assertTrue(page.locator("#participant-home").is_visible())
                        self.assertFalse(page.locator("#participant-offers-view").is_visible())
                        self.assertFalse(page.locator("#participant-profile-view").is_visible())
                        nav.locator('[data-view="offers"]').click()
                        self.assertTrue(page.locator("#participant-offers-view").is_visible())
                        self.assertFalse(page.locator("#participant-home").is_visible())
                        self.assertTrue(page.locator(".participant-screen-offers").is_visible())
                        self.assertIn("Мои",page.locator("#offers-heading").inner_text())
                        self.assertIn("офферы",page.locator("#offers-heading").inner_text())
                        self.assertEqual(page.title(),"The Affiliates — Офферы")
                        self.assertEqual(nav.locator('[aria-current="page"]').count(), 1)
                        nav.locator('[data-view="profile"]').click()
                        self.assertTrue(page.locator("#participant-profile-view").is_visible())
                        self.assertTrue(page.locator(".participant-screen-profile").is_visible())
                        self.assertFalse(page.locator(".participant-screen-offers").is_visible())
                        self.assertEqual(page.title(),"The Affiliates — Профиль")
                        page.go_back()
                        self.assertTrue(page.locator("#participant-offers-view").is_visible())
                        nav.locator('[data-view="home"]').click()
                        self.assertTrue(page.locator("#participant-home").is_visible())
                        page.close()
            finally:
                browser.close()

    def test_short_viewport_dialog_and_keyboard_simulation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = self.open_page(browser, admin=True, width=390, viewport_height=540)
                page.locator('[data-tab="users"]').click()
                page.locator("#users-list").get_by_role("button", name="Карточка").first.click()
                dialog = page.locator("#participant-detail")
                dialog.wait_for(state="visible")
                dims = dialog.evaluate("""node => ({
                  top:node.getBoundingClientRect().top,
                  bottom:node.getBoundingClientRect().bottom,
                  height:node.getBoundingClientRect().height,
                  viewport:window.innerHeight
                })""")
                self.assertGreaterEqual(dims["top"], -1, dims)
                self.assertLessEqual(dims["bottom"], dims["viewport"] + 1, dims)
                dialog.get_by_role("button", name="Сохранить статус").wait_for()
                dialog.locator('input[aria-label^="Комментарий к офферу"]').fill("Тест комментария")
                self.assertEqual(
                    dialog.locator('input[aria-label^="Комментарий к офферу"]').input_value(),
                    "Тест комментария",
                )
                # Simulate the available viewport shrinking after the keyboard
                # appears while the modal and its focused input are still open.
                page.set_viewport_size({"width":390,"height":410})
                bounds = dialog.evaluate("""node => ({
                    top:node.getBoundingClientRect().top,
                    bottom:node.getBoundingClientRect().bottom,
                    scrollHeight:node.scrollHeight,
                    clientHeight:node.clientHeight,
                    viewport:window.innerHeight,
                })""")
                self.assertGreaterEqual(bounds["top"], -1, bounds)
                self.assertLessEqual(bounds["bottom"], bounds["viewport"]+1, bounds)
                self.assertGreater(bounds["scrollHeight"], bounds["clientHeight"], bounds)
                self.assertTrue(dialog.get_by_role("button",name="Закрыть").count())
                page.close()
            finally:
                browser.close()

    def test_telegram_safe_area_event_updates_padding(self):
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                page=self.open_page(browser,admin=True,width=390)
                result=page.evaluate("""() => {
                    window.Telegram.WebApp.contentSafeAreaInset.top=83;
                    window.Telegram.WebApp.contentSafeAreaInset.bottom=61;
                    window.__tgEvents.contentSafeAreaChanged();
                    const shell=getComputedStyle(document.querySelector('.shell'));
                    return {top:parseFloat(shell.paddingTop),bottom:parseFloat(shell.paddingBottom)};
                }""")
                self.assertGreaterEqual(result["top"],83,result)
                self.assertGreaterEqual(result["bottom"],61,result)
                page.close()
            finally:
                browser.close()

    def test_telegram_ios_top_controls_do_not_cover_header_or_dialog(self):
        # Telegram's native close/menu controls occupy roughly the first 100
        # CSS pixels on iPhone even if its reported content inset is smaller.
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True)
            try:
                for admin in (False,True):
                    with self.subTest(admin=admin):
                        page=self.open_page(browser,admin=admin,width=390)
                        header=page.locator('.admin-mobile-header' if admin else '.participant-top')
                        box=header.bounding_box()
                        self.assertIsNotNone(box)
                        self.assertGreaterEqual(box['y'],112,box)
                        if admin:
                            page.get_by_role('button',name='Каталог офферов').click()
                            dialog=page.locator('#mvp-catalog-dialog')
                            dialog.wait_for(state='visible')
                            rect=dialog.bounding_box()
                            self.assertGreaterEqual(rect['y'],112,rect)
                            self.assertGreater(rect['height'],200,rect)
                            self.assertLessEqual(rect['y']+rect['height'],844,rect)
                            close=dialog.get_by_role('button',name='Закрыть')
                            self.assertGreaterEqual(close.bounding_box()['y'],112)
                        page.close()
            finally:
                browser.close()

    def test_reduced_motion_focus_and_navigation(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                for admin in (False, True):
                    page = self.open_page(browser, admin, reduced_motion=True)
                    target = page.locator("#reload" if admin else "#participant-next-action")
                    target.focus()
                    style = target.evaluate("""node => {
                      const css=getComputedStyle(node);
                      return {outline:css.outlineStyle,duration:css.transitionDuration};
                    }""")
                    self.assertNotEqual(style["outline"], "none")
                    self.assertEqual(style["duration"], "0s")
                    page.close()
            finally:
                browser.close()
