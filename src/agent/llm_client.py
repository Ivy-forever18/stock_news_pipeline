import os
import pickle
from openai import OpenAI

import time
import json

import requests
import yaml
from tqdm import tqdm
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed

API_KEY_PATH = "./config/api_keys.yaml"


def _load_api_keys() -> dict:
    """Load keys from env first, then optional YAML config file."""
    keys = {
        "DEEPSEEK_API_KEY": os.environ.get("DEEPSEEK_API_KEY", ""),
        "OPENAI_API_KEY": os.environ.get("OPENAI_API_KEY", ""),
        "GEMINI_API_KEY": os.environ.get("GEMINI_API_KEY", ""),
        "CLAUDE_API_KEY": os.environ.get("CLAUDE_API_KEY", ""),
        # Optional generic gateway key if user chooses service_provider='all'
        "AIO_API_KEY": os.environ.get("AIO_API_KEY", ""),
    }

    try:
        if os.path.exists(API_KEY_PATH):
            with open(API_KEY_PATH, "r", encoding="utf-8") as file:
                cfg = yaml.safe_load(file) or {}
            for k in keys:
                if not keys[k]:
                    keys[k] = cfg.get(k, "") or ""
    except Exception:
        # Keep env-based values even if config loading fails
        pass

    return keys


_API_KEYS = _load_api_keys()
DEEPSEEK_API_KEY = _API_KEYS.get("DEEPSEEK_API_KEY", "")
OPENAI_API_KEY = _API_KEYS.get("OPENAI_API_KEY", "")
GEMINI_API_KEY = _API_KEYS.get("GEMINI_API_KEY", "")
CLAUDE_API_KEY = _API_KEYS.get("CLAUDE_API_KEY", "")
AIO_API_KEY = _API_KEYS.get("AIO_API_KEY", "")


def call_llm(
    prompt,
    model="deepseek-chat",
    api_key=None,
    base_url=None,
    json_output=False,
    system_prompt="You are a helpful assistant.",
    temperature=1.0,
    local=False,
    local_port=8000,
    return_raw=False,
    max_try=5,
    timeout=60,
    service_provider="all",  # 'all' use all-in-one, 'default' is default URL
    save_raw_dir='.temp/llm_history', # in default we will save LLM calling record for auditing, to disable this please use None
):
    if save_raw_dir:
        os.makedirs(save_raw_dir, exist_ok=True)
        
    # If local is True, send request to local server, we only support using VLLM
    if local:
        url = f"http://localhost:{local_port}/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        if json_output:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            raise RuntimeError(f"Local model server error: {e}")

    # Otherwise, use API-based client
    if service_provider == "default":
        if model.startswith("gpt-"):
            client = OpenAI(
                api_key=api_key or OPENAI_API_KEY,
                base_url=base_url or "https://api.openai-proxy.com/v1",
            )
        elif model.startswith("gemini-"):
            client = OpenAI(
                api_key=api_key or GEMINI_API_KEY,
                base_url=base_url or "https://gemini-openai-proxy.deno.dev/v1",
            )
        elif model.startswith("deepseek-"):
            client = OpenAI(
                api_key=api_key or DEEPSEEK_API_KEY,
                base_url=base_url or "https://api.deepseek.com",
            )
        else:
            raise ValueError(
                "Unsupported model prefix for service_provider='default'. "
                "Use gpt-*, gemini-*, deepseek-* or pass service_provider='all'."
            )
    elif service_provider == "all":
        # General API gateway, requires AIO_API_KEY configured via env or config/api_keys.yaml
        if not AIO_API_KEY:
            raise ValueError("service_provider='all' requires AIO_API_KEY in env or config/api_keys.yaml")
        client = OpenAI(
            api_key=AIO_API_KEY,
            base_url="https://api2.aigcbest.top/v1",
            timeout=timeout,
        )

    else:
        raise ValueError(f"Unknown service_provider: {service_provider}")

    request_params = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "stream": False,
    }
    if json_output:
        request_params["response_format"] = {"type": "json_object"}

    for attempt in range(max_try):
        try:
            response = client.chat.completions.create(**request_params)
            if save_raw_dir:
                response_struct = response.model_dump() 
                raw_response_name = time.strftime("%Y%m%d_%H%M%S", time.localtime()) + ".json"
                save_path = os.path.join(save_raw_dir, raw_response_name)
                with open(save_path, "w", encoding="utf-8") as f:
                    json.dump(response_struct, f, ensure_ascii=False, indent=2)

            if return_raw:
                return response
            else:
                return response.choices[0].message.content.strip()

        except Exception as e:
            if "Too Many Requests" in str(e) and attempt < max_try - 1:
                sleep_time = 0.1
                print(f"Rate limited (API). Retrying in {sleep_time}s...")
                time.sleep(sleep_time)
                continue
            return f"LLM API error: {e}"


