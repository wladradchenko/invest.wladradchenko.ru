import os
from typing import Optional
import torch
import torch.nn.functional as F
import torchvision
from transformers import pipeline, AutoProcessor, AutoModelForImageTextToText, set_seed, AutoTokenizer, AutoModelForSequenceClassification
from translate import Translate
import asyncio
from huggingface_hub import hf_hub_download, list_repo_files
from tqdm.auto import tqdm


try:
    from flash_attn import flash_attn_qkvpacked_func, flash_attn_func
    from flash_attn.bert_padding import pad_input, unpad_input, index_first_axis
    from flash_attn.flash_attn_interface import flash_attn_varlen_func
    FLASH_ATTN_2_AVAILABLE = True
except ImportError:
    FLASH_ATTN_2_AVAILABLE = False


class SentimentAnalyzer:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODEL_PATH = os.path.join(BASE_DIR, "model")

    def __init__(self, device="cuda"):
        self.tokenizer = AutoTokenizer.from_pretrained("yiyanghkust/finbert-tone", cache_dir=self.MODEL_PATH)
        self.model = AutoModelForSequenceClassification.from_pretrained("yiyanghkust/finbert-tone", cache_dir=self.MODEL_PATH)
        self.device = device
        self.model.to(device)

    def analyze(self, text: str) -> dict:
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=512).to(self.device)
        with torch.no_grad():
            outputs = self.model(**inputs)
            probs = F.softmax(outputs.logits, dim=-1)[0]  # shape: [3]
        # 0=negative, 1=neutral, 2=positive
        return {"negative": round(probs[0].item(), 4), "neutral": round(probs[1].item(), 4), "positive": round(probs[2].item(), 4)}


class EmotionAnalyzer:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODEL_PATH = os.path.join(BASE_DIR, "model")

    def __init__(self, device="cuda"):
        device_id = 0 if device == "cuda" else -1
        repo_id = "bhadresh-savani/bert-base-uncased-emotion"

        files = list_repo_files(repo_id)
        for fname in tqdm(files, desc=f"Checking files of text classification"):
            hf_hub_download(repo_id=repo_id, filename=fname, cache_dir=self.MODEL_PATH)

        tokenizer = AutoTokenizer.from_pretrained(repo_id, cache_dir=self.MODEL_PATH)
        model = AutoModelForSequenceClassification.from_pretrained(repo_id, cache_dir=self.MODEL_PATH)

        self.classifier = pipeline(
            "text-classification",
            model=model,
            tokenizer=tokenizer,
            device=device_id,
            top_k=3
        )

    def analyze(self, text: str) -> dict:
        if not text.strip():
            return {}

        classes = self.classifier(text[:512])
        if isinstance(classes[0], list):
            return {c.get('label'): round(c.get('score'), 4) for c in classes[0] if isinstance(c, dict) and c.get('score') >= 0.3}
        return {c.get('label'): round(c.get('score'), 4) for c in classes[0] if isinstance(c, dict) and c.get('score') >= 0.3}


