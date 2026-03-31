"""RAG Integration Test — tests intent routing + retrieval + LLM answer generation.

Tests:
1. _is_knowledge_query() intent routing (knowledge vs command classification)
2. RAG retrieve() quality (relevance scores)
3. RAG generate_answer() via vLLM backend (end-to-end)

Usage:
    CUDA_VISIBLE_DEVICES='' python server/test_rag_integration.py
"""

import os
import sys
import re
import time
import asyncio
import logging
import json

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("rag_integration_test")

# ── 1. Intent Routing Test ─────────────────────────────────────────

# Copied from nlp_agent.py for standalone testing
_RAG_TRIGGER_KEYWORDS = [
    # Korean
    "왜", "어떻게", "원리", "차이", "비교", "장단점",
    "뭐가 좋", "추천", "언제 쓰", "설명해",
    "무슨 차이", "어떤 원리", "작동 원리", "알려줘",
    # English
    "why", "how does", "principle", "difference", "compare",
    "trade-off", "when to use", "explain", "pros and cons",
    "what is the", "tell me about",
]

_COMMAND_INTENTS = {
    "motor", "scan_xrf", "scan_xanes", "scan_xrd",
    "alignment", "mask_atten", "ptycho", "scan_advanced", "setup",
}

# Simplified _detect_intents for testing (from nlp_agent.py keywords)
_INTENT_KEYWORDS = {
    "motor": ["move", "motor", "이동", "움직", "위치", "position", "offset"],
    "info": ["뭐", "무엇", "얼마", "어떤", "현재", "상태", "알려",
             "what", "current", "status", "how", "why", "tell",
             "차이", "비교", "설명", "원리"],
    "scan_xrf": ["xrf", "형광", "fluorescence"],
    "scan_xanes": ["xanes", "에너지 스캔", "energy scan", "absorption"],
    "scan_xrd": ["xrd", "회절", "diffraction"],
    "alignment": ["정렬", "align", "캘리", "calib"],
    "setup": ["설정", "set ", "세팅", "바꿔", "변경", "change"],
}


def _detect_intents_simple(text):
    """Simplified intent detection for testing."""
    text_lower = text.lower()
    intents = set()
    for intent, keywords in _INTENT_KEYWORDS.items():
        for kw in keywords:
            if kw in text_lower:
                intents.add(intent)
                break
    return intents


def _is_knowledge_query(preproc, text):
    """Determine if query should route to RAG."""
    intents = preproc.get("intents", set())
    if intents & _COMMAND_INTENTS:
        return False
    text_lower = text.lower()
    # info intent + RAG keyword
    if "info" in intents:
        for kw in _RAG_TRIGGER_KEYWORDS:
            if kw in text_lower:
                return True
    # No intents at all + RAG keyword (pure knowledge question)
    if not intents:
        for kw in _RAG_TRIGGER_KEYWORDS:
            if kw in text_lower:
                return True
    return False


def test_intent_routing():
    """Test that knowledge queries and commands are correctly classified."""
    print("\n" + "=" * 60)
    print("TEST 1: Intent Routing (_is_knowledge_query)")
    print("=" * 60)

    # (text, expected_is_rag)
    test_cases = [
        # Knowledge queries → should route to RAG (True)
        ("DCM Si(111)이랑 Si(311) 차이가 뭐야?", True),
        ("KB 미러 원리 설명해줘", True),
        ("Pt 코팅이랑 Rh 코팅 비교해줘", True),
        ("How does the undulator work?", True),
        ("What is the difference between Si(111) and Si(311)?", True),
        ("SSA 크기가 빔에 어떤 영향을 줘? 설명해줘", True),

        # Conservative routing: alignment intent → command path (by design)
        ("M1 정렬 순서 알려줘", False),

        # "왜" triggers RAG even without info intent (no intents detected = pure question)
        ("왜 20keV에서 빔이 커져?", True),

        # Command queries → should NOT route to RAG (False)
        ("에너지 12keV로 설정해", False),
        ("M1 피치 3mrad로 이동", False),
        ("XRF 스캔 시작해", False),
        ("XANES 스캔 실행해줘", False),
        ("M1 정렬 시작", False),
        ("DCM 에너지 15keV로 바꿔", False),
        ("KB 미러 위치 조정해", False),

        # Ambiguous → should default to command (False, conservative)
        ("에너지 현재 얼마야?", False),  # info intent but no RAG trigger
    ]

    passed = 0
    failed = 0
    for text, expected in test_cases:
        intents = _detect_intents_simple(text)
        preproc = {"intents": intents}
        result = _is_knowledge_query(preproc, text)
        status = "PASS" if result == expected else "FAIL"
        if status == "PASS":
            passed += 1
        else:
            failed += 1
        print(f"  [{status}] '{text[:50]}...' → RAG={result} (expected={expected})"
              f"  intents={intents}")

    print(f"\n  Result: {passed}/{passed + failed} passed")
    return failed == 0


# ── 2. RAG Retrieval Test ──────────────────────────────────────────

