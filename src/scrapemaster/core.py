import requests
from bs4 import BeautifulSoup
import os
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

class ScrapeMaster:
    def __init__(self, url):
        self.url = url
        self.soup = None
        self.session = requests.Session()
        self.driver = None
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.1 Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        ]

    def set_random_user_agent(self):
        self.session.headers['User-Agent'] = random.choice(self.user_agents)

    def use_proxy(self, proxy):
        self.session.proxies = {'http': proxy, 'https': proxy}

    def fetch_page(self):
        self.set_random_user_agent()
        response = self.session.get(self.url)
        response.raise_for_status()
        self.soup = BeautifulSoup(response.content, 'lxml')

    def fetch_page_with_js(self):
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
        with open(filename, 'wb') as f:
            pickle.dump(self.session.cookies, f)

    def load_cookies(self, filename='cookies.pkl'):
        with open(filename, 'rb') as f:
            self.session.cookies.update(pickle.load(f))

    def save_selenium_cookies(self, filename='selenium_cookies.json'):
        if self.driver:
            with open(filename, 'w') as f:
                json.dump(self.driver.get_cookies(), f)

    def load_selenium_cookies(self, filename='selenium_cookies.json'):
        if self.driver:
            with open(filename, 'r') as f:
                cookies = json.load(f)
                for cookie in cookies:
                    self.driver.add_cookie(cookie)

    def login(self, login_url, username, password, username_field='username', password_field='password'):
        data = {
            username_field: username,
            password_field: password
        }
        response = self.session.post(login_url, data=data)
        response.raise_for_status()
        self.save_cookies()  # Save cookies after successful login

    def login_with_selenium(self, login_url, username, password, username_selector, password_selector, submit_selector):
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

    def scrape_text(self, selector, use_selenium=False):
        if use_selenium:
            self.fetch_page_with_js()
        elif not self.soup:
            self.fetch_page()
        elements = self.soup.select(selector)
        return [clean_text(el.get_text()) for el in elements]

    def scrape_images(self, selector, use_selenium=False):
        if use_selenium:
            self.fetch_page_with_js()
        elif not self.soup:
            self.fetch_page()
        img_elements = self.soup.select(selector)
        return [urljoin(self.url, img['src']) for img in img_elements if 'src' in img.attrs and isinstance(img['src'], str)]


    def download_images(self, image_urls, output_dir):
        os.makedirs(output_dir, exist_ok=True)
        for i, url in enumerate(image_urls):
            response = self.session.get(url)
            response.raise_for_status()
            filename = f"image_{i}.jpg"
            with open(os.path.join(output_dir, filename), 'wb') as f:
                f.write(response.content)

    def scrape_all(self, text_selector, image_selector, output_dir=None, use_selenium=False):
        texts = self.scrape_text(text_selector, use_selenium)
        image_urls = self.scrape_images(image_selector, use_selenium)
        
        if output_dir:
            self.download_images(image_urls, output_dir)
        
        return {
            'texts': texts,
            'image_urls': image_urls
        }

    def __del__(self):
        if self.driver:
            self.driver.quit()
