"""
ScrapeMaster: A versatile web scraping class that utilizes both requests and Selenium for fetching web content.
This class allows for scraping text and images from web pages, handling cookies, and managing user agents.
It supports both static and dynamic content loading, making it suitable for a variety of web scraping tasks.

Usage:
    scraper = ScrapeMaster('http://example.com')
    scraper.fetch_page()
    texts = scraper.scrape_text()
    images = scraper.scrape_images()
    scraper.download_images(images, 'output_directory')
"""

import requests
from bs4 import BeautifulSoup
import random
import pickle
import json
from urllib.parse import urljoin
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from .utils import clean_text
from pathlib import Path
from ascii_colors import ASCIIColors
class ScrapeMaster:
    def __init__(self, url):
        """
        Initializes the ScrapeMaster with the given URL.

        Args:
            url (str): The URL of the page to scrape.
        """
        self.url = url
        self.soup = None
        self.session = requests.Session()
        self.driver = None
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        ]
        self.default_text_selectors = ["h1","h2","h3","p", "pre", "code"]  # Added "code" to the selectors
        self.default_image_selectors = ["img"]

    def set_random_user_agent(self):
        """Sets a random User-Agent header for the session."""
        self.session.headers['User-Agent'] = random.choice(self.user_agents)

    def use_proxy(self, proxy):
        """Sets a proxy for the session.

        Args:
            proxy (str): The proxy URL.
        """
        self.session.proxies = {'http': proxy, 'https': proxy}

    def fetch_page(self):
        """Fetches the page content using requests and parses it with BeautifulSoup."""
        self.set_random_user_agent()
        response = self.session.get(self.url)
        response.raise_for_status()
        self.soup = BeautifulSoup(response.content, 'lxml')

    def fetch_page_with_js(self):
        """Fetches the page content using Selenium to handle JavaScript-rendered content."""
        if not self.driver:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            self.driver = webdriver.Chrome(options=chrome_options)
        
        self.driver.get(self.url)
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        self.soup = BeautifulSoup(self.driver.page_source, 'lxml')

    def save_cookies(self, filename='cookies.pkl'):
        """Saves the session cookies to a file.

        Args:
            filename (str): The filename to save cookies.
        """
        with open(filename, 'wb') as f:
            pickle.dump(self.session.cookies, f)

    def load_cookies(self, filename='cookies.pkl'):
        """Loads session cookies from a file.

        Args:
            filename (str): The filename to load cookies from.
        """
        with open(filename, 'rb') as f:
            self.session.cookies.update(pickle.load(f))

    def save_selenium_cookies(self, filename='selenium_cookies.json'):
        """Saves Selenium cookies to a JSON file.

        Args:
            filename (str): The filename to save Selenium cookies.
        """
        if self.driver:
            with open(filename, 'w') as f:
                json.dump(self.driver.get_cookies(), f)

    def load_selenium_cookies(self, filename='selenium_cookies.json'):
        """Loads Selenium cookies from a JSON file.

        Args:
            filename (str): The filename to load Selenium cookies from.
        """
        if self.driver:
            with open(filename, 'r') as f:
                cookies = json.load(f)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)

    def login(self, login_url, username, password, username_field='username', password_field='password'):
        """Logs into a website using the requests session.

        Args:
            login_url (str): The URL to the login page.
            username (str): The username for login.
            password (str): The password for login.
            username_field (str): The name of the username input field.
            password_field (str): The name of the password input field.
        """
        data = {
            username_field: username,
            password_field: password
        }
        response = self.session.post(login_url, data=data)
        response.raise_for_status()
        self.save_cookies()  # Save cookies after successful login

    def login_with_selenium(self, login_url, username, password, username_selector, password_selector, submit_selector):
        """Logs into a website using Selenium.

        Args:
            login_url (str): The URL to the login page.
            username (str): The username for login.
            password (str): The password for login.
            username_selector (str): The CSS selector for the username input field.
            password_selector (str): The CSS selector for the password input field.
            submit_selector (str): The CSS selector for the submit button.
        """
        if not self.driver:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            self.driver = webdriver.Chrome(options=chrome_options)

        self.driver.get(login_url)
        WebDriverWait(self.driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, username_selector))
        )
        
        self.driver.find_element(By.CSS_SELECTOR, username_selector).send_keys(username)
        self.driver.find_element(By.CSS_SELECTOR, password_selector).send_keys(password)
        self.driver.find_element(By.CSS_SELECTOR, submit_selector).click()
        
        WebDriverWait(self.driver, 10).until(
            EC.url_changes(login_url)
        )
        
        self.save_selenium_cookies()

    def scrape_text(self, selectors=None, use_selenium=False):
        """Scrapes text from the page using the provided selectors.

        Args:
            selectors (list): A list of CSS selectors to scrape text from.
            use_selenium (bool): Whether to use Selenium for scraping.

        Returns:
            list: A list of scraped text.
        """
        try:
            if use_selenium:
                self.fetch_page_with_js()
            elif not self.soup:
                    self.fetch_page()
        except:
            ASCIIColors.error(f"Couldn't load {self.url}")        
            return []
        selectors = selectors or self.default_text_selectors
        texts = []
        for selector in selectors:
            elements = self.soup.select(selector)
            for el in elements:
                # If the element is a <pre> tag, we need to find the <code> tag inside it
                if el.name == 'pre':
                    code_elements = el.find_all('span')
                    for code in code_elements:
                        # Extract text from <code> and clean it
                        texts.append(clean_text(code.get_text()))
                else:
                    texts.append(clean_text(el.get_text()))
        
        return texts

    def scrape_images(self, selectors=None, use_selenium=False):
        """Scrapes image URLs from the page using the provided selectors.

        Args:
            selectors (list): A list of CSS selectors to scrape images from.
            use_selenium (bool): Whether to use Selenium for scraping.

        Returns:
            list: A list of scraped image URLs.
        """
        if use_selenium:
            self.fetch_page_with_js()
        elif not self.soup:
            self.fetch_page()
        
        selectors = selectors or self.default_image_selectors
        image_urls = []
        for selector in selectors:
            img_elements = self.soup.select(selector)
            image_urls.extend([urljoin(self.url, img['src']) for img in img_elements if 'src' in img.attrs and isinstance(img['src'], str)])
        
        return image_urls

    def download_images(self, image_urls, output_dir):
        """Downloads images from the provided URLs to the specified directory.

        Args:
            image_urls (list): A list of image URLs to download.
            output_dir (str): The directory to save downloaded images.
        """
        images_dir = Path(output_dir) / 'images'
        images_dir.mkdir(parents=True, exist_ok=True)  # Ensure the images directory exists
        
        for i, url in enumerate(image_urls):
            response = self.session.get(url)
            response.raise_for_status()
            filename = f"image_{i}.jpg"
            image_folder = images_dir / f"page_{i}"
            image_folder.mkdir(parents=True, exist_ok=True)  # Ensure the page directory exists
            
            with open(image_folder / filename, 'wb') as f:
                f.write(response.content)

    def scrape_all(self, text_selectors=None, image_selectors=None, output_dir=None, use_selenium=False):
        """Scrapes both text and images from the page and optionally downloads images.

        Args:
            text_selectors (list): A list of CSS selectors for scraping text.
            image_selectors (list): A list of CSS selectors for scraping images.
            output_dir (str): The directory to save downloaded images.
            use_selenium (bool): Whether to use Selenium for scraping.

        Returns:
            dict: A dictionary containing scraped texts and image URLs.
        """
        texts = self.scrape_text(text_selectors, use_selenium)
        image_urls = self.scrape_images(image_selectors, use_selenium)
        
        if output_dir:
            self.download_images(image_urls, output_dir)
        
        return {
            'texts': texts,
            'image_urls': image_urls
        }

    def scrape_website(self, max_depth=2, output_dir='output', prefix='page_'):
        """Recursively scrapes a website by following links up to a specified depth.

        Args:
            max_depth (int): The maximum depth to follow links.
            output_dir (str): The directory to save scraped content.
            prefix (str): The prefix for output files.

        Returns:
            None
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        visited = set()
        
        def scrape_page(url, depth):
            if depth > max_depth or url in visited:
                return
            
            visited.add(url)
            self.url = url
            self.fetch_page()
            
            # Scrape text and images
            texts = self.scrape_text()
            image_urls = self.scrape_images()
            
            # Save text to file
            with open(output_path / f"{prefix}{len(visited)}.txt", 'w', encoding='utf-8') as f:
                f.write('\n'.join(texts))
            
            # Download images
            self.download_images(image_urls, output_path)
            
            # Find and follow links
            links = self.soup.find_all('a', href=True)
            for link in links:
                next_url = urljoin(url, link['href'])
                scrape_page(next_url, depth + 1)

        scrape_page(self.url, 0)

    def __del__(self):
        """Cleans up the Selenium driver on object deletion."""
        if self.driver:
            self.driver.quit()
