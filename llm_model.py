import os
import re
import torch
import torchvision
from transformers import AutoProcessor, AutoModelForImageTextToText
from translate import Translate

try:
    from flash_attn import flash_attn_qkvpacked_func, flash_attn_func
    from flash_attn.bert_padding import pad_input, unpad_input, index_first_axis
    from flash_attn.flash_attn_interface import flash_attn_varlen_func
    FLASH_ATTN_2_AVAILABLE = True
except ImportError:
    FLASH_ATTN_2_AVAILABLE = False


class SmolVLM2:
    def __init__(self, device: str = "cuda"):
        if torch.cuda.is_available() and device != "cpu":
            properties = torch.cuda.get_device_properties(device)
            available_vram_gb = (properties.total_memory - torch.cuda.memory_allocated()) / (1024 ** 3)

            if available_vram_gb > 5.5 and FLASH_ATTN_2_AVAILABLE:
                model_path = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
            elif available_vram_gb > 12 and not FLASH_ATTN_2_AVAILABLE:
                model_path = "HuggingFaceTB/SmolVLM2-2.2B-Instruct"
            else:
                model_path = "HuggingFaceTB/SmolVLM2-500M-Video-Instruct"
        else:
            model_path = None

        self.device = device
        self.processor = AutoProcessor.from_pretrained(model_path) if model_path else None
        self.model = AutoModelForImageTextToText.from_pretrained(
            model_path,
            torch_dtype=torch.bfloat16,
            device_map=self.device,
            _attn_implementation="flash_attention_2" if FLASH_ATTN_2_AVAILABLE else None
        ) if model_path else None
        self.translator = Translate()

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
        system_prompt = "You are a helpful finance assistant that can understand an image. Describe what you see on the image and what's happening in it."
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"type": "video", "path": image_path},
                    {"type": "text", "text": prompt}
                ]
            }
        ]

    def process_image_analyser(self, image_path: str, prompt: str = None) -> str:
        messages = self.prompt_image_analyser(image_path, prompt)
        response = self.generate(messages, max_new_tokens=512)
        return response

    def prompt_text_analyser(self, text: str, prompt: str = None):
        text = self.translator.translate(text, src_lang='Russian', trg_lang='English')
        prompt = "What type of video is this and what's happening in it? Be specific about the content type and general activities you observe." if prompt is None or not isinstance(prompt, str) else prompt
        system_prompt = "You are a financial analyst who understands investments, but you have to filter comments and respond only if the comment contains financial information, otherwise you say it is not about finance and investments."
        return [
            {
                "role": "system",
                "content": [{"type": "text", "text": system_prompt}]
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": text},
                    {"type": "text", "text": prompt}
                ]
            }
        ]


if __name__ == '__main__':
    smoll = SmolVLM2()
    smoll.prompt_image_analyser(image_path="/home/user/Downloads/c8e52fd7-4f47-4c1a-adf5-5bea9e83605b-original.jpeg")