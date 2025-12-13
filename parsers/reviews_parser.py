"""
Unified reviews parser that combines all sources
"""
import logging
from typing import List, Dict
from datetime import datetime
from .smartlab_parser import SmartLabParser
from .pulse_parser import PulseParser


class ReviewsParser:
    """Unified parser for reviews from multiple sources"""
    
    def __init__(self):
        self.logger = logging.getLogger("reviews_parser")
        self.parsers = [
            SmartLabParser(),
            PulseParser()
        ]
    
    async def parse_reviews(self, secid: str, start_date=None) -> List[Dict]:
        """
        Parse reviews from all sources for a security.
        Returns list of {text, date} without source information.
        """
        all_reviews = []
        
        # Parse from all sources in parallel
        for parser in self.parsers:
            try:
                async with parser:
                    reviews = await parser.parse_reviews(secid, start_date)
                    # Remove source from reviews (as per requirement)
                    # for review in reviews:
                    #     review.pop('source', None)
                    all_reviews.extend(reviews)
            except Exception as e:
                self.logger.error(f"Error parsing from {parser.__class__.__name__}: {e}")
                continue
        
        # Sort by date (newest first)
        all_reviews.sort(key=lambda x: x.get('date', datetime.now()), reverse=True)
        
        self.logger.info(f"Total reviews parsed for {secid}: {len(all_reviews)}")
        return all_reviews

