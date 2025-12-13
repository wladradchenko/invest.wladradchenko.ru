import os
import aiohttp
import pathlib
import logging
import argostranslate.package
import argostranslate.translate  # pip install argostranslate


logging.getLogger("argostranslate").setLevel(logging.WARNING)
logging.getLogger("argostranslate.utils").setLevel(logging.WARNING)

logging.getLogger("stanza").setLevel(logging.WARNING)
logging.getLogger("stanza.pipeline").setLevel(logging.WARNING)


class Translate:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODEL_PATH = os.path.join(BASE_DIR, "translate")

    def __init__(self):
        if not os.path.exists(self.MODEL_PATH):
            os.makedirs(self.MODEL_PATH, exist_ok=True)

        self.model_urls = {
            "Russian_English": "https://argos-net.com/v1/translate-ru_en-1_9.argosmodel",
            "English_Russian": "https://argos-net.com/v1/translate-en_ru-1_9.argosmodel"
        }

        self.model_filenames = {
            "Russian_English": "translate-ru_en-1_9.argosmodel",
            "English_Russian": "translate-en_ru-1_9.argosmodel"
        }

    @staticmethod
    async def download_file(download_path: str, download_link: str) -> bool:
        # Ensure dir exists
        os.makedirs(os.path.dirname(download_path), exist_ok=True)
        print(f"Prepare download {download_link} to {download_path}")

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(download_link) as response:
                    response.raise_for_status()

                    # Open file for writing
                    with open(download_path, "wb") as f:
                        # Write data in chunks
                        async for chunk in response.content.iter_chunked(8192):
                            if not chunk:
                                break
                            f.write(chunk)
            return True

        except Exception as e:
            print(f"Error downloading: {e}")
            return False

    @staticmethod
    async def get_remote_file_size(download_link: str) -> int | None:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.head(download_link) as response:
                    size = response.headers.get("Content-Length")
                    if size is None:
                        async with session.get(download_link) as r2:
                            size = r2.headers.get("Content-Length")
                    return int(size) if size else None

        except Exception as e:
            print(f"Error getting remote file size: {e}")
            return None

    async def check_download_size(self, download_path: str, download_link: str) -> bool:
        if not os.path.exists(download_path):
            return await self.download_file(download_path, download_link)

        local_size = os.path.getsize(download_path)
        remote_size = await self.get_remote_file_size(download_link)

        if remote_size is None:
            print("Remote size unknown, re‑downloading")
            return await self.download_file(download_path, download_link)

        if local_size == remote_size:
            print(f"File verified {download_path} ({local_size} bytes)")
            return True

        print("Size mismatch, re‑downloading")
        os.remove(download_path)
        return await self.download_file(download_path, download_link)

    async def install_package(self, language: str) -> bool:
        download_link = self.model_urls.get(language)
        download_path = os.path.join(self.MODEL_PATH, self.model_filenames.get(language))
        if await self.check_download_size(download_path, download_link):
            package_path = pathlib.Path(download_path)
            argostranslate.package.install_from_path(package_path)
            return True
        return False

    @staticmethod
    def get_language_indices(src_lang, trg_lang):
        installed_languages = argostranslate.translate.get_installed_languages()
        installed_languages_list = [str(lang) for lang in installed_languages]

        try:
            src_idx = installed_languages_list.index(src_lang)
            tgt_idx = installed_languages_list.index(trg_lang)
            return src_idx, tgt_idx, installed_languages
        except ValueError:
            return -1, -1, installed_languages

    async def translate(self, text, src_lang='Russian', trg_lang='English') -> str:
        if not isinstance(text, str):
            return text

        src_idx, tgt_idx, installed_languages = self.get_language_indices(src_lang, trg_lang)

        if src_idx == -1 or tgt_idx == -1:
            if await self.install_package(f"{src_lang}_{trg_lang}"):
                src_idx, tgt_idx, installed_languages = self.get_language_indices(src_lang, trg_lang)
            else:
                return text

        translation = installed_languages[src_idx].get_translation(installed_languages[tgt_idx])
        if translation is None:
            print("Error. The language pack is not installed.")
            return text
        return translation.translate(text)
