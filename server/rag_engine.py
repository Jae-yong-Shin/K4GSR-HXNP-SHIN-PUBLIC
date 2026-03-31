"""
RAG (Retrieval-Augmented Generation) engine for K4GSR Beamline NLP system.

Indexes docs/ directory (MD + PDF) into a ChromaDB vector store,
retrieves relevant chunks for knowledge queries, and generates
answers via the existing LLM backend.

Usage (standalone test):
    python server/rag_engine.py
"""

import os
import re
import logging
import hashlib
import json
import time
from pathlib import Path
from typing import List, Dict, Optional

log = logging.getLogger("rag-engine")

# ── Optional imports (graceful degradation) ──────────────────────────
try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    _CHROMA_OK = True
except ImportError:
    _CHROMA_OK = False
    log.warning("chromadb not installed — RAG disabled")

try:
    from sentence_transformers import SentenceTransformer
    _ST_OK = True
except ImportError:
    _ST_OK = False
    log.warning("sentence-transformers not installed — RAG disabled")

try:
    from PyPDF2 import PdfReader
    _PDF_OK = True
except ImportError:
    _PDF_OK = False
    log.info("PyPDF2 not installed — PDF indexing disabled")


# ══════════════════════════════════════════════════════════════════════
# Constants
# ══════════════════════════════════════════════════════════════════════

EMBEDDING_MODEL = "intfloat/multilingual-e5-large"
COLLECTION_NAME = "beamline_docs"
CHUNK_MIN_LENGTH = 50       # skip chunks shorter than this (chars)
CHUNK_MAX_TOKENS = 1000     # approximate upper bound

RAG_SYNTHESIS_PROMPT = """You are a beamline scientist assistant for the K4GSR nanoprobe beamline (Korea-4GSR, ID10).
Answer the user's question using ONLY the provided context documents.

Rules:
1. Answer in {language_name}.
2. If the context doesn't contain enough information, say so honestly.
3. Cite the source document for each claim: [source: filename, Section Name]
4. Use specific numbers from the documents (energies in keV, distances in m/mm, sizes in um/nm).
5. Keep the answer concise but technically accurate.
6. If the question is about choosing between options, present trade-offs clearly.
7. Do NOT invent information not present in the context.

Context documents:
{context_chunks}

User question: {query}
"""

LANGUAGE_NAMES = {
    "ko": "Korean", "en": "English", "ja": "Japanese", "zh": "Chinese",
    "de": "German", "fr": "French", "es": "Spanish",
    "th": "Thai", "hi": "Hindi", "ar": "Arabic",
}


# ══════════════════════════════════════════════════════════════════════
# Chunking helpers
# ══════════════════════════════════════════════════════════════════════

def _parse_frontmatter(text: str) -> (dict, str):
    """Extract YAML front-matter from MD text. Returns (meta, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("---", 3)
    if end < 0:
        return {}, text
    fm_block = text[3:end].strip()
    body = text[end + 3:].strip()
    meta = {}
    for line in fm_block.split("\n"):
        if ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val.startswith("[") and val.endswith("]"):
                val = [v.strip().strip('"').strip("'")
                       for v in val[1:-1].split(",")]
            meta[key] = val
    return meta, body


def _chunk_markdown(text: str, source: str) -> List[Dict]:
    """Split markdown by ## headings into chunks."""
    meta, body = _parse_frontmatter(text)
    tags = meta.get("tags", [])
    if isinstance(tags, str):
        tags = [tags]

    chunks = []
    # Split on ## headings (keep heading with content)
    parts = re.split(r'^(##\s+.+)$', body, flags=re.MULTILINE)

    current_section = meta.get("title", source)
    current_text = ""

    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.startswith("## "):
            # Save previous chunk
            if current_text and len(current_text) >= CHUNK_MIN_LENGTH:
                chunks.append({
                    "text": current_text.strip(),
                    "source": source,
                    "section": current_section,
                    "tags": tags,
                })
            current_section = part[3:].strip()
            current_text = part + "\n"
        else:
            current_text += part + "\n"

    # Save last chunk
    if current_text and len(current_text) >= CHUNK_MIN_LENGTH:
        chunks.append({
            "text": current_text.strip(),
            "source": source,
            "section": current_section,
            "tags": tags,
        })

    # If no ## headings found, treat entire body as one chunk
    if not chunks and body and len(body) >= CHUNK_MIN_LENGTH:
        chunks.append({
            "text": body.strip(),
            "source": source,
            "section": current_section,
            "tags": tags,
        })

    return chunks


def _chunk_pdf(filepath: str) -> List[Dict]:
    """Split PDF into page-based chunks."""
    if not _PDF_OK:
        return []
    try:
        reader = PdfReader(filepath)
    except Exception as e:
        log.warning("Failed to read PDF %s: %s", filepath, e)
        return []

    source = os.path.basename(filepath)
    chunks = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text()
        except Exception as e:
            log.warning("Failed to extract text from %s page %d: %s",
                        filepath, i + 1, e)
            continue
        if text and len(text.strip()) >= CHUNK_MIN_LENGTH:
            chunks.append({
                "text": text.strip(),
                "source": source,
                "section": f"Page {i + 1}",
                "tags": ["spec", "pdf"],
            })
    return chunks


