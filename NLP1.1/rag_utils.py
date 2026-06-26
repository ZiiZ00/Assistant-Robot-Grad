import os
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import FAISS
from langchain_huggingface import HuggingFaceEmbeddings

def build_vectorstore_from_pdfs(pdf_folder: str, save_path: str):
    """
    Load all PDFs from a folder, split into chunks, and create a FAISS vector store.
    
    Args:
        pdf_folder: Path to folder containing PDF files
        save_path: Path where the vector store will be saved
    """
    all_docs = []

    # Load all PDFs in the folder
    print(f"Loading PDFs from: {pdf_folder}")
    for filename in os.listdir(pdf_folder):
        if filename.endswith(".pdf"):
            print(f"  Loading: {filename}")
            loader = PyPDFLoader(os.path.join(pdf_folder, filename))
            docs = loader.load()
            all_docs.extend(docs)
            print(f"    Loaded {len(docs)} pages")

    print(f"\nTotal pages loaded: {len(all_docs)}")

    # Split documents into chunks
    splitter = RecursiveCharacterTextSplitter(chunk_size=500, chunk_overlap=100)
    chunks = splitter.split_documents(all_docs)
    print(f"Split into {len(chunks)} chunks")

    # Use HuggingFace embeddings (local model)
    print("Loading embedding model...")
    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2"
    )

    # Build FAISS vectorstore
    print("Building FAISS vector store...")
    vectorstore = FAISS.from_documents(chunks, embeddings)
    vectorstore.save_local(save_path)
    print(f"✅ Vector store saved to: {save_path}")

if __name__ == "__main__":
    build_vectorstore_from_pdfs("Data", "vectorstore")