class SmolVLM2:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MODEL_PATH = os.path.join(BASE_DIR, "model")

    def __init__(self, device: str = "cuda"):
        if not os.path.exists(self.MODEL_PATH):
            os.makedirs(self.MODEL_PATH, exist_ok=True)

        if torch.cuda.is_available() and device != "cpu":
            properties = torch.cuda.get_device_properties(device)
            available_vram_gb = (properties.total_memory - torch.cuda.memory_allocated()) / (1024 ** 3)

            if available_vram_gb > 5.5 and FLASH_ATTN_2_AVAILABLE:
                repo_id = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
            elif available_vram_gb > 12 and not FLASH_ATTN_2_AVAILABLE:
                repo_id = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
            else:
                repo_id = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
            # Fix seed to exclude random answers
            SEED = 42
            torch.manual_seed(SEED)
            torch.cuda.manual_seed_all(SEED)
            set_seed(SEED)
        else:
            repo_id = None

        self.device = device

        if repo_id:
            files = list_repo_files(repo_id)
            for fname in tqdm(files, desc=f"Checking files of LLM"):
                hf_hub_download(repo_id=repo_id, filename=fname, cache_dir=self.MODEL_PATH)

        self.processor = AutoProcessor.from_pretrained(repo_id, cache_dir=self.MODEL_PATH) if repo_id else None
        self.model = AutoModelForImageTextToText.from_pretrained(
            repo_id,
            dtype=torch.bfloat16,
            cache_dir=self.MODEL_PATH,
            device_map=self.device,
            _attn_implementation="flash_attention_2" if FLASH_ATTN_2_AVAILABLE else None
        ) if repo_id else None

    def generate(self, messages: list, max_new_tokens: int = 64):
        if self.processor is None or self.model is None:
            return None
        inputs = self.processor.apply_chat_template(
            messages[:8192],
            add_generation_prompt=True,
            tokenize=True,
            return_dict=True,
            return_tensors="pt",
        ).to(self.model.device, dtype=torch.bfloat16)
        generated_ids = self.model.generate(**inputs, max_new_tokens=max_new_tokens, do_sample=True, temperature=0.7)
        generated_output = self.processor.decode(generated_ids[0], skip_special_tokens=True).lower().split("assistant: ")[1]
        return generated_output

    @staticmethod
    def prompt_image_analyser(image_path: str, prompt: str = None):
        prompt = "What type of an image is this and what's happening in it? Be specific about the content type and general activities you observe." if prompt is None or not isinstance(prompt, str) else prompt
        system_prompt = "You are a helpful finance assistant that can understand an image. Describe what you see on the image and what's happening in it. Your answer should be short."
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"type": "image", "path": image_path},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

    def process_image_analyser(self, image_path: str, prompt: str = None) -> str:
        messages = self.prompt_image_analyser(image_path, prompt)
        response = self.generate(messages, max_new_tokens=128)
        return response

    @staticmethod
    def prompt_text_analyser(text: str, prompt: str = None):
        prompt = "Rate the signal to buy, hold or sell a security in the user COMMENT. But some messages are spam and discussions, and are not related to the topic of finance at all, filter them." if prompt is None or not isinstance(prompt, str) else prompt
        system_prompt = """
            You're a financial analyst and investing journalist. Analyze the comment. Determine whether the message is related to investment-relevant financial information, including: public companies, stocks, bonds, financial markets, investor events, earnings, guidance, strategy, capital expenditures, growth expectations, risks, or factors that may influence an investment decision.
            
            If the message is NOT related to investment-relevant financial information: Return exactly the word: invalid.
            If the message IS related to investment-relevant financial information: Evaluate the overall investment sentiment according to the following scale:
            
            Extremely negative investment signal (bankruptcy, default, fraud, delisting, severe sanctions, existential risk);
            Very negative signal (collapse in earnings, withdrawal of guidance, major regulatory or legal risks);
            Strong negative signal (significant deterioration in fundamentals, sharp margin or revenue decline);
            Moderately negative signal (noticeable problems, weak outlook, increasing risks);
            Slightly negative signal score  (minor issues, cautious tone, short-term headwinds);
            Neutral or purely informational content with no clear positive or negative investment implication;
            Slightly positive signal (mild optimism, stability, small positive developments);
            Moderately positive signal (solid results, improving outlook, controlled growth);
            Clearly positive signal score (strong performance, strategic progress, visible growth drivers);
            Very positive signal (strong growth expectations, major strategic advantages, high confidence);
            Extremely positive investment signal (exceptional performance, transformative events, strong long-term value creation);
        """
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"COMMENT: {text}"},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

    def process_text_analyser(self, text: str, prompt: str = None) -> str:
        messages = self.prompt_text_analyser(text, prompt)
        response = self.generate(messages, max_new_tokens=256)
        return response


