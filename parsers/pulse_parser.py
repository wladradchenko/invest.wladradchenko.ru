"""
Parser for tbank.ru pulse reviews
"""
from typing import List, Dict
from datetime import datetime
from bs4 import BeautifulSoup
from .base_parser import BaseParser


class PulseParser(BaseParser):
    """Parser for tbank.ru pulse"""
    
    BASE_URL = "https://www.tbank.ru/invest/stocks"
    
    async def parse_reviews(self, secid: str) -> List[Dict]:
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

                if self.USE_IMAGE:
                    parent = comment.find_parent(attrs={'data-qa-file': 'PulsePost'})
                    img_elem = parent.find('img', attrs={'data-qa-file': 'ImageTiles'})
                    img_url = img_elem.get('src') if img_elem else None
                    img_filepath = await self.download_file(img_url) if img_url else None
                else:
                    img_filepath = None

                # Filter by current week
                if text not in duplicate_comments:
                    reviews.append({
                        'text': text,
                        'date': datetime.now().strftime('%Y-%m-%d %H:%M'),
                        'img': img_filepath,
                        'source': 'tbank'
                    })
                    duplicate_comments.append(text)
        except Exception as e:
            self.logger.info(f"Parsed {len(reviews)} reviews from tbank for {secid}")
        
        return reviews

