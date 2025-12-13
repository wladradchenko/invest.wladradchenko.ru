"""
Base parser class for reviews
"""
import re
import os
import uuid
import aiohttp
import logging
import hashlib
from abc import ABC, abstractmethod
from typing import List, Dict
from datetime import datetime, timedelta
from PIL import Image
from io import BytesIO


class BaseParser(ABC):
    """Base class for review parsers"""
    DAYS = 7
    MEDIA_PATH = os.path.join('media', 'img')
    USE_IMAGE = True

    def __init__(self):
        self.logger = logging.getLogger(f"parser.{self.__class__.__name__}")
        self.session: aiohttp.ClientSession = None
        self.img_hashes = set()
        if not os.path.exists(self.MEDIA_PATH) and self.USE_IMAGE:
            os.makedirs(self.MEDIA_PATH, exist_ok=True)
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30),
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        )
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_html(self, url: str) -> str:
        """Fetch HTML content from URL"""
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    return await response.text()
                else:
                    self.logger.error(f"Failed to fetch {url}: status {response.status}")
                    return ""
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {e}")
            return ""

    async def download_file(self, img_url):
        if not img_url:
            return None
        filename = f"{uuid.uuid4()}.jpg"
        filepath = os.path.join(self.MEDIA_PATH, filename)
        async with aiohttp.ClientSession() as session:
            async with session.get(img_url) as resp:
                if resp.status == 200:
                    img_bytes = await resp.read()

                    img_hash = hashlib.md5(img_bytes).hexdigest()
                    if img_hash in self.img_hashes:
                        return None

                    with Image.open(BytesIO(img_bytes)) as img:
                        rgb_img = img.convert("RGB")
                        rgb_img.save(filepath, format="JPEG")
                    self.img_hashes.add(img_hash)

                    return filepath
        return None

    @staticmethod
    def clean_text(text: str) -> str:
        """
        Удаляет эмодзи и смайлы из текста
        """
        # простая regex для unicode emoji
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U00002700-\U000027BF"  # dingbats
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE
        )
        text = emoji_pattern.sub(r'', text)
        text = text.strip()
        return text

    def parse_date(self, date_str: str) -> datetime:
        """Parse date string to datetime"""
        if not date_str:
            return datetime.now()
        
        date_str = date_str.strip()
        
        # Common date formats
        formats = [
            '%Y-%m-%d',
            '%d.%m.%Y',
            '%d/%m/%Y',
            '%Y-%m-%d %H:%M:%S',
            '%d.%m.%Y %H:%M',
            '%d %B %Y',
            '%d %b %Y',
            '%Y-%m-%dT%H:%M:%S',
            '%Y-%m-%dT%H:%M:%SZ',
            '%d.%m.%Y %H:%M:%S',
            '%Y-%m-%d %H:%M',
            'сегодня',
            'вчера',
        ]
        
        # Handle Russian relative dates
        date_str_lower = date_str.lower()
        if 'сегодня' in date_str_lower or 'today' in date_str_lower:
            return datetime.now()
        if 'вчера' in date_str_lower or 'yesterday' in date_str_lower:
            return datetime.now() - timedelta(days=1)
        
        # Try to extract time if present
        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except:
                continue
        
        # Try to parse ISO format manually
        try:
            # Remove timezone info if present
            date_str_clean = date_str.split('+')[0].split('Z')[0].split('T')[0]
            if len(date_str_clean) == 10:  # YYYY-MM-DD
                return datetime.strptime(date_str_clean, '%Y-%m-%d')
        except:
            pass
        
        # If no format matches, return current date
        self.logger.warning(f"Could not parse date: {date_str}, using current date")
        return datetime.now()
    
    def is_this_week(self, date: datetime) -> bool:
        """Check if date is within current week"""
        today = datetime.now()
        week_start = today - timedelta(days=today.weekday())
        week_end = week_start + timedelta(days=6)
        return week_start.date() <= date.date() <= week_end.date()
    
    @abstractmethod
    async def parse_reviews(self, secid: str) -> List[Dict]:
        """Parse reviews for a security. Returns list of {text, date}"""
        pass

