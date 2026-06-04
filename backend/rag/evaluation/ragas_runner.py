import os
import json
import math
import sys
import types
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

# RAGAS 0.4.x imports this VertexAI adapter at module load time even when the
# evaluation uses Azure OpenAI. Newer langchain-community versions no longer
# expose this module path, so provide a minimal import shim.
if "langchain_community.chat_models.vertexai" not in sys.modules:
    vertexai_shim = types.ModuleType("langchain_community.chat_models.vertexai")

    class ChatVertexAI:
        pass

    vertexai_shim.ChatVertexAI = ChatVertexAI
    sys.modules["langchain_community.chat_models.vertexai"] = vertexai_shim

from ragas import evaluate
from ragas.metrics import faithfulness, answer_relevancy
from ragas.llms import LangchainLLMWrapper
from ragas.embeddings import LangchainEmbeddingsWrapper
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from datasets import Dataset

load_dotenv(".env")

EVAL_OUTPUT_DIR = Path("data/evaluations")


# ─────────────────────────────────────────────
# AZURE LLM + EMBEDDINGS FOR RAGAS
# ─────────────────────────────────────────────
def get_ragas_llm():
    llm = AzureChatOpenAI(
        api_key          = os.getenv("AZURE_OPENAI_LLM_KEY"),
        azure_endpoint   = os.getenv("AZURE_LLM_ENDPOINT"),
        api_version      = os.getenv("AZURE_LLM_API_VERSION"),
        azure_deployment = os.getenv("AZURE_LLM_DEPLOYMENT_41_MINI"),
        temperature      = 0,
        timeout          = 120,  
        max_retries      = 2,     
    )
    return LangchainLLMWrapper(llm)


def get_ragas_embeddings():
    emb = AzureOpenAIEmbeddings(
        api_key          = os.getenv("AZURE_OPENAI_EMB_KEY"),
        azure_endpoint   = os.getenv("AZURE_EMB_ENDPOINT"),
        api_version      = os.getenv("AZURE_EMB_API_VERSION"),
        azure_deployment = os.getenv("AZURE_EMB_DEPLOYMENT"),
    )
    return LangchainEmbeddingsWrapper(emb)


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────
def safe_score(val):
  
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    return round(float(val), 4)


def avg(results, key):

    vals = [
        r["ragas"][key]
        for r in results
        if r.get("ragas") and r["ragas"].get(key) is not None
    ]
    return round(sum(vals) / len(vals), 4) if vals else None


# ─────────────────────────────────────────────
# RUN EVALUATION
# ─────────────────────────────────────────────
def run_ragas_evaluation(
    results  : list,
    run_name : str,
    config   : dict,
) -> dict:

    try:
        dataset = Dataset.from_dict({
            "question": [r["question"] for r in results],
            "answer"  : [r["answer"]   for r in results],
            "contexts": [r["contexts"] for r in results],
        })

        ragas_llm = get_ragas_llm()
        ragas_emb = get_ragas_embeddings()

        metrics = [faithfulness, answer_relevancy]
        for metric in metrics:
            metric.llm        = ragas_llm
            metric.embeddings = ragas_emb

        print(f"Running RAGAS evaluation for {len(results)} questions...")

        scores = evaluate(
            dataset,
            metrics          = metrics,
            raise_exceptions = False,
            batch_size       = 1, 
        )
        scores_dict = scores.to_pandas().to_dict(orient="records")

        # Attach per-question scores
        for i, r in enumerate(results):
            r["ragas"] = {
                "faithfulness"    : safe_score(scores_dict[i].get("faithfulness")),
                "answer_relevancy": safe_score(scores_dict[i].get("answer_relevancy")),
            }

        # Aggregate
        aggregate = {
            "faithfulness"    : avg(results, "faithfulness"),
            "answer_relevancy": avg(results, "answer_relevancy"),
        }

        report = {
            "run_name"  : run_name,
            "timestamp" : datetime.utcnow().isoformat(),
            "config"    : config,
            "total"     : len(results),
            "results"   : results,
            "aggregate" : aggregate,
        }

        EVAL_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = EVAL_OUTPUT_DIR / f"{run_name}.json"
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)

        print(f"Saved to {output_path}")
        print(f"Aggregate: {aggregate}")

        return report

    except Exception as e:
        print(f"RAGAS evaluation failed: {e}")
        raise
