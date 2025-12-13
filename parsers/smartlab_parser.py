"""
Parser for smart-lab.ru reviews
"""
import os
import uuid
from typing import List, Dict
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from .base_parser import BaseParser


class SmartLabParser(BaseParser):
    """Parser for smart-lab.ru forum"""
    
    BASE_URL = "https://smart-lab.ru"

    async def parse_reviews(self, secid: str) -> List[Dict]:
        """Parse reviews from smart-lab.ru"""
        reviews = []
        duplicate_comments = []
        secid_lower = secid.upper()
        today = datetime.now().date()

        dates_list = [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(self.DAYS, 0, -1)]
        for date in dates_list:
            url = f"{self.BASE_URL}/forum/{secid_lower}/{date}"

            html = await self.fetch_html(url)
            if not html:
                continue

            try:
                soup = BeautifulSoup(html, 'lxml')
                pagination = soup.find('div', id='pagination')
                comments = []

                if pagination:
                    for a_tag in pagination.find_all('a', href=True):
                        try:
                            page = await self.fetch_html(f"{self.BASE_URL}/{a_tag['href']}")
                            soup = BeautifulSoup(page, 'lxml')
                            comments.extend(soup.find_all(attrs={'data-type': 'comment'}))
                        except Exception as e:
                            self.logger.error(f"Error parsing page: {e}")
                            continue
                else:
                    comments.extend(soup.find_all(attrs={'data-type': 'comment'}))

                for comment in comments:
                    try:
                        time_elem = comment.find('time', attrs={'datetime': True})
                        date_str = date if not time_elem else time_elem['datetime']
                        review_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))

                        text_elem = comment.find(class_='text')
                        if not text_elem:
                            continue

                        reply_elem = text_elem.find(class_='reply')
                        if reply_elem:
                            reply_elem.decompose()

                        if self.USE_IMAGE:
                            a_elem = comment.find('a', class_='imgpreview')
                            img_elem = a_elem.find('img') if a_elem else None
                            img_url = img_elem.get('src') if img_elem else None
                            img_filepath = await self.download_file(f"{self.BASE_URL}/{img_url}") if img_url else None
                        else:
                            img_filepath = False

                        text = self.clean_text(text_elem.get_text(strip=True))
                        if not text or len(text) < 10:
                            continue

                        if self.is_this_week(review_date) and text not in duplicate_comments:
                            reviews.append({
                                'text': text,
                                'date': review_date.strftime('%Y-%m-%d %H:%M'),
                                'img': img_filepath,
                                'source': 'smart-lab'
                            })
                            duplicate_comments.append(text)

                    except Exception as e:
                        self.logger.error(f"Error parsing post: {e}")
                        continue
                self.logger.info(f"Parsed {len(reviews)} reviews from smart-lab for {secid}")
            except Exception as e:
                self.logger.error(f"Error parsing smart-lab page: {e}")
        
        return reviews

