from langchain_community.document_loaders import PyPDFLoader
from langchain.schema import Document


def process_pdf(filename: str):
    """
    Parse a PDF into LangChain Documents
    """
    try:
        loader = PyPDFLoader(filename)
        docs = loader.load()  # one Document per page
        return docs
    except Exception as e:
        #return error as a doc so the app still renders
        return [Document(page_content=f"PDF parse error: {e}")]
