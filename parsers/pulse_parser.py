"""
Parser for tbank.ru pulse reviews
"""
import re
from typing import List, Dict
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from .base_parser import BaseParser


class PulseParser(BaseParser):
    """Parser for tbank.ru pulse"""
    
    BASE_URL = "https://www.tbank.ru/invest/stocks"
    MONTHS_RU = {
        "января": 1,
        "февраля": 2,
        "марта": 3,
        "апреля": 4,
        "мая": 5,
        "июня": 6,
        "июля": 7,
        "августа": 8,
        "сентября": 9,
        "октября": 10,
        "ноября": 11,
        "декабря": 12,
    }

    def parse_date(self, date_str: str):
        date_str = date_str.strip()
        now = datetime.now()

        if date_str.startswith("Сегодня"):
            time_part = re.search(r"(\d{1,2}:\d{2})", date_str).group(1)
            dt = datetime.combine(now.date(), datetime.strptime(time_part, "%H:%M").time())
        elif date_str.startswith("Вчера"):
            time_part = re.search(r"(\d{1,2}:\d{2})", date_str).group(1)
            yesterday = now.date() - timedelta(days=1)
            dt = datetime.combine(yesterday, datetime.strptime(time_part, "%H:%M").time())
        else:
            m = re.match(r"(\d{1,2}) (\w+) (\d{4}) в (\d{1,2}:\d{2})", date_str)
            if not m:
                return None
            day, month_str, year, time_part = m.groups()
            month = self.MONTHS_RU[month_str.lower()]
            dt = datetime.strptime(f"{day}-{month}-{year} {time_part}", "%d-%m-%Y %H:%M")

        return dt.strftime("%Y-%m-%d %H:%M")

    def get_date(self, time_elem):
        for elem in time_elem:
            date = self.parse_date(elem.get_text(strip=True))
            if date:
                return date
        return None

    async def parse_reviews(self, secid: str, start_date=None) -> List[Dict]:
        """Parse reviews from tbank.ru pulse"""
        reviews = []
        duplicate_comments = []
        secid_upper = secid.upper()
        url = f"{self.BASE_URL}/{secid_upper}/pulse/"

        html = await self.fetch_html(url)
        if not html:
            return reviews
        
        try:
            soup = BeautifulSoup(html, 'lxml')
            comments = soup.find_all(attrs={'data-qa-file': 'TextLineCollapse'})
            for comment in comments:
                text = self.clean_text(comment.get_text(strip=True))
                if not text or len(text) < 10:
                    continue

                parent = comment.find_parent(attrs={'data-qa-file': 'PulsePost'})
                time_elem = parent.find_all('div', attrs={'data-qa-file': 'PulsePostAuthor'})
                date_str = self.get_date(time_elem)
                date_str = date_str if date_str else datetime.now().strftime('%Y-%m-%d %H:%M')
                if start_date is not None and date_str.date() <= start_date:
                    return []

                if self.USE_IMAGE:
                    img_elem = parent.find('img', attrs={'data-qa-file': 'ImageTiles'})
                    img_url = img_elem.get('src') if img_elem else None
                    img_filepath = await self.download_file(img_url) if img_url else None
                else:
                    img_filepath = None

                # Filter by current week
                if text not in duplicate_comments:
                    reviews.append({
                        'text': text,
                        'date': date_str,
                        'img': img_filepath,
                        'source': 'tbank'
                    })
                    duplicate_comments.append(text)
        except Exception as e:
            self.logger.info(f"Parsed {len(reviews)} reviews from tbank for {secid}")
        
        return reviews

