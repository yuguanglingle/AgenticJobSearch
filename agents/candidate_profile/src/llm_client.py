import os
from openai import OpenAI


class LLMClient:
    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required.")
        self.model = os.getenv("LLM_MODEL", "gpt-4o-mini")
        base_url = os.getenv("LLM_BASE_URL")
        if base_url:
            self.client = OpenAI(api_key=api_key, base_url=base_url)
        else:
            self.client = OpenAI(api_key=api_key)
        self.last_usage = None

    def generate(self, *, system_prompt: str, user_prompt: str) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
        )
        self.last_usage = response.usage
        return response.choices[0].message.content or ""

    def fix_json(self, *, system_prompt: str, bad_json: str) -> str:
        prompt = (
            "Fix the following so it is valid JSON that matches the schema. "
            "Return only JSON, no markdown or commentary.\n\n"
            f"{bad_json}"
        )
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )
        self.last_usage = response.usage
        return response.choices[0].message.content or ""

    def usage_summary(self) -> str:
        if not self.last_usage:
            return "tokens: unavailable"
        return (
            "tokens: prompt="
            f"{self.last_usage.prompt_tokens} completion={self.last_usage.completion_tokens} "
            f"total={self.last_usage.total_tokens}"
        )

