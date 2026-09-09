"""
ScrapeMaster GUI Module - PySide6/Qt6 Implementation
Licensed under LGPL-compatible terms (PySide6/Qt6).
"""
from __future__ import annotations
import sys
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from typing import Optional, List, Dict, Final, Any

# --- Auto-install GUI Dependencies via pipmaster ---
PYSIDE6_AVAILABLE: bool = False
try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLineEdit, QPushButton, QTextEdit, QLabel, QFileDialog,
        QMessageBox, QMenu, QStatusBar, QTabWidget, QDialog, QCheckBox,
        QDialogButtonBox, QGridLayout, QSpinBox, QTreeWidget, QTreeWidgetItem,
        QListWidget, QListWidgetItem, QRadioButton, QButtonGroup, QGroupBox,
        QSplitter, QComboBox, QProgressBar
    )
    from PySide6.QtCore import QSettings, Qt, QObject, QThread, Signal, QByteArray
    from PySide6.QtGui import QAction, QCloseEvent, QFont
    PYSIDE6_AVAILABLE = True
except ImportError:
    # Attempt auto-install via pipmaster
    try:
        import pipmaster as pm
        print("Installing GUI dependencies (PySide6, markdown)...")
        pm.ensure_packages(["PySide6", "markdown"], verbose=True)
        from PySide6.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QLineEdit, QPushButton, QTextEdit, QLabel, QFileDialog,
            QMessageBox, QMenu, QStatusBar, QTabWidget, QDialog, QCheckBox,
            QDialogButtonBox, QGridLayout, QSpinBox, QTreeWidget, QTreeWidgetItem,
            QListWidget, QListWidgetItem, QRadioButton, QButtonGroup, QGroupBox,
            QSplitter, QComboBox, QProgressBar
        )
        from PySide6.QtCore import QSettings, Qt, QObject, QThread, Signal, QByteArray
        from PySide6.QtGui import QAction, QCloseEvent, QFont
        PYSIDE6_AVAILABLE = True
    except Exception as e:
        print(f"Failed to install GUI dependencies: {e}")
        PYSIDE6_AVAILABLE = False
        # Dummy types for type checking when GUI not available
        from typing import Any
        QObject = Any
        QSettings = Any
        QWidget = Any
        QMainWindow = Any

# --- Library Imports ---
from .core import ScrapeMaster, SUPPORTED_STRATEGIES, DEFAULT_STRATEGY_ORDER
from .exceptions import ScrapeMasterError
from .utils import is_valid_url, sanitize_filename

# Constants
APP_NAME: Final = "ScrapeMaster GUI"
ORG_NAME: Final = "ScrapeMaster"
SETTINGS_STRATEGY_PREFIX: Final = "settings/strategyEnabled_"
SETTINGS_HEADLESS: Final = "settings/headlessMode"
SETTINGS_CRAWL_DEPTH: Final = "settings/crawlDepth"

