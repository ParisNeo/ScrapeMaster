import sys
import json
import os
from urllib.parse import urlparse
import time # Import time for timestamp in filename

# --- Check and Install Dependencies ---
try:
    # Try importing PyQt5 first
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLineEdit, QPushButton, QTextEdit, QLabel, QAction, QFileDialog,
        QMessageBox, QMenu, QStatusBar, QTabWidget, QDialog, QCheckBox,
        QDialogButtonBox, QGridLayout, QSpinBox # Added QSpinBox
    )
    from PyQt5.QtCore import QSettings, Qt, pyqtSignal
    from PyQt5.QtGui import QIcon # Optional
except ImportError:
    # If PyQt5 fails, try installing it and markdown via pipmaster
    print("PyQt5 not found. Attempting to install dependencies using pipmaster...")
    try:
        import pipmaster as pm
        # Add 'markdown' library for rendering
        pm.ensure_packages(["PyQt5", "markdown"], verbose=True)
        # Re-try imports after installation
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLineEdit, QPushButton, QTextEdit, QLabel, QAction, QFileDialog,
            QMessageBox, QMenu, QStatusBar, QTabWidget, QDialog, QCheckBox,
            QDialogButtonBox, QGridLayout, QSpinBox # Added QSpinBox
        )
        from PyQt5.QtCore import QSettings, Qt, pyqtSignal
        from PyQt5.QtGui import QIcon
    except ImportError:
        print("Failed to install or import PyQt5/markdown. Please install them manually and run again.")
        print("pip install PyQt5 markdown")
        sys.exit(1)
    except Exception as e:
         print(f"An error occurred during dependency setup: {e}")
         sys.exit(1)

# --- Import Markdown library ---
try:
    import markdown
except ImportError:
    print("Error: 'markdown' library not found even after check. Please install it: 'pip install markdown'")
    sys.exit(1)


# --- Import the ScrapeMaster Library ---
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
try:
    from scrapemaster import ScrapeMaster
    from scrapemaster.core import SUPPORTED_STRATEGIES, DEFAULT_STRATEGY_ORDER
except ImportError as e:
     print(f"Error importing ScrapeMaster library: {e}")
     print("Please ensure the ScrapeMaster library is installed correctly.")
     print("You might need to run 'pip install .' from the main ScrapeMaster directory.")
     sys.exit(1)


# --- Constants ---
APP_NAME = "ScrapeMaster GUI"
ORG_NAME = "MyCompany"
MAX_RECENT_FILES = 10
SETTINGS_RECENT_FILES = "recentFiles"
SETTINGS_STRATEGY_PREFIX = "settings/strategyEnabled_"
SETTINGS_HEADLESS = "settings/headlessMode"
SETTINGS_CRAWL_DEPTH = "settings/crawlDepth" # New setting key
SETTINGS_WINDOW_GEOMETRY = "window/geometry"
SETTINGS_WINDOW_STATE = "window/state"


# --- Helper Function (URL Validation - Defined within the GUI script) ---
def is_valid_url_for_gui(url_string: str) -> bool:
    if not isinstance(url_string, str): return False
    try:
        result = urlparse(url_string)
        return all([result.scheme, result.netloc]) and result.scheme in ['http', 'https']
    except ValueError: return False

