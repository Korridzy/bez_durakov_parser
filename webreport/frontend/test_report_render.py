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


if __name__ == "__main__":
    unittest.main()