if PYSIDE6_AVAILABLE:
    
    class ScrapeWorker(QObject):
        """Enhanced worker supporting all content types."""
        progress = Signal(str)
        finished = Signal(dict, str, str)  # results, markdown, error_msg
        error_occurred = Signal(str)
        media_found = Signal(dict)  # media links
        structured_data_found = Signal(dict)  # json-ld, opengraph

        def __init__(self, url: str, strategies: List[str], headless: bool, 
                     depth: int, content_type: str = 'auto'):
            super().__init__()
            self.url = url
            self.strategies = strategies
            self.headless = headless
            self.depth = depth
            self.content_type = content_type  # 'auto', 'article', 'video', 'podcast', 'social'
            self._is_running = True
            self._scraper: Optional[ScrapeMaster] = None

        def cancel(self):
            self._is_running = False
            if self._scraper:
                try:
                    self._scraper._quit_driver()
                except Exception:
                    pass

        def run(self):
            if not self._is_running:
                return
            
            try:
                self._scraper = ScrapeMaster(
                    self.url, 
                    strategy=self.strategies, 
                    headless=self.headless
                )
                
                self.progress.emit(f"Fetching {self.url}...")
                
                # Fetch content first
                if not self._scraper._fetch_content(self._scraper.strategy):
                    error = self._scraper.get_last_error() or "Fetch failed"
                    self.error_occurred.emit(error)
                    return

                results = {"type": self.content_type, "url": self.url}
                markdown = ""

                # Handle based on selected content type
                if self.content_type == 'video' or (
                    self.content_type == 'auto' and (
                        'youtube.com' in self.url or 
                        'youtu.be' in self.url or 
                        'vimeo.com' in self.url or
                        'twitch.tv' in self.url
                    )
                ):
                    self.progress.emit("Extracting video content...")
                    video_data = self._scraper.scrape_video(self.url, extract_type='auto')
                    if video_data:
                        results['video'] = video_data
                        if video_data.get('transcript'):
                            markdown = f"# Video Transcript\n\n{video_data['transcript']}\n\n"
                            markdown += f"## Metadata\n\n```json\n{json.dumps(video_data.get('metadata', {}), indent=2)}\n```"
                        else:
                            markdown = self._scraper.scrape_markdown() or ""
                    
                elif self.content_type == 'podcast' or (
                    self.content_type == 'auto' and self._is_podcast_url(self.url)
                ):
                    self.progress.emit("Extracting podcast feed...")
                    feed = self._scraper.scrape_podcast_feed()
                    if feed:
                        results['podcast'] = feed
                        markdown = f"# {feed['title']}\n\n"
                        markdown += f"**Author:** {feed.get('author', 'Unknown')}\n\n"
                        markdown += "## Episodes\n\n"
                        for ep in feed['episodes'][:10]:  # Last 10
                            markdown += f"### {ep['title']}\n"
                            markdown += f"- **Date:** {ep.get('date', 'Unknown')}\n"
                            if ep.get('duration'):
                                markdown += f"- **Duration:** {ep['duration']}\n"
                            if ep.get('audio_url'):
                                markdown += f"- [Audio]({ep['audio_url']})\n"
                            markdown += "\n"
                    
                elif self.content_type == 'social' or (
                    self.content_type == 'auto' and (
                        'twitter.com' in self.url or 
                        'x.com' in self.url or
                        'linkedin.com' in self.url
                    )
                ):
                    self.progress.emit("Extracting social post...")
                    post = self._scraper.scrape_social_post()
                    if post:
                        results['social'] = post
                        markdown = f"# Social Post\n\n"
                        markdown += f"**Platform:** {post['platform'].title()}\n"
                        if post.get('author'):
                            markdown += f"**Author:** {post['author']}\n"
                        markdown += f"\n{post['text']}\n\n"
                        if post.get('quoted_content'):
                            markdown += f"**Quoted:** {post['quoted_content'].get('text', '')}\n"
                        if post.get('metrics'):
                            markdown += f"\n**Metrics:** {post['metrics']}\n"
                    else:
                        markdown = self._scraper.scrape_markdown() or ""
                
                elif self.content_type == 'article':
                    self.progress.emit("Extracting article content...")
                    article = self._scraper.scrape_article(extract_comments=True)
                    if article:
                        results['article'] = article
                        markdown = article.get('content_md', '')
                        # Prepend metadata
                        meta_header = f"# {article.get('title', 'Article')}\n\n"
                        if article.get('author'):
                            meta_header += f"**Author:** {article['author']}\n\n"
                        if article.get('published_date'):
                            meta_header += f"**Published:** {article['published_date']}\n\n"
                        if article.get('reading_time_min'):
                            meta_header += f"**Reading Time:** {article['reading_time_min']} min\n\n"
                        markdown = meta_header + markdown
                    else:
                        markdown = self._scraper.scrape_markdown() or ""
                
                else:
                    # Generic scrape
                    self.progress.emit("Extracting generic content...")
                    crawl_results = self._scraper.scrape_all(
                        max_depth=self.depth,
                        convert_to_markdown=True
                    )
                    if crawl_results:
                        markdown = crawl_results.get('markdown', '')
                        results.update(crawl_results)

                # Extract media if requested
                if self._is_running:
                    self.progress.emit("Extracting media links...")
                    media = self._scraper.scrape_media_links()
                    if any(media.values()):
                        results['media'] = media
                        self.media_found.emit(media)

                # Extract structured data
                if self._is_running:
                    self.progress.emit("Extracting structured data...")
                    structured = self._scraper.scrape_structured_data()
                    if structured:
                        results['structured_data'] = structured
                        self.structured_data_found.emit(structured)

                if not self._is_running:
                    return

                last_error = self._scraper.get_last_error() or ""
                self.finished.emit(results, markdown, last_error)
                    
            except Exception as e:
                self.error_occurred.emit(str(e))
            finally:
                if self._scraper:
                    try:
                        self._scraper._quit_driver()
                    except Exception:
                        pass

        def _is_podcast_url(self, url: str) -> bool:
            """Check if URL looks like a podcast RSS feed."""
            indicators = ['feed', 'rss', 'podcast', '.xml', 'itunes']
            return any(ind in url.lower() for ind in indicators)

    class SettingsDialog(QDialog):
        """Enhanced settings with content-type specific options."""
        settingsChanged = Signal()

        def __init__(self, settings: QSettings, parent: Optional[QWidget] = None):
            super().__init__(parent)
            self.settings = settings
            self.setWindowTitle("ScrapeMaster Settings")
            self.setMinimumWidth(450)
            self._init_ui()
            self._load_settings()

        def _init_ui(self):
            layout = QVBoxLayout(self)
            
            # Strategies group
            strat_group = QGroupBox("Scraping Strategies (fallback order)")
            grid = QGridLayout()
            
            self.strategy_checkboxes: Dict[str, QCheckBox] = {}
            row = 0
            for strategy in DEFAULT_STRATEGY_ORDER:
                if strategy not in SUPPORTED_STRATEGIES:
                    continue
                cb = QCheckBox(strategy.replace('_', ' ').title())
                grid.addWidget(cb, row, 0)
                self.strategy_checkboxes[strategy] = cb
                row += 1
            strat_group.setLayout(grid)
            layout.addWidget(strat_group)
            
            # Browser options
            browser_group = QGroupBox("Browser Options")
            browser_layout = QVBoxLayout()
            
            self.headless_cb = QCheckBox("Run browser headless (invisible)")
            browser_layout.addWidget(self.headless_cb)
            browser_group.setLayout(browser_layout)
            layout.addWidget(browser_group)
            
            # Crawl options
            crawl_group = QGroupBox("Crawling")
            crawl_layout = QGridLayout()
            
            crawl_layout.addWidget(QLabel("Max Depth:"), 0, 0)
            self.depth_spin = QSpinBox()
            self.depth_spin.setRange(0, 10)
            self.depth_spin.setToolTip("0 = Single page only\n>0 = Follow links recursively")
            crawl_layout.addWidget(self.depth_spin, 0, 1)
            
            crawl_group.setLayout(crawl_layout)
            layout.addWidget(crawl_group)
            
            # Buttons
            buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
            buttons.accepted.connect(self._save_settings)
            buttons.rejected.connect(self.reject)
            layout.addWidget(buttons)

        def _load_settings(self):
            for strategy, cb in self.strategy_checkboxes.items():
                key = f"{SETTINGS_STRATEGY_PREFIX}{strategy}"
                cb.setChecked(self.settings.value(key, True, type=bool))
            
            self.headless_cb.setChecked(self.settings.value(SETTINGS_HEADLESS, True, type=bool))
            self.depth_spin.setValue(self.settings.value(SETTINGS_CRAWL_DEPTH, 0, type=int))

        def _save_settings(self):
            active = [s for s, cb in self.strategy_checkboxes.items() if cb.isChecked()]
            if not active:
                QMessageBox.warning(self, "Invalid", "Select at least one strategy.")
                return
            
            for strategy, cb in self.strategy_checkboxes.items():
                self.settings.setValue(f"{SETTINGS_STRATEGY_PREFIX}{strategy}", cb.isChecked())
            
            self.settings.setValue(SETTINGS_HEADLESS, self.headless_cb.isChecked())
            self.settings.setValue(SETTINGS_CRAWL_DEPTH, self.depth_spin.value())
            self.settingsChanged.emit()
            self.accept()

    class ScrapeMasterApp(QMainWindow):
        """Main GUI Application with enhanced content type support."""
        
        def __init__(self):
            super().__init__()
            self.settings = QSettings(ORG_NAME, APP_NAME)
            self.current_file: Optional[Path] = None
            self.worker_thread: Optional[QThread] = None
            self.worker: Optional[ScrapeWorker] = None
            self.current_results: Optional[Dict[str, Any]] = None
            self._init_ui()
            self._load_state()

        def _init_ui(self):
            self.setWindowTitle(APP_NAME)
            self.resize(1200, 800)
            
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            
            # URL Input Section
            url_layout = QHBoxLayout()
            url_layout.addWidget(QLabel("URL:"))
            self.url_input = QLineEdit()
            self.url_input.setPlaceholderText("https://example.com/article or https://youtube.com/watch?v=...")
            self.url_input.setClearButtonEnabled(True)
            url_layout.addWidget(self.url_input)
            
            # Content Type Selector
            self.type_group = QButtonGroup()
            self.type_layout = QHBoxLayout()
            self.type_layout.addWidget(QLabel("Type:"))
            
            types = [
                ('auto', 'Auto-detect'),
                ('article', 'Article'),
                ('video', 'Video'),
                ('podcast', 'Podcast'),
                ('social', 'Social Media'),
                ('generic', 'Generic')
            ]
            
            for key, label in types:
                rb = QRadioButton(label)
                rb.setProperty('type', key)
                if key == 'auto':
                    rb.setChecked(True)
                self.type_group.addButton(rb)
                self.type_layout.addWidget(rb)
            
            url_layout.addLayout(self.type_layout)
            layout.addLayout(url_layout)
            
            # Action Buttons
            btn_layout = QHBoxLayout()
            
            self.scrape_btn = QPushButton("Scrape")
            self.scrape_btn.setStyleSheet("QPushButton { font-weight: bold; padding: 6px; }")
            self.scrape_btn.clicked.connect(self.start_scrape)
            btn_layout.addWidget(self.scrape_btn)
            
            self.cancel_btn = QPushButton("Cancel")
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.clicked.connect(self.cancel_scrape)
            btn_layout.addWidget(self.cancel_btn)
            
            btn_layout.addStretch()
            
            # Quick export buttons
            self.export_obsidian_btn = QPushButton("Export to Obsidian")
            self.export_obsidian_btn.setEnabled(False)
            self.export_obsidian_btn.clicked.connect(self.export_to_obsidian)
            btn_layout.addWidget(self.export_obsidian_btn)
            
            self.export_notion_btn = QPushButton("Export to Notion")
            self.export_notion_btn.setEnabled(False)
            self.export_notion_btn.clicked.connect(self.export_to_notion)
            btn_layout.addWidget(self.export_notion_btn)
            
            layout.addLayout(btn_layout)
            
            # Progress bar
            self.progress = QProgressBar()
            self.progress.setVisible(False)
            self.progress.setRange(0, 0)  # Indeterminate
            layout.addWidget(self.progress)
            
            # Main content splitter
            splitter = QSplitter(Qt.Vertical)
            
            # Tabs for different views
            self.tabs = QTabWidget()
            
            # Markdown view
            self.raw_output = QTextEdit()
            self.raw_output.setPlaceholderText("Scraped content will appear here...")
            self.raw_output.setAcceptRichText(False)
            self.tabs.addTab(self.raw_output, "Markdown")
            
            # Rendered view
            self.rendered_output = QTextEdit()
            self.rendered_output.setReadOnly(True)
            self.tabs.addTab(self.rendered_output, "Rendered Preview")
            
            # Media view (list of found images/videos/audio)
            self.media_list = QListWidget()
            self.media_list.setWordWrap(True)
            self.tabs.addTab(self.media_list, "Media Links")
            
            # Structured Data tree
            self.structured_tree = QTreeWidget()
            self.structured_tree.setHeaderLabels(["Key", "Value"])
            self.tabs.addTab(self.structured_tree, "Structured Data")
            
            # Metadata info
            self.metadata_text = QTextEdit()
            self.metadata_text.setReadOnly(True)
            self.metadata_text.setMaximumHeight(150)
            self.metadata_text.setPlaceholderText("Article/Video metadata will appear here...")
            
            splitter.addWidget(self.tabs)
            
            # Metadata panel below
            meta_group = QGroupBox("Extracted Metadata")
            meta_layout = QVBoxLayout()
            meta_layout.addWidget(self.metadata_text)
            meta_group.setLayout(meta_layout)
            splitter.addWidget(meta_group)

            layout.addWidget(splitter)

            # Menus
            self._create_menus()

            # Status bar
            self.status_bar = QStatusBar()
            self.setStatusBar(self.status_bar)
            self.status_bar.showMessage("Ready")

            self.tabs.setCurrentIndex(0)

            # Ensure we track the last content type for status display
            self._last_content_type = 'auto'

        def _create_menus(self):
            menubar = self.menuBar()
            
            # File
            file_menu = menubar.addMenu("&File")
            
            load_action = QAction("&Load JSON...", self)
            load_action.setShortcut("Ctrl+O")
            load_action.triggered.connect(self.load_file)
            file_menu.addAction(load_action)
            
            save_action = QAction("&Save Results As JSON...", self)
            save_action.setShortcut("Ctrl+S")
            save_action.triggered.connect(self.save_file)
            file_menu.addAction(save_action)
            
            export_md_action = QAction("&Export Markdown (.md)...", self)
            export_md_action.triggered.connect(self.export_markdown)
            file_menu.addAction(export_md_action)
            
            file_menu.addSeparator()
            
            exit_action = QAction("E&xit", self)
            exit_action.setShortcut("Ctrl+Q")
            exit_action.triggered.connect(self.close)
            file_menu.addAction(exit_action)
            
            # Options
            opts_menu = menubar.addMenu("&Options")
            settings_action = QAction("&Settings...", self)
            settings_action.triggered.connect(self.show_settings)
            opts_menu.addAction(settings_action)
            
            # Tools
            tools_menu = menubar.addMenu("&Tools")
            screenshot_action = QAction("Capture &Screenshot...", self)
            screenshot_action.triggered.connect(self.capture_screenshot)
            tools_menu.addAction(screenshot_action)

        def show_settings(self):
            dialog = SettingsDialog(self.settings, self)
            dialog.exec()

        def get_active_strategies(self) -> List[str]:
            strategies = []
            for s in DEFAULT_STRATEGY_ORDER:
                if s not in SUPPORTED_STRATEGIES:
                    continue
                key = f"{SETTINGS_STRATEGY_PREFIX}{s}"
                if self.settings.value(key, True, type=bool):
                    strategies.append(s)
            return strategies or ['requests']

        def get_selected_type(self) -> str:
            btn = self.type_group.checkedButton()
            return btn.property('type') if btn else 'auto'

        def start_scrape(self):
            url = self.url_input.text().strip()
            if not url:
                QMessageBox.warning(self, "Error", "Enter a URL")
                return

            if not url.startswith(('http://', 'https://')):
                url = f"https://{url}"
                self.url_input.setText(url)

            if not is_valid_url(url):
                QMessageBox.warning(self, "Error", "Invalid URL format")
                return

            if self.worker_thread and self.worker_thread.isRunning():
                QMessageBox.warning(self, "Busy", "Scrape already in progress")
                return

            strategies = self.get_active_strategies()
            headless = self.settings.value(SETTINGS_HEADLESS, True, type=bool)
            depth = self.settings.value(SETTINGS_CRAWL_DEPTH, 0, type=int)
            content_type = self.get_selected_type()
            self._last_content_type = content_type  # Store for use in on_scrape_finished

            self.worker_thread = QThread()
            self.worker = ScrapeWorker(url, strategies, headless, depth, content_type)
            self.worker.moveToThread(self.worker_thread)
            
            # Connect
            self.worker_thread.started.connect(self.worker.run)
            self.worker.progress.connect(self.status_bar.showMessage)
            self.worker.finished.connect(self.on_scrape_finished)
            self.worker.error_occurred.connect(self.on_scrape_error)
            self.worker.media_found.connect(self.on_media_found)
            self.worker.structured_data_found.connect(self.on_structured_data_found)
            self.worker.finished.connect(self.worker_thread.quit)
            self.worker.error_occurred.connect(self.worker_thread.quit)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            
            self.scrape_btn.setEnabled(False)
            self.cancel_btn.setEnabled(True)
            self.progress.setVisible(True)
            self.raw_output.clear()
            self.rendered_output.clear()
            self.media_list.clear()
            self.structured_tree.clear()
            self.metadata_text.clear()
            self.export_obsidian_btn.setEnabled(False)
            self.export_notion_btn.setEnabled(False)
            
            self.worker_thread.start()

        def cancel_scrape(self):
            if self.worker:
                self.worker.cancel()
                self.status_bar.showMessage("Cancelling...")

        def on_media_found(self, media: dict):
            """Display found media links."""
            self.media_list.clear()
            
            if media.get('images'):
                item = QListWidgetItem("🖼️ Images:")
                item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.media_list.addItem(item)
                for img in media['images'][:10]:  # Limit display
                    self.media_list.addItem(f"  {img}")
            
            if media.get('videos'):
                item = QListWidgetItem("🎬 Videos:")
                item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.media_list.addItem(item)
                for vid in media['videos']:
                    self.media_list.addItem(f"  {vid}")
            
            if media.get('audios'):
                item = QListWidgetItem("🎵 Audio:")
                item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.media_list.addItem(item)
                for aud in media['audios']:
                    self.media_list.addItem(f"  {aud}")
            
            if media.get('embeds'):
                item = QListWidgetItem("📺 Embeds:")
                item.setFont(QFont("Segoe UI", 10, QFont.Bold))
                self.media_list.addItem(item)
                for emb in media['embeds']:
                    self.media_list.addItem(f"  [{emb['type']}] {emb['url']}")

        def on_structured_data_found(self, data: dict):
            """Display structured data in tree."""
            self.structured_tree.clear()
            
            def add_items(parent, data_dict):
                for key, value in data_dict.items():
                    if isinstance(value, dict):
                        item = QTreeWidgetItem([str(key), ""])
                        parent.addChild(item)
                        add_items(item, value)
                    elif isinstance(value, list):
                        item = QTreeWidgetItem([str(key), f"List ({len(value)} items)"])
                        parent.addChild(item)
                        for i, v in enumerate(value[:5]):  # Limit display
                            child = QTreeWidgetItem([f"[{i}]", str(v)[:100]])
                            item.addChild(child)
                    else:
                        item = QTreeWidgetItem([str(key), str(value)[:200]])
                        parent.addChild(item)
            
            for data_type, content in data.items():
                if content and isinstance(content, (dict, list)):
                    root = QTreeWidgetItem([data_type, ""])
                    self.structured_tree.addTopLevelItem(root)
                    if isinstance(content, dict):
                        add_items(root, content)
                    elif isinstance(content, list) and content:
                         add_items(root, {"items": content})
            
            self.structured_tree.expandAll()

        def on_scrape_finished(self, results: dict, markdown: str, error: str):
            self.scrape_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress.setVisible(False)
            self.current_results = results

            # Get content type from results (stored in worker) or use current selection
            content_type = results.get('type', self._last_content_type)

            # Check for partial success (markdown without error but with error content)
            # This catches cases like YouTube consent pages that return "markdown" but not real content
            if error and not markdown:
                self.raw_output.setPlainText(f"Error: {error}")
                self.status_bar.showMessage(f"Failed: {error[:50]}...", 5000)
                return

            if markdown:
                # Validate markdown isn't just an error message or empty
                if len(markdown.strip()) < 50 and "Error" in markdown:
                    self.raw_output.setPlainText(f"Failed: {markdown}")
                    self.status_bar.showMessage("Scrape returned error content", 5000)
                    return

                self.raw_output.setPlainText(markdown)
                self.try_render_markdown(markdown)
                self.export_obsidian_btn.setEnabled(True)
                self.export_notion_btn.setEnabled(True)

                # Show metadata if available
                meta_lines = []
                if 'article' in results:
                    art = results['article']
                    if art.get('title'): meta_lines.append(f"📰 Title: {art['title']}")
                    if art.get('author'): meta_lines.append(f"✍️ Author: {art['author']}")
                    if art.get('reading_time_min'): meta_lines.append(f"⏱️ Read time: {art['reading_time_min']} min")

                if 'video' in results:
                    vid = results['video']
                    if vid.get('metadata', {}).get('title'): 
                        meta_lines.append(f"🎬 Video: {vid['metadata']['title']}")

                if 'podcast' in results:
                    pod = results.get('podcast', {})
                    if pod.get('title'):
                        meta_lines.append(f"🎙️ Podcast: {pod['title']} ({len(pod.get('episodes', []))} episodes)")

                if meta_lines:
                    self.metadata_text.setPlainText("\n".join(meta_lines))
                else:
                    self.metadata_text.setPlainText("No specific metadata extracted.")

                visited = len(results.get('visited_urls', []))
                msg = f"Success: {content_type} scraped"
                if visited > 1:
                    msg += f" ({visited} pages)"
                self.status_bar.showMessage(msg, 5000)
            else:
                self.raw_output.setPlainText(f"Failed: {error}")
                self.status_bar.showMessage(f"Error: {error}", 5000)

        def on_scrape_error(self, error: str):
            self.scrape_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.progress.setVisible(False)
            self.raw_output.setPlainText(f"Critical Error:\n{error}")
            self.status_bar.showMessage("Scrape failed", 5000)

        def try_render_markdown(self, md_text: str):
            try:
                import markdown
                html = markdown.markdown(
                    md_text, 
                    extensions=['fenced_code', 'tables', 'extra', 'codehilite'],
                    output_format='html5'
                )
                self.rendered_output.setHtml(html)
            except ImportError:
                self.rendered_output.setPlainText("Install 'markdown' for preview: pip install markdown")
            except Exception as e:
                self.rendered_output.setPlainText(f"Render error: {e}")

        def capture_screenshot(self):
            if not self.worker or not self.worker._scraper:
                QMessageBox.warning(self, "Error", "No active scraper session")
                return
            
            filename, _ = QFileDialog.getSaveFileName(
                self, "Save Screenshot", "screenshot.png", "PNG (*.png)"
            )
            if filename:
                result = self.worker._scraper.save_screenshot(filename, full_page=True)
                if result:
                    QMessageBox.information(self, "Success", f"Screenshot saved to {result}")

        def export_to_obsidian(self):
            if not self.current_results:
                return
            
            vault_path = QFileDialog.getExistingDirectory(
                self, "Select Obsidian Vault Location"
            )
            if not vault_path:
                return
            
            # Generate filename
            url = self.url_input.text()
            parsed = urlparse(url)
            base = parsed.path.split('/')[-1] or 'index'
            filename = sanitize_filename(f"{base}_{int(time.time())}.md")
            
            content = self.raw_output.toPlainText()
            if not content:
                QMessageBox.warning(self, "Error", "No content to export")
                return
                
            # Add frontmatter
            frontmatter = f"""---
url: {url}
scraped: {time.strftime('%Y-%m-%d %H:%M:%S')}
type: {self.current_results.get('type', 'generic')}
tags: [scrapemaster]
---
"""
            filepath = Path(vault_path) / filename
            
            try:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(frontmatter + "\n" + content)
                QMessageBox.information(self, "Success", f"Exported to {filepath}")
            except Exception as e:
                QMessageBox.critical(self, "Export Failed", str(e))

        def export_to_notion(self):
            # Simplified - just show dialog for token
            token, ok = QFileDialog.getText("Notion Setup",
                "Enter Notion Integration Token:",
                "secret_...")
            if not ok or not token.startswith('secret_'):
                QMessageBox.warning(self, "Error", "Invalid token format")
                return
                
            db_id, ok = QFileDialog.getText("Notion Setup", "Database ID:", "")
            if not ok or not db_id:
                return
            
            content = self.raw_output.toPlainText()
            url = self.url_input.text()
            
            # This would need actual Notion API implementation
            QMessageBox.information(self, "Info", 
                "Notion export requires additional API setup.\n"
                "Use the export_to_notion() method in your code directly for automation.")

        def save_file(self):
            if not self.current_results:
                QMessageBox.warning(self, "Error", "No results to save")
                return
                
            url = self.url_input.text()
            safe_name = sanitize_filename(f"{urlparse(url).netloc}_results.json")
            path, _ = QFileDialog.getSaveFileName(
                self, "Save JSON", safe_name, "JSON (*.json)"
            )
            
            if path:
                try:
                    # Merge current results with UI state
                    data = self.current_results.copy()
                    data['markdown'] = self.raw_output.toPlainText()
                    data['url'] = url
                    data['timestamp'] = time.time()
                    
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False)
                    self.status_bar.showMessage(f"Saved {Path(path).name}", 3000)
                except Exception as e:
                    QMessageBox.critical(self, "Error", str(e))

        def export_markdown(self):
            content = self.raw_output.toPlainText()
            if not content:
                QMessageBox.warning(self, "Error", "No content to export")
                return
                
            path, _ = QFileDialog.getSaveFileName(
                self, "Export Markdown", "scraped.md", "Markdown (*.md)"
            )
            
            if path:
                try:
                    if not path.lower().endswith('.md'):
                        path += '.md'
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    self.status_bar.showMessage(f"Exported {Path(path).name}", 3000)
                except Exception as e:
                    QMessageBox.critical(self, "Error", str(e))

        def load_file(self):
            path, _ = QFileDialog.getOpenFileName(self, "Load JSON", "", "JSON (*.json)")
            if not path:
                return
            
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if 'url' not in data:
                    raise ValueError("Invalid format")
                
                self.url_input.setText(data.get('url', ''))
                content = data.get('markdown', '')
                self.raw_output.setPlainText(content)
                self.try_render_markdown(content)
                
                # Display rich metadata if present
                if 'article' in data:
                    art = data['article']
                    meta = f"📰 {art.get('title', 'Unknown')}\n"
                    if art.get('author'): meta += f"By: {art['author']}\n"
                    self.metadata_text.setPlainText(meta)
                
                self.status_bar.showMessage(f"Loaded {Path(path).name}", 3000)
                
            except Exception as e:
                QMessageBox.critical(self, "Load Error", str(e))

        def _load_state(self):
            geo = self.settings.value("window/geometry")
            if geo:
                self.restoreGeometry(geo)
            state = self.settings.value("window/state")
            if state:
                self.restoreState(state)

        def closeEvent(self, event: QCloseEvent):
            # Safely cleanup - check existence before accessing to avoid RuntimeError
            if self.worker_thread is not None:
                try:
                    if self.worker_thread.isRunning():
                        if self.worker is not None:
                            try:
                                self.worker.cancel()
                            except RuntimeError:
                                pass  # Worker already deleted
                        self.worker_thread.quit()
                        if not self.worker_thread.wait(3000):
                            self.worker_thread.terminate()
                            self.worker_thread.wait()
                except RuntimeError:
                    # Thread C++ object already deleted
                    pass
                except Exception:
                    pass
            
            # Save state
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("window/state", self.saveState())
            self.settings.sync()
            
            event.accept()

    def main():
        """Entry point for GUI."""
        if not PYSIDE6_AVAILABLE:
            print("GUI requires PySide6. Install with: pip install PySide6 markdown")
            sys.exit(1)
        
        app = QApplication(sys.argv)
        app.setOrganizationName(ORG_NAME)
        app.setApplicationName(APP_NAME)
        
        window = ScrapeMasterApp()
        window.show()
        
        sys.exit(app.exec())

else:
    # Stubs for when GUI is not available
    class ScrapeWorker:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("PySide6 not available")
    
    class SettingsDialog:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("PySide6 not available")
    
    class ScrapeMasterApp:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("PySide6 not available")
    
    def main():
        print("Error: PySide6 required. pip install PySide6 markdown")
        sys.exit(1)