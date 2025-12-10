"""
File-based caching system for API responses
"""
import json
import os
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from pathlib import Path


class CacheManager:
    """File-based cache manager"""
    
    def __init__(self, cache_dir: str = "cache"):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.logger = logging.getLogger("cache")
    
    def _get_cache_key(self, url: str, params: Dict = None) -> str:
        """Generate cache key from URL and params"""
        key_string = url
        if params:
            key_string += json.dumps(params, sort_keys=True)
        return hashlib.md5(key_string.encode()).hexdigest()
    
    def _get_cache_path(self, key: str) -> Path:
        """Get cache file path"""
        return self.cache_dir / f"{key}.json"
    
    def get(self, url: str, params: Dict = None, ttl_hours: int = 24) -> Optional[Dict]:
        """Get cached data if exists and not expired"""
        key = self._get_cache_key(url, params)
        cache_path = self._get_cache_path(key)
        
        if not cache_path.exists():
            return None
        
        try:
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check expiration
            cached_time = datetime.fromisoformat(data.get('cached_at', '2000-01-01'))
            if datetime.now() - cached_time > timedelta(hours=ttl_hours):
                # Expired, delete cache
                cache_path.unlink()
                return None
            
            return data.get('data')
        except Exception as e:
            self.logger.error(f"Error reading cache: {e}")
            return None
    
    def set(self, url: str, data: Any, params: Dict = None):
        """Cache data"""
        key = self._get_cache_key(url, params)
        cache_path = self._get_cache_path(key)
        
        try:
            cache_data = {
                'cached_at': datetime.now().isoformat(),
                'url': url,
                'params': params,
                'data': data
            }
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.error(f"Error writing cache: {e}")
    
    def clear_expired(self):
        """Clear all expired cache files"""
        if not self.cache_dir.exists():
            return
        
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                cached_time = datetime.fromisoformat(data.get('cached_at', '2000-01-01'))
                # Remove if older than 30 days
                if datetime.now() - cached_time > timedelta(days=30):
                    cache_file.unlink()
            except:
                # If can't read, delete
                cache_file.unlink()
    
    def clear_all(self):
        """Clear all cache"""
        if not self.cache_dir.exists():
            return
        
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()

