from __future__ import annotations

import os
import unittest

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as expected
from selenium.webdriver.support.ui import WebDriverWait


FRONTEND_URL = os.getenv("WEBREPORT_FRONTEND_URL", "http://127.0.0.1:28501")


class ReportRenderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        options = Options()
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.set_capability("goog:loggingPrefs", {"browser": "ALL"})
        cls.driver = webdriver.Chrome(options=options)
        cls.wait = WebDriverWait(cls.driver, 15)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.driver.quit()

    def test_report_renders_without_traceback_or_console_errors(self) -> None:
        self.driver.get(FRONTEND_URL)
        self.wait.until(
            lambda driver: driver.find_element(By.CSS_SELECTOR, "textarea[aria-label='Ваше сообщение']")
        ).send_keys("покажи все игры")
        self.driver.find_element(By.XPATH, "//button[normalize-space()='Отправить']").click()

        self.wait.until(
            expected.visibility_of_element_located(
                (By.XPATH, "//*[normalize-space()='Основные показатели']")
            )
        )
        report_pane = self.driver.find_element(By.CSS_SELECTOR, ".st-key-report-pane-scroll")
        self.assertIn("Запрос: покажи все игры", report_pane.text)

        self.assertEqual([], self.driver.find_elements(By.XPATH, "//*[normalize-space()='Traceback']"))
        console_errors = [
            entry
            for entry in self.driver.get_log("browser")
            if entry["level"] == "SEVERE"
        ]
        self.assertEqual([], console_errors)

    def test_top_teams_report_renders_without_traceback_or_console_errors(self) -> None:
        self.driver.get(FRONTEND_URL)
        self.wait.until(
            lambda driver: driver.find_element(By.CSS_SELECTOR, "textarea[aria-label='Ваше сообщение']")
        ).send_keys("топ 10 команд")
        self.driver.find_element(By.XPATH, "//button[normalize-space()='Отправить']").click()

        self.wait.until(
            expected.visibility_of_element_located(
                (By.XPATH, "//*[normalize-space()='Основные показатели']")
            )
        )
        report_pane = self.driver.find_element(By.CSS_SELECTOR, ".st-key-report-pane-scroll")
        self.assertIn("Запрос: топ 10 команд", report_pane.text)
        self.assertIn("Скачать CSV", report_pane.text)
        self.assertEqual([], self.driver.find_elements(By.XPATH, "//*[normalize-space()='Traceback']"))
        console_errors = [
            entry
            for entry in self.driver.get_log("browser")
            if entry["level"] == "SEVERE"
        ]
        self.assertEqual([], console_errors)

    def test_split_pane_tolerates_missing_scroll_panes_during_rerender(self) -> None:
        self.driver.get(FRONTEND_URL)
        self.wait.until(
            lambda driver: driver.find_element(By.CSS_SELECTOR, "textarea[aria-label='Ваше сообщение']")
        )
        self.driver.get_log("browser")

        self.driver.execute_script(
            """
            document.querySelector(".st-key-chat-pane-scroll")?.classList.remove("st-key-chat-pane-scroll");
            document.querySelector(".st-key-report-pane-scroll")?.classList.remove("st-key-report-pane-scroll");
            window.dispatchEvent(new Event("resize"));
            """
        )
        self.driver.execute_async_script(
            "const done = arguments[arguments.length - 1]; requestAnimationFrame(done);"
        )

        console_errors = [
            entry
            for entry in self.driver.get_log("browser")
            if entry["level"] == "SEVERE"
        ]
        self.assertEqual([], console_errors)

    def test_desktop_split_pane_sets_scroll_pane_heights(self) -> None:
        original_size = self.driver.get_window_size()
        self.driver.set_window_size(1280, 720)
        try:
            self.driver.get(FRONTEND_URL)
            self.wait.until(
                lambda driver: driver.find_element(By.CSS_SELECTOR, ".st-key-chat-pane-scroll")
            )
            self.driver.execute_async_script(
                "const done = arguments[arguments.length - 1]; requestAnimationFrame(done);"
            )
            self.wait.until(
                lambda driver: driver.execute_script(
                    """
                    return [
                        document.querySelector(".st-key-chat-pane-scroll"),
                        document.querySelector(".st-key-report-pane-scroll"),
                    ].every((pane) => pane?.style.height.endsWith("px"));
                    """
                )
            )
            pane_sizes = self.driver.execute_script(
                """
                const chatPane = document.querySelector(".st-key-chat-pane-scroll");
                const reportPane = document.querySelector(".st-key-report-pane-scroll");
                const chatColumn = chatPane.closest('[data-testid="stColumn"]');
                const reportColumn = reportPane.closest('[data-testid="stColumn"]');
                const row = chatColumn.parentElement;
                const availableHeight = Math.max(320, Math.floor(window.innerHeight - row.getBoundingClientRect().top));
                const chatChrome = Math.round(chatPane.getBoundingClientRect().top - chatColumn.getBoundingClientRect().top);
                const reportChrome = Math.round(reportPane.getBoundingClientRect().top - reportColumn.getBoundingClientRect().top);
                return {
                    actual: [chatPane.style.height, reportPane.style.height],
                    expected: [
                        `${Math.max(96, availableHeight - chatChrome)}px`,
                        `${Math.max(160, availableHeight - reportChrome)}px`,
                    ],
                };
                """
            )
        finally:
            self.driver.set_window_size(original_size["width"], original_size["height"])

        self.assertEqual(pane_sizes["expected"], pane_sizes["actual"])


if __name__ == "__main__":
    unittest.main()
