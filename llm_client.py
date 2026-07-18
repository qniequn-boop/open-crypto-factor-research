# btclab/llm_client.py
# LLM API调用封装 —— 严格按照 PROJECT_DOC.md §10.1
# 兼容 OpenAI 格式(兼容 DeepSeek/智谱等)

import json
import requests
from typing import List, Dict, Optional
import config

class Candidate:
    def __init__(self, hypothesis: str, dsl_expr: str, direction: str):
        self.hypothesis = hypothesis
        self.dsl_expr = dsl_expr
        self.direction = direction  # long / short / neutral

    def __repr__(self):
        return f"Candidate(direction={self.direction}, expr={self.dsl_expr[:50]}...)"

    def to_dict(self):
        return {
            'hypothesis': self.hypothesis,
            'dsl_expr': self.dsl_expr,
            'direction': self.direction,
        }

class LLMClient:
    def __init__(self, base_url: str = None, api_key: str = None, model: str = None):
        self.base_url = base_url or config.LLM_BASE_URL
        self.api_key = api_key or config.LLM_API_KEY
        self.model = model or config.LLM_MODEL
        self.timeout = config.LLM_TIMEOUT

    def _call(self, system_prompt: str, user_prompt: str) -> str:
        headers = {
            'Content-Type': 'application/json',
            'Authorization': f"Bearer {self.api_key}",
        }
        payload = {
            'model': self.model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': user_prompt},
            ],
            'temperature': 0.7,
            'response_format': {'type': 'json_object'},
        }

        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=headers, json=payload, timeout=self.timeout
        )

        if resp.status_code != 200:
            raise IOError(f"LLM API返回 {resp.status_code}: {resp.text}")

        data = resp.json()
        return data['choices'][0]['message']['content']

    def generate_candidates(self, system_prompt: str, user_prompt: str,
                            n_candidates: int = None) -> List[Candidate]:
        n_candidates = n_candidates or config.CANDIDATES_PER_ROUND

        # 构建输出要求
        output_format = (
            "返回一个JSON对象, 包含 candidates 数组 (共" + str(n_candidates) + "个):\n"
            '{"candidates": [{"hypothesis": "我预期X能预测Y, 因为Z", "dsl_expr": "因子表达式", "direction": "long/short/neutral"}]}'
        )

        full_user_prompt = user_prompt + output_format

        # 重试机制 (最多3次)
        for attempt in range(3):
            try:
                response_text = self._call(system_prompt, full_user_prompt)
                candidates = self._parse_response(response_text, n_candidates)
                if candidates:
                    return candidates
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"LLM调用失败 (尝试 {attempt+1}/3): {e}")

        return []

    def _parse_response(self, text: str, n_expected: int) -> List[Candidate]:
        try:
            data = json.loads(text)
            raw_candidates = data.get('candidates', [])

            candidates = []
            for c in raw_candidates:
                hypothesis = c.get('hypothesis', '')
                dsl_expr = c.get('dsl_expr', '')
                direction = c.get('direction', 'neutral')

                if not hypothesis or not dsl_expr:
                    continue

                direction = direction.lower()
                if direction not in ('long', 'short', 'neutral'):
                    direction = 'neutral'

                candidates.append(Candidate(hypothesis, dsl_expr, direction))

            return candidates
        except json.JSONDecodeError as e:
            print(f"JSON解析失败: {e}")
            return []


# 全局实例
_client: Optional[LLMClient] = None

def get_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