# --- Settings Dialog ---
class SettingsDialog(QDialog):
    settingsChanged = pyqtSignal()

    def __init__(self, settings: QSettings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Scraper Settings")
        self.setMinimumWidth(350)

        layout = QVBoxLayout(self)
        grid_layout = QGridLayout()

        # --- Strategy Checkboxes ---
        self.strategy_checkboxes = {}
        grid_layout.addWidget(QLabel("<b>Scraping Strategies (in order):</b>"), 0, 0, 1, 2)
        row = 1
        for strategy in DEFAULT_STRATEGY_ORDER:
            if strategy not in SUPPORTED_STRATEGIES: continue
            checkbox = QCheckBox(strategy.capitalize())
            setting_key = f"{SETTINGS_STRATEGY_PREFIX}{strategy}"
            is_enabled = self.settings.value(setting_key, True, type=bool)
            checkbox.setChecked(is_enabled)
            grid_layout.addWidget(checkbox, row, 0)
            self.strategy_checkboxes[strategy] = checkbox
            row += 1

        # --- Headless Mode & Crawl Depth ---
        grid_layout.addWidget(QLabel("<b>Options:</b>"), row, 0, 1, 2)
        row += 1
        self.headless_checkbox = QCheckBox("Run browser headless (no visible window)")
        headless_enabled = self.settings.value(SETTINGS_HEADLESS, True, type=bool)
        self.headless_checkbox.setChecked(headless_enabled)
        grid_layout.addWidget(self.headless_checkbox, row, 0, 1, 2)
        row += 1

        # --- Crawl Depth SpinBox ---
        grid_layout.addWidget(QLabel("Crawl Depth:"), row, 0)
        self.crawl_depth_spinbox = QSpinBox()
        self.crawl_depth_spinbox.setRange(0, 10) # Allow depth 0 (single page) up to 10
        self.crawl_depth_spinbox.setToolTip("0 = Scrape only the entered URL.\n>0 = Follow links up to this depth within the same domain.")
        current_depth = self.settings.value(SETTINGS_CRAWL_DEPTH, 0, type=int) # Default to 0
        self.crawl_depth_spinbox.setValue(current_depth)
        grid_layout.addWidget(self.crawl_depth_spinbox, row, 1)
        row += 1

        layout.addLayout(grid_layout)
        layout.addStretch(1)

        # --- Dialog Buttons ---
        self.buttonBox = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttonBox.accepted.connect(self.save_settings)
        self.buttonBox.rejected.connect(self.reject)
        layout.addWidget(self.buttonBox)

    def save_settings(self):
        at_least_one_strategy = False
        for strategy, checkbox in self.strategy_checkboxes.items():
            setting_key = f"{SETTINGS_STRATEGY_PREFIX}{strategy}"
            is_enabled = checkbox.isChecked()
            self.settings.setValue(setting_key, is_enabled)
            if is_enabled: at_least_one_strategy = True

        if not at_least_one_strategy:
            QMessageBox.warning(self, "Settings Error", "Please select at least one scraping strategy.")
            return

        self.settings.setValue(SETTINGS_HEADLESS, self.headless_checkbox.isChecked())
        self.settings.setValue(SETTINGS_CRAWL_DEPTH, self.crawl_depth_spinbox.value()) # Save depth
        self.settingsChanged.emit()
        self.accept()

# --- Main Application Class ---

class DocScraperAppGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = QSettings(ORG_NAME, APP_NAME)
        self.current_file_path = None
        self.initUI()
        self.update_recent_files_menu()
        self.load_window_state()

    def initUI(self):
        self.setWindowTitle(APP_NAME)
        # ... (rest of initUI is the same: central widget, url layout, tab widget, buttons) ...
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        url_layout = QHBoxLayout()
        url_label = QLabel("URL:")
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("Enter documentation URL here...")
        self.url_input.returnPressed.connect(self.scrape_url_action)
        scrape_button = QPushButton("Scrape")
        scrape_button.clicked.connect(self.scrape_url_action)
        url_layout.addWidget(url_label)
        url_layout.addWidget(self.url_input)
        url_layout.addWidget(scrape_button)
        main_layout.addLayout(url_layout)
        self.tab_widget = QTabWidget()
        self.raw_markdown_output = QTextEdit()
        self.raw_markdown_output.setPlaceholderText("Raw scraped Markdown content will appear here...")
        self.raw_markdown_output.setReadOnly(False)
        self.raw_markdown_output.setAcceptRichText(False)
        self.rendered_output = QTextEdit()
        self.rendered_output.setPlaceholderText("Rendered view (if Markdown is scraped successfully).")
        self.rendered_output.setReadOnly(True)
        self.tab_widget.addTab(self.raw_markdown_output, "Raw Markdown")
        self.tab_widget.addTab(self.rendered_output, "Rendered")
        main_layout.addWidget(self.tab_widget)
        button_layout = QHBoxLayout()
        self.copy_button = QPushButton("Copy Raw Markdown")
        self.copy_button.clicked.connect(self.copy_markdown_action)
        self.copy_button.setEnabled(False)
        button_layout.addWidget(self.copy_button)
        button_layout.addStretch(1)
        main_layout.addLayout(button_layout)
        self.create_menus()
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("Ready")
        self.update_title()


    def create_menus(self):
        menubar = self.menuBar()

        # --- File Menu ---
        file_menu = menubar.addMenu('&File')
        load_action = QAction('&Load JSON...', self); load_action.setShortcut('Ctrl+O'); load_action.setStatusTip('Load scraped data from a JSON file'); load_action.triggered.connect(self.load_file_dialog); file_menu.addAction(load_action)
        save_as_action = QAction('Save As &JSON...', self); save_as_action.setShortcut('Ctrl+S'); save_as_action.setStatusTip('Save URL and Markdown to a JSON file'); save_as_action.triggered.connect(self.save_file_dialog); file_menu.addAction(save_as_action)
        # --- Add Export Markdown Action ---
        export_md_action = QAction('&Export as Markdown (.md)...', self)
        export_md_action.setStatusTip('Export the raw Markdown content to a .md file')
        export_md_action.triggered.connect(self.export_markdown_dialog)
        file_menu.addAction(export_md_action)
        # --- End Add ---
        file_menu.addSeparator()
        self.recent_files_menu = QMenu('&Recent Files', self); file_menu.addMenu(self.recent_files_menu)
        file_menu.addSeparator()
        exit_action = QAction('&Exit', self); exit_action.setShortcut('Ctrl+Q'); exit_action.setStatusTip('Exit application'); exit_action.triggered.connect(self.close); file_menu.addAction(exit_action)

        # --- Options Menu ---
        options_menu = menubar.addMenu('&Options')
        settings_action = QAction('&Settings...', self)
        settings_action.setStatusTip('Configure scraping strategies and options')
        settings_action.triggered.connect(self.open_settings_dialog)
        options_menu.addAction(settings_action)

    # --- load_window_state, save_window_state, update_title (same as before) ---
    def load_window_state(self):
        geometry = self.settings.value(SETTINGS_WINDOW_GEOMETRY); state = self.settings.value(SETTINGS_WINDOW_STATE)
        if geometry: self.restoreGeometry(geometry)
        if state: self.restoreState(state)
        else: self.setGeometry(100, 100, 800, 600)
    def save_window_state(self):
        self.settings.setValue(SETTINGS_WINDOW_GEOMETRY, self.saveGeometry()); self.settings.setValue(SETTINGS_WINDOW_STATE, self.saveState())
    def update_title(self):
        title = APP_NAME;
        if self.current_file_path: title += f" - {os.path.basename(self.current_file_path)}"
        self.setWindowTitle(title)

    # --- Actions ---

    def open_settings_dialog(self):
        dialog = SettingsDialog(self.settings, self)
        dialog.exec_()

    def scrape_url_action(self):
        url = self.url_input.text().strip()
        if not url: QMessageBox.warning(self, "Input Error", "Please enter a URL."); return

        # --- URL Validation (same as before) ---
        if not is_valid_url_for_gui(url):
            if not url.startswith(('http://', 'https://')):
                url_https = f"https://{url}"; url_http = f"http://{url}"
                if is_valid_url_for_gui(url_https): url = url_https; self.url_input.setText(url); print(f"Assuming HTTPS: {url}")
                elif is_valid_url_for_gui(url_http): url = url_http; self.url_input.setText(url); print(f"Assuming HTTP: {url}")
                else: QMessageBox.warning(self, "Input Error", f"Invalid URL: {self.url_input.text()}"); return
            else: QMessageBox.warning(self, "Input Error", f"Invalid URL: {self.url_input.text()}"); return

        # --- Get Settings ---
        active_strategies = [s for s in DEFAULT_STRATEGY_ORDER if self.settings.value(f"{SETTINGS_STRATEGY_PREFIX}{s}", True, type=bool) and s in SUPPORTED_STRATEGIES]
        if not active_strategies: QMessageBox.critical(self, "Config Error", "No scraping strategies enabled!"); return
        headless_mode = self.settings.value(SETTINGS_HEADLESS, True, type=bool)
        crawl_depth = self.settings.value(SETTINGS_CRAWL_DEPTH, 0, type=int) # Get crawl depth

        # --- Use ScrapeMaster Library ---
        crawl_msg = f", Crawl Depth: {crawl_depth}" if crawl_depth > 0 else ""
        self.statusBar.showMessage(f"Scraping {url} (Strategies: {active_strategies}, Headless: {headless_mode}{crawl_msg})...")
        self.raw_markdown_output.setPlaceholderText(f"Scraping {url}{crawl_msg}...\nPlease wait...")
        self.rendered_output.setPlaceholderText("Waiting for content...")
        self.raw_markdown_output.clear(); self.rendered_output.clear()
        self.copy_button.setEnabled(False)
        QApplication.processEvents()

        markdown_content = None
        html_content = None
        final_status_message = "Scraping finished."

        try:
            scraper = ScrapeMaster(url, strategy=active_strategies, headless=headless_mode)

            # Call scrape_all, passing the crawl depth
            results = scraper.scrape_all(
                max_depth=crawl_depth,
                convert_to_markdown=True
                # Optionally pass other params like crawl_delay, allowed_domains from settings too
            )

            if results:
                markdown_content = results.get('markdown') # Aggregated markdown if crawling
                if markdown_content:
                    self.raw_markdown_output.setPlainText(markdown_content)
                    self.copy_button.setEnabled(True)
                    crawl_info = f", {len(results.get('visited_urls',[]))} pages scraped" if crawl_depth > 0 else ""
                    final_status_message = f"Success! (Strategy: {scraper.last_strategy_used or 'N/A'}{crawl_info})"
                    self.raw_markdown_output.setPlaceholderText("Raw scraped Markdown content.")
                    try:
                        html_content = markdown.markdown(markdown_content, extensions=['fenced_code', 'tables', 'extra'])
                        self.rendered_output.setHtml(html_content)
                        self.rendered_output.setPlaceholderText("Rendered Markdown content.")
                    except Exception as e_render:
                        self.rendered_output.setPlainText(f"[Render Error: {e_render}]")
                        self.rendered_output.setPlaceholderText("Failed to render Markdown.")

                else: # No Markdown found (even if crawl was attempted)
                    fallback_text = "\n---\n".join(results.get('texts', [])) # Aggregate all texts
                    message = "[INFO] No primary Markdown content generated."
                    if fallback_text:
                         message += " Displaying all text fragments."
                         self.raw_markdown_output.setPlainText(fallback_text)
                         self.copy_button.setEnabled(True)
                    else:
                         message += " No text fragments found either."
                         self.raw_markdown_output.setPlainText(message)
                         self.copy_button.setEnabled(False)
                    final_status_message = message
                    self.raw_markdown_output.setPlaceholderText(message)
                    self.rendered_output.setPlaceholderText("No Markdown content to render.")

                # Report failed URLs if crawling
                if crawl_depth > 0 and results.get('failed_urls'):
                    failed_list = "\n - ".join(results['failed_urls'])
                    print(f"Warning: Failed to scrape the following URLs during crawl:\n - {failed_list}") # Log failed URLs
                    QMessageBox.warning(self,"Crawl Warning", f"Failed to scrape {len(results['failed_urls'])} URLs during crawl. Check console log for details.")


            else: # Fetch/scrape_all returned None
                error_message = scraper.get_last_error() or "Unknown scraping error."
                self.raw_markdown_output.setPlainText(f"Error:\n{error_message}")
                final_status_message = f"Scraping failed. Check Raw tab."
                self.raw_markdown_output.setPlaceholderText("Scraping failed. See error message above.")
                self.rendered_output.setPlaceholderText("Scraping failed.")
                if scraper.last_error and ("All scraping strategies failed" in scraper.last_error or "Could not initialize" in scraper.last_error):
                     QMessageBox.critical(self, "Scraping Error", error_message)

        except Exception as e:
            import traceback; error_details = traceback.format_exc()
            error_msg = f"Critical Application Error:\n{e}\n\nDetails:\n{error_details}"
            self.raw_markdown_output.setPlainText(error_msg); self.rendered_output.setPlainText(f"[App Error: {e}]")
            final_status_message = "A critical error occurred."
            self.raw_markdown_output.setPlaceholderText("Critical error."); self.rendered_output.setPlaceholderText("Critical error.")
            QMessageBox.critical(self, "Application Error", f"An unexpected error occurred:\n{e}")

        self.statusBar.showMessage(final_status_message, 5000)
        self.current_file_path = None
        self.update_title()

    def copy_markdown_action(self):
        clipboard = QApplication.clipboard(); raw_markdown_text = self.raw_markdown_output.toPlainText()
        clipboard.setText(raw_markdown_text); self.statusBar.showMessage("Raw Markdown copied to clipboard!", 2000)

    def save_file_dialog(self):
        url = self.url_input.text(); raw_markdown = self.raw_markdown_output.toPlainText()
        if not url or not raw_markdown or raw_markdown.startswith("Error:") or raw_markdown.startswith("[INFO]") or not raw_markdown.strip():
            QMessageBox.warning(self, "Save Error", "Need valid URL and content to save."); return
        try:
            parsed_url = urlparse(url); safe_domain = parsed_url.netloc.replace('.', '_'); safe_path = parsed_url.path.replace('/', '_').strip('_');
            if not safe_path: safe_path = 'index'; suggested_name = f"{safe_domain}_{safe_path}.json"; suggested_name = "".join(c for c in suggested_name if c.isalnum() or c in ('_', '-')).rstrip()[:100] + ".json"
        except Exception: suggested_name = "scraped_data.json"
        options = QFileDialog.Options(); file_path, _ = QFileDialog.getSaveFileName(self, "Save Scraped Data (JSON)", suggested_name, "JSON Files (*.json);;All Files (*)", options=options)
        if file_path:
            if not file_path.lower().endswith('.json'): file_path += '.json'
            self.save_file(file_path)

    def save_file(self, file_path):
        data = { "url": self.url_input.text(), "markdown": self.raw_markdown_output.toPlainText() }
        try:
            with open(file_path, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4, ensure_ascii=False)
            self.current_file_path = file_path; self.add_recent_file(file_path); self.update_title(); self.statusBar.showMessage(f"Data saved to {os.path.basename(file_path)}", 3000)
        except Exception as e: QMessageBox.critical(self, "Save Error", f"Could not save JSON file:\n{e}"); self.statusBar.showMessage("Save failed.", 3000)


    # --- NEW Export Markdown Dialog ---
    def export_markdown_dialog(self):
        """Opens a dialog to export raw markdown content to a .md file."""
        raw_markdown = self.raw_markdown_output.toPlainText()
        url = self.url_input.text()

        if not raw_markdown or raw_markdown.startswith("Error:") or raw_markdown.startswith("[INFO]") or not raw_markdown.strip():
            QMessageBox.warning(self, "Export Error", "No valid Markdown content available to export.")
            return

        # Suggest filename based on URL or timestamp
        suggested_name = "scraped_content.md"
        if url and is_valid_url_for_gui(url):
            try:
                parsed_url = urlparse(url); safe_domain = parsed_url.netloc.replace('.', '_'); safe_path = parsed_url.path.replace('/', '_').strip('_');
                if not safe_path: safe_path = 'index'; base_name = f"{safe_domain}_{safe_path}"
                suggested_name = "".join(c for c in base_name if c.isalnum() or c in ('_', '-')).rstrip()[:100] + ".md"
            except Exception: pass # Keep default name if URL parsing fails
        else:
            # Use timestamp if no valid URL
             timestamp = time.strftime("%Y%m%d_%H%M%S")
             suggested_name = f"scraped_content_{timestamp}.md"

        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Export Raw Markdown",
            suggested_name,
            "Markdown Files (*.md);;Text Files (*.txt);;All Files (*)",
            options=options
        )

        if file_path:
            # Ensure .md extension if filter selected it
            # if _ == "Markdown Files (*.md)" and not file_path.lower().endswith('.md'):
            #      file_path += '.md' # Append if filter implies .md but user didn't type it
            # Or simply force it:
            if not file_path.lower().endswith(('.md', '.txt')):
                file_path += '.md' # Default to .md if no known text extension

            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(raw_markdown)
                self.statusBar.showMessage(f"Markdown exported to {os.path.basename(file_path)}", 3000)
            except IOError as e:
                QMessageBox.critical(self, "Export Error", f"Could not export Markdown file:\n{e}")
                self.statusBar.showMessage("Export failed.", 3000)
            except Exception as e:
                 QMessageBox.critical(self, "Export Error", f"An unexpected error occurred during export:\n{e}")
                 self.statusBar.showMessage("Export failed.", 3000)


    def load_file_dialog(self): # Renamed action in menu to Load JSON...
        options = QFileDialog.Options(); file_path, _ = QFileDialog.getOpenFileName(self, "Load Scraped Data (JSON)", "", "JSON Files (*.json);;All Files (*)", options=options)
        if file_path: self.load_file(file_path)

    def load_file(self, file_path):
        """Loads data from the specified JSON file."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f: data = json.load(f)
            if "url" not in data or "markdown" not in data: raise ValueError("JSON file missing 'url' or 'markdown' key.")
            loaded_url = data.get("url", ""); loaded_markdown = data.get("markdown", "")
            self.url_input.setText(loaded_url); self.raw_markdown_output.setPlainText(loaded_markdown)
            is_valid_content = bool(loaded_markdown and not loaded_markdown.startswith("Error:") and not loaded_markdown.startswith("[INFO]"))
            if is_valid_content:
                try:
                    html_content = markdown.markdown(loaded_markdown, extensions=['fenced_code', 'tables', 'extra'])
                    self.rendered_output.setHtml(html_content); self.rendered_output.setPlaceholderText("Rendered.")
                except Exception as e_render: self.rendered_output.setPlainText(f"[Render Error: {e_render}]"); self.rendered_output.setPlaceholderText("Failed render.")
                self.copy_button.setEnabled(True)
            else:
                self.rendered_output.clear(); self.rendered_output.setPlaceholderText("Loaded file has error/no content."); self.copy_button.setEnabled(False)
            self.current_file_path = file_path; self.add_recent_file(file_path); self.update_title(); self.statusBar.showMessage(f"Loaded {os.path.basename(file_path)}", 3000)
        except FileNotFoundError: QMessageBox.critical(self, "Load Error", f"File not found:\n{file_path}"); self.remove_recent_file(file_path); self.statusBar.showMessage("Load failed: File not found.", 3000)
        except json.JSONDecodeError: QMessageBox.critical(self, "Load Error", f"Could not decode JSON file:\n{file_path}"); self.statusBar.showMessage("Load failed: Invalid JSON.", 3000)
        except ValueError as e: QMessageBox.critical(self, "Load Error", f"Invalid file format: {e}\n{file_path}"); self.statusBar.showMessage("Load failed: Invalid format.", 3000)
        except Exception as e: QMessageBox.critical(self, "Load Error", f"An unexpected error occurred during load:\n{e}"); self.statusBar.showMessage("Load failed.", 3000)

    # --- Recent Files Handling (No changes needed) ---
    def get_recent_files(self) -> list[str]: return self.settings.value(SETTINGS_RECENT_FILES, [], type=list)
    def set_recent_files(self, files: list[str]): self.settings.setValue(SETTINGS_RECENT_FILES, files)
    def add_recent_file(self, file_path: str):
        if not file_path: return; recent_files = self.get_recent_files();
        try: recent_files.remove(file_path)
        except ValueError: pass
        recent_files.insert(0, file_path); del recent_files[MAX_RECENT_FILES:]; self.set_recent_files(recent_files); self.update_recent_files_menu()
    def remove_recent_file(self, file_path: str):
        if not file_path: return; recent_files = self.get_recent_files();
        try: recent_files.remove(file_path); self.set_recent_files(recent_files); self.update_recent_files_menu()
        except ValueError: pass
    def update_recent_files_menu(self):
        self.recent_files_menu.clear(); recent_files = self.get_recent_files(); actions = []
        for i, file_path in enumerate(recent_files):
            if not file_path: continue
            action = QAction(f"&{i+1} {os.path.basename(file_path)}", self); action.setData(file_path); action.triggered.connect(self.open_recent_file); actions.append(action)
        if actions: self.recent_files_menu.addActions(actions); self.recent_files_menu.setEnabled(True)
        else: no_recent_action = QAction("(No Recent Files)", self); no_recent_action.setEnabled(False); self.recent_files_menu.addAction(no_recent_action); self.recent_files_menu.setEnabled(False)
    def open_recent_file(self):
        action = self.sender();
        if action and action.data():
            file_path = action.data()
            if os.path.exists(file_path): self.load_file(file_path)
            else: QMessageBox.warning(self, "File Not Found", f"File not found: {os.path.basename(file_path)}"); self.remove_recent_file(file_path)


    def closeEvent(self, event):
        self.save_window_state(); self.settings.sync(); event.accept()


# --- Main Execution ---
if __name__ == '__main__':
    app = QApplication(sys.argv)
    mainWin = DocScraperAppGUI()
    mainWin.show()
    sys.exit(app.exec_())