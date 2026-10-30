"""
List the model ids your API keys can use right now.
Usage:  python -m scripts.list_models
"""
import httpx

from core.config import settings


def main() -> None:
    with httpx.Client(timeout=20) as client:
        if settings.groq_api_key:
            response = client.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            )
            print(f"Groq: HTTP {response.status_code}")
            if response.is_success:
                ids = sorted(item["id"] for item in response.json().get("data", []))
                for model_id in ids:
                    print("  ", model_id)
                print(f"Configured GROQ_MODEL={settings.groq_model} -> listed: {settings.groq_model in ids}")
        else:
            print("Groq: GROQ_API_KEY is not set")

        print()
        if settings.gemini_api_key:
            response = client.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": settings.gemini_api_key},
                params={"pageSize": 200},
            )
            print(f"Gemini: HTTP {response.status_code}")
            if response.is_success:
                ids = sorted(
                    item["name"].removeprefix("models/")
                    for item in response.json().get("models", [])
                    if "generateContent" in item.get("supportedGenerationMethods", [])
                )
                for model_id in ids:
                    print("  ", model_id)
                print(f"Configured GEMINI_MODEL={settings.gemini_model} -> listed: {settings.gemini_model in ids}")
        else:
            print("Gemini: GEMINI_API_KEY is not set")


if __name__ == "__main__":
    main()