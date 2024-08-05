# -*- coding: utf-8 -*-
import itertools
import logging
import re
import time
import traceback
from datetime import datetime

import numpy as np
import pandas as pd
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

GM_WEBPAGE = 'https://www.google.com/maps/'
MAX_WAIT = 10
MAX_RETRY = 5
MAX_SCROLLS = 40


class GoogleMapsScraper:

    def __init__(self, debug=False):
        self.debug = debug
        self.driver = self._get_driver()
        self.logger = self._get_logger()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, tb):
        if exc_type:
            traceback.print_exception(exc_type, exc_value, tb)
        self.driver.close()
        self.driver.quit()
        return True

    def sort_by(self, url, ind):
        self.driver.get(url)
        self._click_on_cookie_agreement()
        wait = WebDriverWait(self.driver, MAX_WAIT)

        for _ in range(MAX_RETRY):
            try:
                menu_bt = wait.until(EC.element_to_be_clickable((By.XPATH, '//button[@data-value=\'Sort\']')))
                menu_bt.click()
                time.sleep(3)
                break
            except Exception as e:
                self.logger.warn('Failed to click sorting button')
        else:
            return -1

        recent_rating_bt = self.driver.find_elements(By.XPATH, '//div[@role=\'menuitemradio\']')[ind]
        recent_rating_bt.click()
        time.sleep(5)

        return 0

    def get_places(self, keyword_list=None):
        df_places = pd.DataFrame()
        search_point_url_list = self._gen_search_points_from_square(keyword_list)

        for i, search_point_url in enumerate(search_point_url_list):
            print(search_point_url)
            if (i + 1) % 10 == 0:
                print(f"{i}/{len(search_point_url_list)}")
                df_places = df_places[['search_point_url', 'href', 'name']]
                df_places.to_csv('output/places_wax.csv', index=False)

            try:
                self.driver.get(search_point_url)
            except NoSuchElementException:
                self.driver.quit()
                self.driver = self._get_driver()
                self.driver.get(search_point_url)

            scrollable_div = self.driver.find_element(
                By.CSS_SELECTOR, "div.m6QErb.DxyBCb.kA9KIf.dS8AEf.ecceSd > div[aria-label*='Results for']")
            for _ in range(10):
                self.driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', scrollable_div)

            time.sleep(2)
            response = BeautifulSoup(self.driver.page_source, 'html.parser')
            div_places = response.select('div[jsaction] > a[href]')

            for div_place in div_places:
                place_info = {
                    'search_point_url': search_point_url.replace('https://www.google.com/maps/search/', ''),
                    'href': div_place['href'],
                    'name': div_place['aria-label']
                }
                df_places = df_places.append(place_info, ignore_index=True)

        df_places = df_places[['search_point_url', 'href', 'name']]
        df_places.to_csv('output/places_wax.csv', index=False)

    def get_reviews(self, offset):
        self._scroll()
        time.sleep(4)
        self._expand_reviews()
        response = BeautifulSoup(self.driver.page_source, 'html.parser')
        rblock = response.find_all('div', class_='jftiEf fontBodyMedium')
        parsed_reviews = [self._parse(review) for index, review in enumerate(rblock) if index >= offset]
        for r in parsed_reviews:
            print(r)
        return parsed_reviews

    def get_account(self, url):
        self.driver.get(url)
        self._click_on_cookie_agreement()
        time.sleep(2)
        response = BeautifulSoup(self.driver.page_source, 'html.parser')
        return self._parse_place(response, url)

    def _parse(self, review):
        item = {}
        item['id_review'] = review.get('data-review-id')
        item['caption'] = self._filter_string(review.find('span', class_='wiI7pd').text) if review.find('span', class_='wiI7pd') else None
        item['relative_date'] = review.find('span', class_='rsqaWe').text if review.find('span', class_='rsqaWe') else None
        item['retrieval_date'] = datetime.now()
        item['rating'] = float(review.find('span', class_='kvMYJc')['aria-label'].split(' ')[0]) if review.find('span', class_='kvMYJc') else None
        item['username'] = review.get('aria-label')
        item['n_review_user'] = review.find('div', class_='RfnDt').text.split(' ')[3] if review.find('div', class_='RfnDt') else 0
        item['url_user'] = review.find('button', class_='WEBjve')['data-href'] if review.find('button', class_='WEBjve') else None
        return item

    def _parse_place(self, response, url):
        place = {}
        place['name'] = response.find('h1', class_='DUwDvf fontHeadlineLarge').text.strip() if response.find('h1', class_='DUwDvf fontHeadlineLarge') else None
        place['overall_rating'] = float(response.find('div', class_='F7nice ').find('span', class_='ceNzKf')['aria-label'].split(' ')[1]) if response.find('div', class_='F7nice ').find('span', class_='ceNzKf') else None
        place['n_reviews'] = int(response.find('div', class_='F7nice ').text.split('(')[1].replace(',', '').replace(')', '')) if response.find('div', class_='F7nice ') else 0
        place['n_photos'] = int(response.find('div', class_='YkuOqf').text.replace('.', '').replace(',', '').split(' ')[0]) if response.find('div', class_='YkuOqf') else 0
        place['category'] = response.find('button', jsaction='pane.rating.category').text.strip() if response.find('button', jsaction='pane.rating.category') else None
        place['description'] = response.find('div', class_='PYvSYb').text.strip() if response.find('div', class_='PYvSYb') else None
        b_list = response.find_all('div', class_='Io6YTe fontBodyMedium')
        place['address'] = b_list[0].text if b_list else None
        place['website'] = b_list[1].text if len(b_list) > 1 else None
        place['phone_number'] = b_list[2].text if len(b_list) > 2 else None
        place['plus_code'] = b_list[3].text if len(b_list) > 3 else None
        place['opening_hours'] = response.find('div', class_='t39EBf GUrTXd')['aria-label'].replace('\u202f', ' ') if response.find('div', class_='t39EBf GUrTXd') else None
        place['url'] = url
        lat, long, _ = url.split('/')[6].split(',')
        place['lat'] = lat[1:]
        place['long'] = long
        return place

    def _gen_search_points_from_square(self, keyword_list=None):
        keyword_list = keyword_list or []
        square_points = pd.read_csv('input/square_points.csv')
        cities = square_points['city'].unique()
        search_urls = [
            f"https://www.google.com/maps/search/{keyword}/@{lat},{long},15z"
            for city in cities
            for lat, long, keyword in itertools.product(
                square_points[square_points['city'] == city]['latitude'].unique(),
                square_points[square_points['city'] == city]['longitude'].unique(),
                keyword_list
            )
        ]
        return search_urls

    def _expand_reviews(self):
        buttons = self.driver.find_elements(By.CSS_SELECTOR, 'button.w8nwRe.kyuRq')
        for button in buttons:
            self.driver.execute_script("arguments[0].click();", button)

    def _scroll(self):
        scrollable_div = self.driver.find_element(By.CSS_SELECTOR, 'div.m6QErb.DxyBCb.kA9KIf.dS8AEf')
        self.driver.execute_script('arguments[0].scrollTop = arguments[0].scrollHeight', scrollable_div)

    def _get_logger(self):
        logger = logging.getLogger('googlemaps-scraper')
        logger.setLevel(logging.DEBUG)
        fh = logging.FileHandler('gm-scraper.log')
        fh.setLevel(logging.DEBUG)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        fh.setFormatter(formatter)
        logger.addHandler(fh)
        return logger

    def _get_driver(self):
        options = webdriver.ChromeOptions()
        if not self.debug:
            options.add_argument("--headless")
        else:
            options.add_argument("--window-size=1366,768")
        options.add_argument("--disable-notifications")
        options.add_argument("--accept-lang=en-GB")
        driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        driver.get(GM_WEBPAGE)
        return driver

    def _click_on_cookie_agreement(self):
        try:
            agree = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//span[contains(text(), "Reject all")]')))
            agree.click()
            return True
        except Exception as e:
            return False

    def _filter_string(self, s):
        return s.replace('\r', ' ').replace('\n', ' ').replace('\t', ' ')
