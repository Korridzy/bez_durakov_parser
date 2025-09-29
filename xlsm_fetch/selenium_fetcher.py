"""Selenium-based fetcher for Google Drive files."""

import time
import re
from typing import List, Dict, Optional
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options as ChromeOptions

from .base_fetcher import BaseFetcher
import shutil
from pathlib import Path
import zipfile
import tempfile
import hashlib


class SeleniumFetcher(BaseFetcher):
    """Fetcher that uses Selenium browser automation to get files from Google Drive."""

    def __init__(self, folder_url: str, download_dir: Optional[str] = None, headless: bool = True):
        """Initialize with Google Drive folder URL and optional download directory.

        Args:
            folder_url: URL of Google Drive folder
            download_dir: optional download directory
            headless: whether to run Chrome in headless mode (default True)
        """
        super().__init__(folder_url, download_dir)
        self.headless = headless

    def fetch(self) -> List[str]:
        """Fetch list of .xlsm files from Google Drive folder.

        Returns:
            List of file names (strings) that were downloaded and added
        """
        self._log(f"Starting Selenium fetch from: {self.folder_url}")

        # Use download directory from base class (with fallback logic)
        target_download_dir = self.download_dir

        # Create custom Chrome profile with download settings
        # Use project_root, set in BaseFetcher
        project_root = self.project_root
        temp_profile_dir = project_root / "temp_chrome_profile"
        temp_profile_dir.mkdir(exist_ok=True)

        # Create Preferences file manually
        preferences_file = temp_profile_dir / "Default" / "Preferences"
        preferences_file.parent.mkdir(exist_ok=True)

        preferences_data = {
            "download": {
                "default_directory": str(target_download_dir.resolve()),
                "prompt_for_download": False,
                "directory_upgrade": True
            }
        }

        import json
        with open(preferences_file, 'w', encoding='utf-8') as f:
            json.dump(preferences_data, f, indent=2)

        self._log(f"Created Chrome profile with download directory: {target_download_dir}")

        # Setup Chrome options
        chrome_options = ChromeOptions()
        chrome_options.add_argument(f"--user-data-dir={temp_profile_dir}")

        # Enable headless mode for CI / unattended runs
        if self.headless:
            try:
                chrome_options.add_argument("--headless=new")
                chrome_options.add_argument("--hide-scrollbars")
                chrome_options.add_argument("--single-process")
            except Exception:
                # fallback to older headless flag if --headless=new isn't supported
                try:
                    chrome_options.add_argument("--headless")
                except Exception:
                    pass

        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--disable-extensions")
        chrome_options.add_argument("--disable-background-timer-throttling")
        chrome_options.add_argument("--disable-backgrounding-occluded-windows")
        chrome_options.add_argument("--disable-renderer-backgrounding")
        chrome_options.add_argument("--disable-features=TranslateUI")
        chrome_options.add_argument("--disable-ipc-flooding-protection")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        chrome_options.add_argument("--remote-debugging-port=9222")
        chrome_options.add_argument("--disable-web-security")
        chrome_options.add_argument("--allow-running-insecure-content")

        driver = None
        try:
            driver = webdriver.Chrome(options=chrome_options)
            driver.set_page_load_timeout(60)

            self._log("Opening Google Drive folder...")
            driver.get(self.folder_url)

            self._log("Waiting 60 seconds for page to load...")
            time.sleep(60)

            # Step 1: Scroll through files and select all
            self._scroll_and_select_files(driver)

            # Step 2: Find and click download button
            download_success = self._find_download_button_by_properties(driver)
            if not download_success:
                self._log("❌ Failed to find or click download button")
                return []

            # Step 3: Wait for download to complete
            zip_path = self._wait_for_download_completion(driver, target_download_dir)
            if not zip_path:
                self._log("❌ Download did not complete successfully")
                return []

            # Step 4: Process downloaded archive
            added_files = self._process_downloaded_archive(zip_path, target_download_dir)

            # Return the actual file names instead of dummy names
            self._log(f"Fetch completed. Found {len(added_files)} new files.")
            return added_files

        except Exception as e:
            self._log(f"Error during Selenium fetch: {e}")
            return []

        finally:
            if driver:
                driver.quit()

            # Cleanup temporary profile
            if temp_profile_dir.exists():
                try:
                    shutil.rmtree(temp_profile_dir)
                except Exception as cleanup_ex:
                    self._log(f"Warning: Could not cleanup temp profile: {cleanup_ex}")

    def _scroll_and_select_files(self, driver) -> None:
        """Scroll through the file list to load all files and select them all.

        Args:
            driver: Selenium WebDriver instance
        """
        self._log("Starting to scroll down (scrolling container)...")

        # Send ArrowDown directly to the browser window (no element detection)
        max_presses = 500
        stagnation_limit = 60
        presses = 0
        stagnation = 0

        def count_items():
            try:
                return int(driver.execute_script("return (document.querySelectorAll('[data-id]').length)") or 0)
            except Exception:
                return 0

        current_count = count_items()
        self._log(f"Initial item count: {current_count}")

        # Track presses between growths and stagnation levels
        last_growth_press = 0
        while presses < max_presses and stagnation < stagnation_limit:
            presses += 1
            # perform a single down press (no per-press logging to reduce noise)
            try:
                # send key to active window via ActionChains
                ActionChains(driver).send_keys(Keys.ARROW_DOWN).perform()
            except Exception:
                try:
                    # fallback: send to body element
                    body = driver.find_element(By.TAG_NAME, 'body')
                    ActionChains(driver).move_to_element(body).send_keys(Keys.ARROW_DOWN).perform()
                except Exception:
                    pass

            time.sleep(0.6)

            new_count = count_items()
            if new_count > current_count:
                # capture stagnation that occurred before this growth
                prev_stagnation = stagnation
                # compute how many presses happened since last detected growth
                presses_since_last_growth = presses - last_growth_press
                last_growth_press = presses
                stagnation = 0
                self._log(f"Detected growth: {current_count} -> {new_count} (after {presses_since_last_growth} presses, previous stagnation={prev_stagnation})")
                current_count = new_count
            else:
                stagnation += 1

        self._log(f"Key-scrolling finished after {presses} presses, items={current_count}")

        # Select all files with Ctrl+A
        try:
            ActionChains(driver).key_down(Keys.CONTROL).send_keys('a').key_up(Keys.CONTROL).perform()
            self._log('Sent Ctrl+A to select all files')
        except Exception:
            try:
                # fallback: send via ActionChains without key_down/up
                ActionChains(driver).send_keys(Keys.CONTROL, 'a').perform()
                self._log('Sent Ctrl+A (fallback)')
            except Exception:
                self._log('Failed to send Ctrl+A')

        # wait for the selection to be registered and toolbar to appear
        time.sleep(10)

    def _find_download_button_by_properties(self, driver) -> bool:
        """Find download button by combination of properties and click it.

        Args:
            driver: Selenium WebDriver instance

        Returns:
            True if download button was found and clicked successfully, False otherwise
        """
        self._log("=== SEARCHING BY PROPERTY COMBINATION ===")
        self._log("Looking for elements with: role='button', cursor='pointer', blue text, focusable, active, top-right quadrant")

        try:
            # Get screen dimensions
            screen_size = driver.execute_script("return {width: window.innerWidth, height: window.innerHeight};")
            screen_width = screen_size['width']
            screen_height = screen_size['height']

            # Calculate top-right quadrant boundaries (divide screen into 3x3 grid)
            # Top-right quadrant: x > 2/3 * width, y < 1/3 * height
            min_x = (2/3) * screen_width
            max_y = (1/3) * screen_height

            self._log(f"Screen size: {screen_width}x{screen_height}")
            self._log(f"Top-right quadrant: x > {min_x}, y < {max_y}")

            # Find all elements with role='button'
            button_elements = driver.find_elements(By.CSS_SELECTOR, "[role='button']")
            self._log(f"Found {len(button_elements)} elements with role='button'")

            matching_elements = []

            for elem in button_elements:
                try:
                    # Check if element is visible and get its properties
                    if not elem.is_displayed():
                        continue

                    # Get position
                    rect = driver.execute_script(
                        "var r=arguments[0].getBoundingClientRect(); "
                        "return {top:r.top, left:r.left, width:r.width, height:r.height, "
                        "right:r.right, bottom:r.bottom};", elem
                    )

                    # Check if in top-right quadrant
                    elem_x = rect['left']
                    elem_y = rect['top']

                    if elem_x <= min_x or elem_y >= max_y:
                        continue

                    # Get CSS properties
                    css_props = driver.execute_script(
                        "var el=arguments[0]; var styles=window.getComputedStyle(el); "
                        "return {"
                        "  cursor: styles.cursor, "
                        "  color: styles.color, "
                        "  visibility: styles.visibility, "
                        "  display: styles.display "
                        "};", elem
                    )

                    # Check cursor pointer
                    if css_props.get('cursor') != 'pointer':
                        continue

                    # Check if element has blue text (RGB values for blue color)
                    color = css_props.get('color', '')
                    is_blue = False
                    if 'rgb(' in color:
                        # Extract RGB values
                        rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
                        if rgb_match:
                            r, g, b = map(int, rgb_match.groups())
                            # Blue text typically has: low red, low green, high blue
                            # Google's blue is approximately rgb(11, 87, 208)
                            if b > r and b > g and b > 100:
                                is_blue = True

                    if not is_blue:
                        continue

                    # Get attributes for focusability and activity checks
                    attrs = driver.execute_script(
                        "var el=arguments[0]; var result={}; "
                        "for(var i=0; i<el.attributes.length; i++) {"
                        "  result[el.attributes[i].name] = el.attributes[i].value; "
                        "} return result;", elem
                    )

                    # Check if focusable (tabindex >= 0 or naturally focusable)
                    tabindex = attrs.get('tabindex')
                    is_focusable = (tabindex is not None and int(tabindex) >= 0) or elem.tag_name.lower() in ['button', 'a', 'input', 'select', 'textarea']

                    if not is_focusable:
                        continue

                    # Check if active (not disabled)
                    aria_disabled = attrs.get('aria-disabled', '').lower()
                    disabled = attrs.get('disabled')
                    is_active = aria_disabled != 'true' and disabled is None

                    if not is_active:
                        continue

                    # If all conditions are met, add to matching elements
                    matching_elements.append({
                        'element': elem,
                        'position': rect,
                        'css_props': css_props,
                        'attrs': attrs
                    })

                except Exception as ex:
                    self._log(f"Error checking element: {ex}")
                    continue

            self._log(f"✅ Found {len(matching_elements)} elements matching all criteria")

            # Analyze each matching element
            for i, elem_data in enumerate(matching_elements, start=1):
                self._log(f"\n--- MATCHING ELEMENT #{i} DETAILED ANALYSIS ---")
                self._analyze_element_details(driver, elem_data['element'])

            # Click the first matching element if found
            if matching_elements:
                download_button = matching_elements[0]['element']
                self._log("\n🖱️ FOCUSING AND PRESSING SPACE ON DOWNLOAD BUTTON...")

                try:
                    # Focus on the button and press space
                    ActionChains(driver).move_to_element(download_button).perform()
                    time.sleep(1)  # Give time for focus
                    download_button.send_keys(Keys.SPACE)
                    self._log("✅ Download button focused and space pressed successfully")

                    return True  # Download button found and clicked

                except Exception as ex:
                    self._log(f"❌ Error focusing and pressing space on download button: {ex}")
                    return False
            else:
                self._log("❌ No suitable download button found to activate")
                return False

        except Exception as ex:
            self._log(f"❌ Error during property-based search: {ex}")
            return False

    def _wait_for_download_completion(self, driver, target_download_dir):
        """Wait for zip file download to complete."""

        self._log(f"⏳ Waiting for download completion...")
        self._log(f"📁 Target directory: {target_download_dir}")

        # Get initial files in target download directory
        initial_files = set()
        if target_download_dir.exists():
            initial_files = set(f.name for f in target_download_dir.iterdir() if f.is_file())
        self._log(f"Initial files in target directory: {len(initial_files)}")

        max_wait_time = 300  # 5 minutes maximum wait
        check_interval = 5   # Check every 5 seconds
        elapsed_time = 0

        while elapsed_time < max_wait_time:
            time.sleep(check_interval)
            elapsed_time += check_interval

            if not target_download_dir.exists():
                self._log(f"Target directory doesn't exist yet, waiting... ({elapsed_time}s)")
                continue

            # Get current files in target directory
            current_files = set(f.name for f in target_download_dir.iterdir() if f.is_file())
            new_files = current_files - initial_files

            # Check for .crdownload files (Chrome partial downloads)
            partial_downloads = [f for f in current_files if f.endswith('.crdownload')]

            if partial_downloads:
                self._log(f"📥 Download in progress: {partial_downloads} ({elapsed_time}s)")
                continue

            # Check for new zip files
            new_zip_files = [f for f in new_files if f.lower().endswith('.zip')]

            if new_zip_files:
                zip_file = new_zip_files[0]
                zip_path = target_download_dir / zip_file

                # Verify file is complete and not zero bytes
                if zip_path.exists() and zip_path.stat().st_size > 0:
                    self._log(f"✅ Download completed: {zip_file}")
                    self._log(f"📦 File size: {zip_path.stat().st_size} bytes")
                    return zip_path
                else:
                    self._log(f"⚠️ Zip file exists but may be incomplete: {zip_file} ({elapsed_time}s)")

            # Check if any new files appeared
            if new_files:
                self._log(f"📄 New files detected: {new_files} ({elapsed_time}s)")
            else:
                self._log(f"⏳ Still waiting for download... ({elapsed_time}s)")

        self._log(f"⏰ Download wait timeout after {max_wait_time} seconds")

        # List all files in target directory for debugging
        if target_download_dir.exists():
            all_files = list(target_download_dir.iterdir())
            self._log(f"🔍 Final target directory contents:")
            for file_path in all_files:
                if file_path.is_file():
                    self._log(f"  - {file_path.name} ({file_path.stat().st_size} bytes)")

        return None

    def _process_downloaded_archive(self, zip_path: Path, target_download_dir: Path) -> List[str]:
        """Unpack downloaded zip, compare its .xlsm files with target directory and copy new/different ones.

        After processing removes the downloaded zip and temporary extraction directory.

        Returns:
            List of new file names added
        """
        self._log(f"📦 Processing downloaded archive: {zip_path}")

        # Create temporary extraction directory
        tmp_dir = Path(tempfile.mkdtemp(prefix="xlsm_extract_"))
        try:
            # Extract archive
            try:
                with zipfile.ZipFile(zip_path, 'r') as zf:
                    zf.extractall(tmp_dir)
                self._log(f"✅ Extracted archive to temporary dir: {tmp_dir}")
            except Exception as ex:
                self._log(f"❌ Failed to extract archive: {ex}")
                return []

            # Helper to compute SHA256 of a file
            def file_hash(p: Path) -> str:
                h = hashlib.sha256()
                with p.open('rb') as f:
                    for chunk in iter(lambda: f.read(8192), b''):
                        h.update(chunk)
                return h.hexdigest()

            # Gather existing files hashes in target directory
            existing_files = {}
            if target_download_dir.exists():
                for p in target_download_dir.glob('*.xlsm'):
                    if p.is_file():
                        try:
                            existing_files[p.name] = file_hash(p)
                        except Exception:
                            existing_files[p.name] = None

            # Find extracted .xlsm files
            extracted_files = [p for p in tmp_dir.rglob('*.xlsm') if p.is_file()]
            self._log(f"Found {len(extracted_files)} extracted .xlsm files")

            added_files = []
            for ef in extracted_files:
                try:
                    name = ef.name
                    h = file_hash(ef)

                    if name in existing_files and existing_files[name] == h:
                        # same name and content -> skip
                        continue

                    # Decide destination path. If name exists but different content -> add hash suffix
                    if name in existing_files:
                        dest_name = f"{ef.stem}_{h[:8]}{ef.suffix}"
                    else:
                        dest_name = name

                    dest_path = Path(target_download_dir) / dest_name
                    shutil.copy2(ef, dest_path)
                    added_files.append(dest_path.name)
                    self._log(f"➕ Added file: {dest_path.name}")
                except Exception as ex:
                    self._log(f"❌ Error while handling extracted file {ef}: {ex}")

            if not added_files:
                self._log("ℹ️ No new files to add from the archive")
            else:
                self._log(f"✅ Total new files added: {len(added_files)}")

            return added_files

        finally:
            # Remove downloaded archive
            try:
                zip_path.unlink()
                self._log(f"🗑️ Removed downloaded archive: {zip_path}")
            except Exception as ex:
                self._log(f"⚠️ Could not remove archive {zip_path}: {ex}")

            # Cleanup temporary extraction directory
            try:
                shutil.rmtree(tmp_dir)
                self._log(f"🗑️ Removed temporary extraction dir: {tmp_dir}")
            except Exception as ex:
                self._log(f"⚠️ Could not remove temp dir {tmp_dir}: {ex}")

    def _analyze_element_details(self, driver, elem):
        """Analyze element details (same as before but extracted to separate method)."""
        try:
            # Basic properties
            tag_name = elem.tag_name
            self._log(f"Tag: {tag_name}")

            # All attributes
            attrs = driver.execute_script(
                "var el=arguments[0]; var result={}; "
                "for(var i=0; i<el.attributes.length; i++) {"
                "  result[el.attributes[i].name] = el.attributes[i].value; "
                "} return result;", elem
            )
            self._log(f"Attributes: {attrs}")

            # Position and size
            rect = driver.execute_script(
                "var r=arguments[0].getBoundingClientRect(); "
                "return {top:r.top, left:r.left, width:r.width, height:r.height, "
                "right:r.right, bottom:r.bottom};", elem
            )
            self._log(f"Position: {rect}")

            # CSS properties
            css_props = driver.execute_script(
                "var el=arguments[0]; var styles=window.getComputedStyle(el); "
                "return {"
                "  display: styles.display, "
                "  visibility: styles.visibility, "
                "  position: styles.position, "
                "  zIndex: styles.zIndex, "
                "  backgroundColor: styles.backgroundColor, "
                "  color: styles.color, "
                "  fontSize: styles.fontSize, "
                "  fontFamily: styles.fontFamily, "
                "  fontWeight: styles.fontWeight, "
                "  cursor: styles.cursor, "
                "  border: styles.border, "
                "  borderRadius: styles.borderRadius, "
                "  padding: styles.padding, "
                "  margin: styles.margin "
                "};", elem
            )
            self._log(f"CSS Properties: {css_props}")

            # Parent element info
            parent_info = driver.execute_script(
                "var el=arguments[0].parentElement; "
                "if(!el) return null; "
                "var attrs={}; "
                "for(var i=0; i<el.attributes.length; i++) {"
                "  attrs[el.attributes[i].name] = el.attributes[i].value; "
                "} "
                "return {tagName: el.tagName, attributes: attrs};", elem
            )
            self._log(f"Parent: {parent_info}")

            # XPath generation
            xpath = driver.execute_script(
                "function getXPath(el) {"
                "  if(el.id) return 'id(\"' + el.id + '\")'; "
                "  var parts = []; "
                "  while(el && el.nodeType === 1) {"
                "    var nb = 0; "
                "    var sib = el.previousSibling; "
                "    while(sib) {"
                "      if(sib.nodeType === 1 && sib.nodeName === el.nodeName) nb++; "
                "      sib = sib.previousSibling; "
                "    } "
                "    var idx = nb ? nb + 1 : 1; "
                "    parts.unshift(el.nodeName.toLowerCase() + '[' + idx + ']'); "
                "    el = el.parentNode; "
                "  } "
                "  return '/' + parts.join('/'); "
                "} "
                "return getXPath(arguments[0]);", elem
            )
            self._log(f"Generated XPath: {xpath}")

            # CSS Selector generation
            css_selector = driver.execute_script(
                "function getCSSPath(el) {"
                "  if(el.id) return '#' + el.id; "
                "  var path = []; "
                "  while(el && el.nodeType === 1) {"
                "    var selector = el.nodeName.toLowerCase(); "
                "    if(el.className) {"
                "      selector += '.' + el.className.replace(/\\s+/g, '.'); "
                "    } "
                "    var sib = el.previousElementSibling; "
                "    var nth = 1; "
                "    while(sib) {"
                "      if(sib.nodeName.toLowerCase() === selector.split('.')[0]) nth++; "
                "      sib = sib.previousElementSibling; "
                "    } "
                "    if(nth > 1) selector += ':nth-of-type(' + nth + ')'; "
                "    path.unshift(selector); "
                "    el = el.parentElement; "
                "  } "
                "  return path.join(' > '); "
                "} "
                "return getCSSPath(arguments[0]);", elem
            )
            self._log(f"Generated CSS Selector: {css_selector}")

            # Event listeners info
            events_info = driver.execute_script(
                "var el=arguments[0]; "
                "return {"
                "  onclick: el.onclick ? 'present' : 'none', "
                "  hasEventListeners: typeof el._eventListeners !== 'undefined' ? 'possible' : 'unknown' "
                "};", elem
            )
            self._log(f"Event Handlers: {events_info}")

            # Text content variations
            text_info = driver.execute_script(
                "var el=arguments[0]; "
                "return {"
                "  textContent: el.textContent, "
                "  innerText: el.innerText, "
                "  innerHTML: el.innerHTML, "
                "  outerHTML: el.outerHTML.substring(0, 500) "
                "};", elem
            )
            self._log(f"Text Content: {text_info['textContent']}")
            self._log(f"Inner Text: {text_info['innerText']}")
            self._log(f"Inner HTML: {text_info['innerHTML']}")
            self._log(f"Outer HTML (first 500 chars): {text_info['outerHTML']}")

            # Unique characteristics for future identification
            unique_props = []

            if attrs.get('id'):
                unique_props.append(f"id='{attrs['id']}'")
            if attrs.get('class'):
                unique_props.append(f"class='{attrs['class']}'")
            if attrs.get('role'):
                unique_props.append(f"role='{attrs['role']}'")
            if attrs.get('data-tooltip'):
                unique_props.append(f"data-tooltip='{attrs['data-tooltip']}'")
            if attrs.get('aria-label'):
                unique_props.append(f"aria-label='{attrs['aria-label']}'")

            # Add CSS-based identification
            if css_props.get('backgroundColor') and css_props['backgroundColor'] != 'rgba(0, 0, 0, 0)':
                unique_props.append(f"background-color: {css_props['backgroundColor']}")

            self._log(f"🎯 UNIQUE IDENTIFICATION PROPERTIES: {unique_props}")

            # Alternative selectors for future use
            alt_selectors = []
            if attrs.get('id'):
                alt_selectors.append(f"#{attrs['id']}")
            if attrs.get('class'):
                classes = attrs['class'].replace(' ', '.')
                alt_selectors.append(f"{tag_name}.{classes}")
            if attrs.get('role'):
                alt_selectors.append(f"[role='{attrs['role']}']")
            if attrs.get('data-tooltip'):
                alt_selectors.append(f"[data-tooltip='{attrs['data-tooltip']}']")

            self._log(f"🔍 ALTERNATIVE SELECTORS: {alt_selectors}")

        except Exception as ex:
            self._log(f"❌ Error analyzing element: {ex}")

    def _analyze_download_button(self, driver):
        """Find and analyze 'Скачать все' button with detailed property extraction."""
        self._log("=== ANALYZING DOWNLOAD BUTTON ===")

        # Find element with exact text 'Скачать все'
        try:
            xpath_exact = "//*[normalize-space(string())='Скачать все']"
            elements = driver.find_elements(By.XPATH, xpath_exact)

            if not elements:
                self._log("❌ No element with exact text 'Скачать все' found")
                return

            self._log(f"✅ Found {len(elements)} element(s) with exact text 'Скачать все'")

            for i, elem in enumerate(elements, start=1):
                self._log(f"\n--- ELEMENT #{i} DETAILED ANALYSIS ---")

                try:
                    # Basic properties
                    tag_name = elem.tag_name
                    self._log(f"Tag: {tag_name}")

                    # All attributes
                    attrs = driver.execute_script(
                        "var el=arguments[0]; var result={}; "
                        "for(var i=0; i<el.attributes.length; i++) {"
                        "  result[el.attributes[i].name] = el.attributes[i].value; "
                        "} return result;", elem
                    )
                    self._log(f"Attributes: {attrs}")

                    # Position and size
                    rect = driver.execute_script(
                        "var r=arguments[0].getBoundingClientRect(); "
                        "return {top:r.top, left:r.left, width:r.width, height:r.height, "
                        "right:r.right, bottom:r.bottom};", elem
                    )
                    self._log(f"Position: {rect}")

                    # CSS properties
                    css_props = driver.execute_script(
                        "var el=arguments[0]; var styles=window.getComputedStyle(el); "
                        "return {"
                        "  display: styles.display, "
                        "  visibility: styles.visibility, "
                        "  position: styles.position, "
                        "  zIndex: styles.zIndex, "
                        "  backgroundColor: styles.backgroundColor, "
                        "  color: styles.color, "
                        "  fontSize: styles.fontSize, "
                        "  fontFamily: styles.fontFamily, "
                        "  fontWeight: styles.fontWeight, "
                        "  cursor: styles.cursor, "
                        "  border: styles.border, "
                        "  borderRadius: styles.borderRadius, "
                        "  padding: styles.padding, "
                        "  margin: styles.margin "
                        "};", elem
                    )
                    self._log(f"CSS Properties: {css_props}")

                    # Parent element info
                    parent_info = driver.execute_script(
                        "var el=arguments[0].parentElement; "
                        "if(!el) return null; "
                        "var attrs={}; "
                        "for(var i=0; i<el.attributes.length; i++) {"
                        "  attrs[el.attributes[i].name] = el.attributes[i].value; "
                        "} "
                        "return {tagName: el.tagName, attributes: attrs};", elem
                    )
                    self._log(f"Parent: {parent_info}")

                    # XPath generation
                    xpath = driver.execute_script(
                        "function getXPath(el) {"
                        "  if(el.id) return 'id(\"' + el.id + '\")'; "
                        "  var parts = []; "
                        "  while(el && el.nodeType === 1) {"
                        "    var nb = 0; "
                        "    var sib = el.previousSibling; "
                        "    while(sib) {"
                        "      if(sib.nodeType === 1 && sib.nodeName === el.nodeName) nb++; "
                        "      sib = sib.previousSibling; "
                        "    } "
                        "    var idx = nb ? nb + 1 : 1; "
                        "    parts.unshift(el.nodeName.toLowerCase() + '[' + idx + ']'); "
                        "    el = el.parentNode; "
                        "  } "
                        "  return '/' + parts.join('/'); "
                        "} "
                        "return getXPath(arguments[0]);", elem
                    )
                    self._log(f"Generated XPath: {xpath}")

                    # CSS Selector generation
                    css_selector = driver.execute_script(
                        "function getCSSPath(el) {"
                        "  if(el.id) return '#' + el.id; "
                        "  var path = []; "
                        "  while(el && el.nodeType === 1) {"
                        "    var selector = el.nodeName.toLowerCase(); "
                        "    if(el.className) {"
                        "      selector += '.' + el.className.replace(/\\s+/g, '.'); "
                        "    } "
                        "    var sib = el.previousElementSibling; "
                        "    var nth = 1; "
                        "    while(sib) {"
                        "      if(sib.nodeName.toLowerCase() === selector.split('.')[0]) nth++; "
                        "      sib = sib.previousElementSibling; "
                        "    } "
                        "    if(nth > 1) selector += ':nth-of-type(' + nth + ')'; "
                        "    path.unshift(selector); "
                        "    el = el.parentElement; "
                        "  } "
                        "  return path.join(' > '); "
                        "} "
                        "return getCSSPath(arguments[0]);", elem
                    )
                    self._log(f"Generated CSS Selector: {css_selector}")

                    # Event listeners info
                    events_info = driver.execute_script(
                        "var el=arguments[0]; "
                        "return {"
                        "  onclick: el.onclick ? 'present' : 'none', "
                        "  hasEventListeners: typeof el._eventListeners !== 'undefined' ? 'possible' : 'unknown' "
                        "};", elem
                    )
                    self._log(f"Event Handlers: {events_info}")

                    # Text content variations
                    text_info = driver.execute_script(
                        "var el=arguments[0]; "
                        "return {"
                        "  textContent: el.textContent, "
                        "  innerText: el.innerText, "
                        "  innerHTML: el.innerHTML, "
                        "  outerHTML: el.outerHTML.substring(0, 500) "
                        "};", elem
                    )
                    self._log(f"Text Content: {text_info['textContent']}")
                    self._log(f"Inner Text: {text_info['innerText']}")
                    self._log(f"Inner HTML: {text_info['innerHTML']}")
                    self._log(f"Outer HTML (first 500 chars): {text_info['outerHTML']}")

                    # Unique characteristics for future identification
                    unique_props = []

                    if attrs.get('id'):
                        unique_props.append(f"id='{attrs['id']}'")
                    if attrs.get('class'):
                        unique_props.append(f"class='{attrs['class']}'")
                    if attrs.get('role'):
                        unique_props.append(f"role='{attrs['role']}'")
                    if attrs.get('data-tooltip'):
                        unique_props.append(f"data-tooltip='{attrs['data-tooltip']}'")
                    if attrs.get('aria-label'):
                        unique_props.append(f"aria-label='{attrs['aria-label']}'")

                    # Add CSS-based identification
                    if css_props.get('backgroundColor') and css_props['backgroundColor'] != 'rgba(0, 0, 0, 0)':
                        unique_props.append(f"background-color: {css_props['backgroundColor']}")

                    self._log(f"🎯 UNIQUE IDENTIFICATION PROPERTIES: {unique_props}")

                    # Alternative selectors for future use
                    alt_selectors = []
                    if attrs.get('id'):
                        alt_selectors.append(f"#{attrs['id']}")
                    if attrs.get('class'):
                        classes = attrs['class'].replace(' ', '.')
                        alt_selectors.append(f"{tag_name}.{classes}")
                    if attrs.get('role'):
                        alt_selectors.append(f"[role='{attrs['role']}']")
                    if attrs.get('data-tooltip'):
                        alt_selectors.append(f"[data-tooltip='{attrs['data-tooltip']}']")

                    self._log(f"🔍 ALTERNATIVE SELECTORS: {alt_selectors}")

                except Exception as ex:
                    self._log(f"❌ Error analyzing element #{i}: {ex}")

        except Exception as ex:
            self._log(f"❌ Error during download button analysis: {ex}")
