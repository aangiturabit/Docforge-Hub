from openai import AzureOpenAI
from dotenv import load_dotenv
import os

load_dotenv()

client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_LLM_KEY"),
    api_version=os.getenv("AZURE_LLM_API_VERSION"),
    azure_endpoint=os.getenv("AZURE_LLM_ENDPOINT")
)

deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI")


def generate_with_llm(prompt: str) -> str:
    try:
        response = client.chat.completions.create(
            model=deployment,
            messages=[
                {
                    "role": "system",
                    "content": "You are a professional business document writer for a SaaS company. Generate complete, well-structured, professional documents. Only return the document content with no extra commentary."
                },
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            max_tokens=4000,
            temperature=0.1
        )
        return response.choices[0].message.content

    except Exception as e:
        raise RuntimeError(f"LLM generation failed: {str(e)}")