# ══════════════════════════════════════════════════════════════════════
# Custom Embedding Function for ChromaDB
# ══════════════════════════════════════════════════════════════════════

class E5EmbeddingFunction:
    """ChromaDB-compatible embedding function using multilingual-e5-large.

    Implements both legacy __call__ and new embed_query/embed_documents
    methods for ChromaDB >=1.5 compatibility.
    """

    def __init__(self, model: "SentenceTransformer"):
        self._model = model

    def name(self) -> str:
        return "multilingual-e5-large"

    def __call__(self, input: List[str]) -> List[List[float]]:
        embeddings = self._model.encode(input, normalize_embeddings=True)
        return embeddings.tolist()

    def embed_documents(self, input: List[str]) -> List[List[float]]:
        """Embed documents (for upsert). ChromaDB >=1.5 API."""
        return self.__call__(input)

    def embed_query(self, input: List[str]) -> List[List[float]]:
        """Embed queries (for search). ChromaDB >=1.5 API."""
        return self.__call__(input)


# ══════════════════════════════════════════════════════════════════════
# Main RAG Engine
# ══════════════════════════════════════════════════════════════════════

class BeamlineRAG:
    """Retrieval-Augmented Generation engine for beamline knowledge queries."""

    def __init__(self, docs_dir: str,
                 db_dir: str = None,
                 embedding_model: str = EMBEDDING_MODEL):
        if not _CHROMA_OK or not _ST_OK:
            raise ImportError(
                "RAG requires chromadb and sentence-transformers. "
                "Install with: pip install chromadb sentence-transformers"
            )

        self.docs_dir = os.path.abspath(docs_dir)
        if db_dir is None:
            db_dir = os.path.join(os.path.dirname(__file__), "chroma_db")
        self.db_dir = os.path.abspath(db_dir)

        # Load embedding model
        log.info("Loading embedding model: %s", embedding_model)
        self._model = SentenceTransformer(embedding_model)
        self._embed_fn = E5EmbeddingFunction(self._model)

        # Initialize ChromaDB
        os.makedirs(self.db_dir, exist_ok=True)
        self._client = chromadb.PersistentClient(path=self.db_dir)
        self._collection = self._client.get_or_create_collection(
            name=COLLECTION_NAME,
            embedding_function=self._embed_fn,
            metadata={"hnsw:space": "cosine"}
        )

        # Index state file (tracks file mtimes for incremental updates)
        self._state_file = os.path.join(self.db_dir, "_index_state.json")
        self._state = self._load_state()

    # ── State management ─────────────────────────────────────────────

    def _load_state(self) -> dict:
        if os.path.exists(self._state_file):
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"files": {}}

    def _save_state(self):
        with open(self._state_file, "w", encoding="utf-8") as f:
            json.dump(self._state, f, indent=2)

    # ── Document indexing ────────────────────────────────────────────

    def index_documents(self) -> int:
        """Index all MD/PDF files in docs_dir. Returns total chunk count.

        Uses mtime-based incremental indexing: only re-indexes changed files.
        """
        all_files = []

        # Directories to exclude from indexing (not knowledge sources)
        _EXCLUDE_DIRS = {"reviews", "archived", "Sample_stage_control"}

        # Collect MD/PDF files
        for root, dirs, files in os.walk(self.docs_dir):
            # Skip excluded directories
            dirs[:] = [d for d in dirs if d not in _EXCLUDE_DIRS]
            for fn in files:
                ext = fn.lower()
                if ext.endswith(".md"):
                    all_files.append(os.path.join(root, fn))
                elif ext.endswith(".pdf"):
                    all_files.append(os.path.join(root, fn))

        indexed_count = 0
        updated_files = 0
        known_files = self._state.get("files", {})

        for filepath in all_files:
            rel_path = os.path.relpath(filepath, self.docs_dir)
            mtime = os.path.getmtime(filepath)

            # Skip if already indexed and not modified
            if rel_path in known_files:
                if known_files[rel_path].get("mtime", 0) >= mtime:
                    indexed_count += known_files[rel_path].get("chunks", 0)
                    continue

            # Index this file
            if filepath.lower().endswith(".md"):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        text = f.read()
                    chunks = _chunk_markdown(text, rel_path)
                except Exception as e:
                    log.warning("Failed to read MD %s: %s", filepath, e)
                    continue
            elif filepath.lower().endswith(".pdf"):
                chunks = _chunk_pdf(filepath)
            else:
                continue

            if not chunks:
                continue

            # Remove old entries for this file
            old_ids = [
                doc_id for doc_id in self._get_ids_for_source(rel_path)
            ]
            if old_ids:
                self._collection.delete(ids=old_ids)

            # Prepare for upsert
            ids = []
            documents = []
            metadatas = []
            for i, chunk in enumerate(chunks):
                # Generate stable ID from source + section + index
                chunk_id = hashlib.md5(
                    f"{rel_path}::{chunk['section']}::{i}".encode()
                ).hexdigest()
                ids.append(chunk_id)
                # e5 models: prepend "passage: " for documents
                documents.append("passage: " + chunk["text"])
                metadatas.append({
                    "source": chunk["source"],
                    "section": chunk["section"],
                    "tags": ",".join(chunk.get("tags", [])),
                })

            # Batch upsert (ChromaDB handles embedding via the function)
            batch_size = 50
            for start in range(0, len(ids), batch_size):
                end = min(start + batch_size, len(ids))
                self._collection.upsert(
                    ids=ids[start:end],
                    documents=documents[start:end],
                    metadatas=metadatas[start:end],
                )

            known_files[rel_path] = {"mtime": mtime, "chunks": len(chunks)}
            indexed_count += len(chunks)
            updated_files += 1
            log.info("Indexed %s: %d chunks", rel_path, len(chunks))

        self._state["files"] = known_files
        self._save_state()

        total = self._collection.count()
        log.info("Indexing complete: %d files updated, %d total chunks in DB",
                 updated_files, total)
        return total

    def _get_ids_for_source(self, source: str) -> List[str]:
        """Get all chunk IDs for a given source file."""
        try:
            results = self._collection.get(
                where={"source": source},
                include=[]
            )
            return results.get("ids", [])
        except Exception:
            return []

    # ── Retrieval ────────────────────────────────────────────────────

    def retrieve(self, query: str, top_k: int = 5) -> List[Dict]:
        """Retrieve top-k relevant chunks for a query.

        Returns list of dicts: {text, source, section, score}
        """
        if self._collection.count() == 0:
            return []

        # e5 models: prepend "query: " for queries
        query_text = "query: " + query

        results = self._collection.query(
            query_texts=[query_text],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "metadatas", "distances"]
        )

        chunks = []
        if results and results["documents"]:
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            dists = results["distances"][0]

            for doc, meta, dist in zip(docs, metas, dists):
                # Remove "passage: " prefix from stored document
                text = doc
                if text.startswith("passage: "):
                    text = text[9:]
                chunks.append({
                    "text": text,
                    "source": meta.get("source", "unknown"),
                    "section": meta.get("section", ""),
                    "score": 1.0 - dist,  # cosine distance → similarity
                })

        return chunks

    # ── Answer generation ────────────────────────────────────────────

    async def generate_answer(self, query: str, chunks: List[Dict],
                               llm_backend, language: str = "ko") -> Dict:
        """Generate an answer from retrieved chunks using the LLM backend.

        Parameters
        ----------
        query : str
            User's original question.
        chunks : list
            Retrieved chunks from retrieve().
        llm_backend : object
            LLM backend with async chat() method.
        language : str
            Response language code.

        Returns
        -------
        dict : {"answer": str, "sources": [str]}
        """
        # Build context string from chunks
        context_parts = []
        sources = []
        for i, chunk in enumerate(chunks):
            source_label = f"{chunk['source']}"
            if chunk.get("section"):
                source_label += f", {chunk['section']}"
            context_parts.append(
                f"[Document {i + 1}: {source_label}]\n{chunk['text']}\n"
            )
            source_str = source_label
            if source_str not in sources:
                sources.append(source_str)

        context_text = "\n".join(context_parts)
        language_name = LANGUAGE_NAMES.get(language, "English")

        system_prompt = RAG_SYNTHESIS_PROMPT.format(
            language_name=language_name,
            context_chunks=context_text,
            query=query,
        )

        messages = [{"role": "user", "content": query}]

        try:
            answer = await llm_backend.chat(system_prompt, messages, 1024)
        except Exception as e:
            log.error("RAG LLM call failed: %s", e)
            answer = f"Failed to generate answer: {e}"

        return {"answer": answer, "sources": sources}


# ══════════════════════════════════════════════════════════════════════
# Standalone test
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    docs_dir = os.path.join(os.path.dirname(__file__), "..", "docs")
    if not os.path.isdir(docs_dir):
        print(f"docs directory not found: {docs_dir}")
        sys.exit(1)

    print(f"Indexing documents from: {os.path.abspath(docs_dir)}")
    t0 = time.time()
    rag = BeamlineRAG(docs_dir)
    count = rag.index_documents()
    elapsed = time.time() - t0
    print(f"Indexed {count} chunks in {elapsed:.1f}s")

    # Test retrieval
    test_queries = [
        "DCM Si(111)과 Si(311) 차이가 뭐야?",
        "KB mirror focal length",
        "M1 alignment procedure",
    ]
    for q in test_queries:
        print(f"\n--- Query: {q} ---")
        results = rag.retrieve(q, top_k=3)
        for i, r in enumerate(results):
            print(f"  [{i + 1}] score={r['score']:.3f} | "
                  f"{r['source']} > {r['section']}")
            print(f"      {r['text'][:120]}...")