def batch_call_llm(
    prompts,
    model="deepseek-chat",
    api_key=None,
    base_url=None,
    json_output=False,
    system_prompt="You are a helpful assistant.",
    temperature=1.0,
    local=False,
    local_port=8000,
    latency=None,
    num_workers=4,
    return_raw=False,
    verbose=False,
    timeout=None,
    service_provider="all",
    save_raw_dir='~/.temp/llm_history',
):
    """
    Batch call LLM with multiple prompts while keeping the result order.

    Args:
        prompts (list[str]): List of prompts to query.
        model, api_key, base_url, json_output, system_prompt, temperature,
        local, local_port: Same as call_llm.
        num_workers (int): Number of parallel workers.
        verbose (bool): If True, show progress bar.

    Returns:
        list[str or None]: Responses in the same order as prompts. None if error.
    """

    results = [None] * len(prompts)

    def _worker(idx, prompt):
        try:
            if latency:
                import time

                time.sleep(latency)
            return (
                idx,
                call_llm(
                    prompt,
                    model=model,
                    api_key=api_key,
                    base_url=base_url,
                    json_output=json_output,
                    system_prompt=system_prompt,
                    temperature=temperature,
                    local=local,
                    local_port=local_port,
                    return_raw=return_raw,
                    timeout=timeout,
                    service_provider=service_provider,
                    save_raw_dir=save_raw_dir,
                ),
            )
        except Exception:
            return idx, None

    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        futures = [executor.submit(_worker, i, p) for i, p in enumerate(prompts)]
        if verbose:
            futures_iter = tqdm(
                as_completed(futures), total=len(prompts), desc="Processing"
            )
        else:
            futures_iter = as_completed(futures)

        for f in futures_iter:
            idx, res = f.result()
            results[idx] = res

    return results


# 🧪 Main test function
def main():
    prompt = (
        "Write a Python function to calculate the Sharpe ratio and explain each line."
    )

    print("=== 🧪 Gemini Client Test ===")
    try:
        result_gm = call_llm(prompt, model="gemini-2.5-flash")
        print(result_gm)
    except Exception as e:
        print(f"DeepSeek API Error: {e}")

    print("=== 🔍 DeepSeek API Test ===")
    try:
        result_ds = call_llm(prompt, model="deepseek-chat")
        print(result_ds)
    except Exception as e:
        print(f"DeepSeek API Error: {e}")

    print("\n=== 🤖 OpenAI GPT-4 Test ===")
    try:
        result_gpt = call_llm(prompt, model="gpt-4")
        print(result_gpt)
    except Exception as e:
        print(f"GPT-4 Error: {e}")

    print("\n=== 🖥️ Local Model Server Test ===")
    try:
        result_local = call_llm(
            prompt,
            model="deepseek-ai/deepseek-llm-7b-chat",
            local=True,
            local_port=8000,  # change if your server uses a different port
        )
        print(result_local)
    except Exception as e:
        print(f"Local Server Error: {e}")


def test_batch_call_llm():
    # 8 meaningful short questions
    prompts = [
        "What is AI?",
        "Define machine learning.",
        "What is deep learning?",
        "Explain overfitting.",
        "What is a neural network?",
        "Define reinforcement learning.",
        "What is natural language processing?",
        "Explain gradient descent.",
    ]

    # Run batch call with 4 workers
    results = batch_call_llm(
        prompts,
        model="gpt-4.1",  # replace with the model you want
        local=False,  # set False if using API
        num_workers=4,
        verbose=True,  # show progress bar
    )

    # Print results
    for i, (prompt, result) in enumerate(zip(prompts, results)):
        print(f"[{i}] Prompt: {prompt}")
        print(f"    Result: {result}\n")


if __name__ == "__main__":
    # test_batch_call_llm()
    main()