class TextAnalyser:
    def __init__(self, device="cuda"):
        self.llm_analyzer = SmolVLM2(device)
        self.sentiment_analyzer = SentimentAnalyzer(device=device)  # TODO test on CPU
        self.emotion_analyzer = EmotionAnalyzer(device=device)  # TODO test on CPU
        self.translator = Translate()

    async def __call__(self, text: str, img_path: str = None) -> Optional[dict]:
        if not text:
            return None
        text = await self.translator.translate(text, src_lang='Russian', trg_lang='English')

        if img_path and os.path.exists(img_path):
            text += self.llm_analyzer.process_image_analyser(img_path)

        analys = self.llm_analyzer.process_text_analyser(str(text))
        if not self.process_text_sentiment(analys):
            return None

        prediction = self.sentiment_analyzer.analyze(analys)
        negative = prediction.get("negative")
        positive = prediction.get("positive")
        neutral = prediction.get("neutral")

        emotion = self.emotion_analyzer.analyze(analys)
        if positive == negative or neutral > 0.5:
            return emotion
        if negative > 0.5 or negative > positive:
            emotion["negative"] = negative
            return emotion
        emotion["positive"] = positive
        return emotion

    def _analyze_neural_networks_sync(self, text: str, img_path: str = None) -> Optional[dict]:
        """Synchronous version of neural network analysis (for thread pool execution)"""
        if not text:
            return None

        # Process image if provided
        if img_path and os.path.exists(img_path):
            text += self.llm_analyzer.process_image_analyser(img_path)

        # Analyze text with LLM
        analys = self.llm_analyzer.process_text_analyser(str(text))
        if not self.process_text_sentiment(analys):
            return None

        # Sentiment analysis
        prediction = self.sentiment_analyzer.analyze(analys)
        negative = prediction.get("negative")
        positive = prediction.get("positive")
        neutral = prediction.get("neutral")

        # Emotion analysis
        emotion = self.emotion_analyzer.analyze(analys)
        if positive == negative or neutral > 0.5:
            return emotion
        if negative > 0.5 or negative > positive:
            emotion["negative"] = negative
            return emotion
        emotion["positive"] = positive
        return emotion

    @staticmethod
    def process_text_sentiment(text: str) -> bool:
        invest_terms = ["buy", "hold", "sell", "stock", "bond", "shares", "dividend", "earnings", "guidance", "revenue", "ebitda", "market", "investor"]
        if not any(t in text.lower() for t in invest_terms):
            return False
        return True


if __name__ == '__main__':
    analys_model = TextAnalyser()
    text1 = "Сегодня большой праздник. ровно 32 года назад 12 декабря 1993 года в 21.00 закончилось голосование. самое интересное и любопытное. в 18.00 явка была 40 % и до 21.00 стала 58% это при морозах, почти в полной темноте (начало 90-х) огромной уличной преступности люди почти в ночное время ломанулись на избирательные участки, чтобы проголосовать за Конституцию, вместо того, чтобы смотреть интереснейший футбол Межконтинентальгый Кубок Сан-Пауло-Милан."
    text2 = "🏦 $SBER после Дня инвестора (10 декабря) подтвердил ставку на экосистему: 110+ млн частных клиентов, 100+ млн в лояльности и 22+ млн в подписке, плюс активное внедрение ИИ (оценка эффекта ~550 млрд руб. к 2026 г. при инвестициях ~600 млрд за 2024–2026).📊 По итогам 11М2025 банк держит темп: кредитование растёт, качество портфеля выглядит устойчиво (просрочка ~2,6%, CoR таргет 1,5% в 2025 и ~1,4% в 2026), а эффективность остаётся сильной (CIR около 30–32%).  На 2026 — ориентир ROE ~22%, капитал около 13,3%, дивполитика 50% прибыли (оценка ~37,8 руб./акц., доходность ~12,3%), мультипликатор P/B ~0,88x, таргет 360 руб. и взгляд «покупать»."
    print(asyncio.run(analys_model(text1)))
    print(asyncio.run(analys_model(text2)))