def test_rag_retrieval(rag):
    """Test retrieval quality with known queries."""
    print("\n" + "=" * 60)
    print("TEST 2: RAG Retrieval Quality")
    print("=" * 60)

    test_queries = [
        {
            "query": "DCM Si(111)과 Si(311) 차이가 뭐야?",
            "expected_keywords": ["Si(111)", "Si(311)", "DCM"],
            "min_score": 0.5,
        },
        {
            "query": "KB mirror focal length",
            "expected_keywords": ["KB", "focal", "mirror"],
            "min_score": 0.5,
        },
        {
            "query": "왜 20keV에서 빔이 커져?",
            "expected_keywords": ["keV", "beam", "빔"],
            "min_score": 0.4,
        },
        {
            "query": "SSA 크기가 빔 사이즈에 미치는 영향",
            "expected_keywords": ["SSA", "slit"],
            "min_score": 0.4,
        },
        {
            "query": "M1 미러 정렬 절차",
            "expected_keywords": ["M1", "mirror", "미러"],
            "min_score": 0.4,
        },
    ]

    all_passed = True
    for tc in test_queries:
        chunks = rag.retrieve(tc["query"], top_k=3)
        print(f"\n  Query: '{tc['query']}'")
        if not chunks:
            print("    FAIL: No chunks retrieved")
            all_passed = False
            continue

        top = chunks[0]
        print(f"    Top result: score={top['score']:.3f} | "
              f"{top['source']} > {top['section']}")
        print(f"    Text preview: {top['text'][:100]}...")

        # Check minimum score
        if top["score"] < tc["min_score"]:
            print(f"    FAIL: Score {top['score']:.3f} < {tc['min_score']}")
            all_passed = False
        else:
            print("    PASS: Score OK")

    return all_passed


# ── 3. LLM Answer Generation Test ─────────────────────────────────

class SimpleVLLMBackend:
    """Minimal vLLM backend for testing RAG answer generation."""

    def __init__(self, base_url="http://localhost:8000", model="Qwen/Qwen3-32B"):
        self.base_url = base_url
        self.model = model

    async def chat(self, system_prompt, messages, max_tokens=1024):
        """Call vLLM OpenAI-compatible chat endpoint."""
        import httpx

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
            ] + messages,
            "max_tokens": max_tokens,
            "temperature": 0.3,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]


async def test_rag_answer_generation(rag):
    """Test end-to-end: retrieve + generate answer via vLLM."""
    print("\n" + "=" * 60)
    print("TEST 3: RAG Answer Generation (via vLLM)")
    print("=" * 60)

    backend = SimpleVLLMBackend()

    # Check vLLM is accessible
    try:
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{backend.base_url}/v1/models")
            if resp.status_code != 200:
                print(f"  SKIP: vLLM not accessible (status={resp.status_code})")
                return None
            models = resp.json()
            print(f"  vLLM models: {[m['id'] for m in models.get('data', [])]}")
    except Exception as e:
        print(f"  SKIP: vLLM not accessible ({e})")
        return None

    test_queries = [
        ("DCM Si(111)과 Si(311) 차이가 뭐야?", "ko"),
        ("How does the KB mirror focus the beam?", "en"),
    ]

    all_passed = True
    for query, lang in test_queries:
        print(f"\n  Query ({lang}): '{query}'")

        t0 = time.time()
        chunks = rag.retrieve(query, top_k=5)
        t_retrieve = time.time() - t0
        print(f"    Retrieved {len(chunks)} chunks in {t_retrieve:.1f}s")

        if not chunks:
            print("    FAIL: No chunks retrieved")
            all_passed = False
            continue

        t0 = time.time()
        result = await rag.generate_answer(query, chunks, backend, language=lang)
        t_answer = time.time() - t0

        answer = result.get("answer", "")
        sources = result.get("sources", [])

        print(f"    Answer generated in {t_answer:.1f}s")
        print(f"    Sources: {sources[:3]}")
        print(f"    Answer preview ({len(answer)} chars):")
        # Show first 300 chars
        for line in answer[:300].split("\n"):
            print(f"      {line}")
        if len(answer) > 300:
            print("      ...")

        # Basic quality checks
        if len(answer) < 50:
            print(f"    FAIL: Answer too short ({len(answer)} chars)")
            all_passed = False
        elif not sources:
            print("    FAIL: No sources cited")
            all_passed = False
        else:
            print("    PASS: Answer quality OK")

    return all_passed


# ── Main ───────────────────────────────────────────────────────────

async def main():
    print("RAG Integration Test")
    print("=" * 60)

    results = {}

    # Test 1: Intent routing (no dependencies)
    results["intent_routing"] = test_intent_routing()

    # Test 2 & 3: Need RAG engine
    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    if not os.path.isdir(docs_dir):
        print(f"\nERROR: docs directory not found: {os.path.abspath(docs_dir)}")
        print("Skipping retrieval and answer generation tests.")
        results["retrieval"] = None
        results["answer_generation"] = None
    else:
        print(f"\nLoading RAG engine (docs: {os.path.abspath(docs_dir)})...")
        t0 = time.time()

        sys.path.insert(0, os.path.dirname(__file__))
        from rag_engine import BeamlineRAG

        rag = BeamlineRAG(docs_dir)
        count = rag.index_documents()
        t_load = time.time() - t0
        print(f"RAG engine ready: {count} chunks, loaded in {t_load:.1f}s")

        # Test 2: Retrieval
        results["retrieval"] = test_rag_retrieval(rag)

        # Test 3: Answer generation
        results["answer_generation"] = await test_rag_answer_generation(rag)

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    for test_name, passed in results.items():
        if passed is None:
            status = "SKIP"
        elif passed:
            status = "PASS"
        else:
            status = "FAIL"
        print(f"  {test_name}: {status}")

    all_ok = all(v is not False for v in results.values())
    print(f"\nOverall: {'ALL TESTS PASSED' if all_ok else 'SOME TESTS FAILED'}")
    return all_ok


if __name__ == "__main__":
    ok = asyncio.run(main())
    sys.exit(0 if ok else 1)
